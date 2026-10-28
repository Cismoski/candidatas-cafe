"""Execução das análises fora do ciclo da requisição.

- A rota agenda via BackgroundTasks (threadpool): o event loop nunca bloqueia.
- O processamento roda num SUBPROCESSO (spawn) com timeout:
  * a memória do numpy/GDAL volta ao sistema quando o processo termina
    (o plano gratuito tem 512 MB);
  * um OOM-kill ou travamento mata só o filho, não a API;
  * o timeout é aplicado de fato (terminate), o que uma thread não permite.
- Um semáforo limita a 1 processamento simultâneo.
- Os produtos são gerados em outputs.tmp/ e só então renomeados para outputs/
  (rename atômico no mesmo filesystem): nunca existe saída pela metade.
- Se a análise foi apagada enquanto processava, o resultado é descartado.
"""

import json
import logging
import multiprocessing as mp
import shutil
import threading
import time
from pathlib import Path

from .db import Database
from .processing.config import ClassificationConfig
from .storage import INPUT_NAMES, Storage

log = logging.getLogger("globalwatch.jobs")
_slots = threading.BoundedSemaphore(1)

GENERIC_ERROR = "Não foi possível processar a imagem. Verifique o arquivo e tente novamente."
TIMEOUT_ERROR = "O processamento excedeu o tempo limite. Tente uma imagem menor."
OOM_ERROR = "O processamento foi interrompido (memória insuficiente). Tente uma imagem menor."
ERROR_FILE = "_erro.json"
EXIT_SCENE_ERROR = 3


def _child(primary: str, out_dir: str, cfg: dict, scl: str | None, secondary: str | None) -> None:
    """Ponto de entrada do subprocesso. Imports aqui: o pai não precisa carregá-los."""
    import sys

    from .processing.pipeline import run_analysis
    from .processing.reading import SceneError

    try:
        run_analysis(
            Path(primary),
            Path(out_dir),
            ClassificationConfig.model_validate(cfg),
            scl_path=Path(scl) if scl else None,
            secondary_path=Path(secondary) if secondary else None,
        )
    except SceneError as e:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        (Path(out_dir) / ERROR_FILE).write_text(json.dumps({"error": str(e)}), "utf-8")
        sys.exit(EXIT_SCENE_ERROR)


def _run(args: tuple, tmp: Path, isolate: bool, timeout_s: int) -> str | None:
    """Executa o pipeline; devolve mensagem de erro para o usuário ou None."""
    if not isolate:  # testes: mesmo processo, mesma semântica de erro
        try:
            _child(*args)
        except SystemExit:
            return json.loads((tmp / ERROR_FILE).read_text("utf-8"))["error"]
        return None

    proc = mp.get_context("spawn").Process(target=_child, args=args, daemon=True)
    proc.start()
    proc.join(timeout_s)
    if proc.is_alive():
        proc.terminate()
        proc.join(5)
        if proc.is_alive():
            proc.kill()
            proc.join()
        return TIMEOUT_ERROR
    if proc.exitcode == 0:
        return None
    if proc.exitcode == EXIT_SCENE_ERROR:
        return json.loads((tmp / ERROR_FILE).read_text("utf-8"))["error"]
    if proc.exitcode is not None and proc.exitcode < 0:  # morto por sinal (ex.: OOM killer)
        log.error("subprocesso morto pelo sinal %d", -proc.exitcode)
        return OOM_ERROR
    log.error("subprocesso terminou com código %s", proc.exitcode)
    return GENERIC_ERROR


def process_analysis(
    db: Database,
    storage: Storage,
    cfg: ClassificationConfig,
    owner_id: str,
    analysis_id: str,
    *,
    isolate: bool = True,
    timeout_s: int = 300,
) -> None:
    with _slots:
        if not db.set_status(analysis_id, "processing"):
            return  # apagada antes de começar
        inputs = storage.inputs_dir(owner_id, analysis_id)
        final = storage.outputs_dir(owner_id, analysis_id)
        tmp = final.with_name("outputs.tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        args = (
            str(inputs / INPUT_NAMES["primary"]),
            str(tmp),
            cfg.model_dump(),
            _optional(inputs / INPUT_NAMES["scl"]),
            _optional(inputs / INPUT_NAMES["secondary"]),
        )
        t0 = time.perf_counter()
        try:
            error = _run(args, tmp, isolate, timeout_s)
        except Exception:
            log.exception("falha ao processar análise %s", analysis_id)
            error = GENERIC_ERROR
        if error is not None:
            shutil.rmtree(tmp, ignore_errors=True)
            if not db.set_status(analysis_id, "failed", error=error):
                storage.remove_analysis(owner_id, analysis_id)
            return
        summary = json.loads((tmp / "summary.json").read_text("utf-8"))
        shutil.rmtree(final, ignore_errors=True)
        tmp.rename(final)
        log.info("análise %s processada em %.1fs", analysis_id, time.perf_counter() - t0)
        if not db.set_status(analysis_id, "done", summary=summary):
            storage.remove_analysis(owner_id, analysis_id)  # apagada durante o processamento


def _optional(p: Path) -> str | None:
    return str(p) if p.exists() else None
