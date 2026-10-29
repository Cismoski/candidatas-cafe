"""Execução das análises fora do ciclo da requisição.

- Fila própria: um ThreadPoolExecutor de 1 thread, separado do threadpool do
  FastAPI. Jobs esperando na fila não ocupam threads das rotas, então /health
  e as demais rotas continuam respondendo com a fila cheia. O tamanho da fila
  é limitado na rota (503 acima de max_queued_jobs).
- O processamento roda num SUBPROCESSO (spawn) com timeout:
  * a memória do numpy/GDAL volta ao sistema quando o processo termina
    (o plano gratuito tem 512 MB);
  * um OOM-kill ou travamento mata só o filho, não a API;
  * o timeout é aplicado de fato (terminate), o que uma thread não permite;
  * apagar a análise em processamento termina o filho (cancel).
- Os produtos são gerados em outputs.tmp/ e só então renomeados para outputs/
  (rename atômico no mesmo filesystem): nunca existe saída pela metade.
- Se a análise foi apagada no meio do caminho, o resultado é descartado.
"""

import json
import logging
import multiprocessing as mp
import shutil
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from multiprocessing.process import BaseProcess
from pathlib import Path

from .db import Database
from .processing.config import ClassificationConfig
from .storage import INPUT_NAMES, Storage

log = logging.getLogger("cafe.jobs")

GENERIC_ERROR = "Não foi possível processar a imagem. Verifique o arquivo e tente novamente."
TIMEOUT_ERROR = "O processamento excedeu o tempo limite. Tente uma imagem menor."
OOM_ERROR = "O processamento foi interrompido (memória insuficiente). Tente uma imagem menor."
ERROR_FILE = "_erro.json"
EXIT_SCENE_ERROR = 3


def _child(
    primary: str,
    out_dir: str,
    cfg: dict,
    scl: str | None,
    secondary: str | None,
    reference_url: str | None = None,
) -> None:
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
            reference_url=reference_url or None,
        )
    except SceneError as e:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        (Path(out_dir) / ERROR_FILE).write_text(json.dumps({"error": str(e)}), "utf-8")
        sys.exit(EXIT_SCENE_ERROR)


def _scene_error(tmp: Path) -> str:
    try:
        return json.loads((tmp / ERROR_FILE).read_text("utf-8"))["error"]
    except (OSError, ValueError, KeyError):
        return GENERIC_ERROR


def run_isolated(args: tuple, tmp: Path, timeout_s: float, on_start=None) -> str | None:
    """Executa o pipeline num subprocesso; devolve mensagem de erro ou None."""
    proc = mp.get_context("spawn").Process(target=_child, args=args, daemon=True)
    proc.start()
    if on_start:
        on_start(proc)
    proc.join(timeout_s)
    if proc.is_alive():
        _terminate(proc)
        return TIMEOUT_ERROR
    if proc.exitcode == 0:
        return None
    if proc.exitcode == EXIT_SCENE_ERROR:
        return _scene_error(tmp)
    if proc.exitcode is not None and proc.exitcode < 0:  # morto por sinal (OOM killer, cancel)
        log.error("subprocesso morto pelo sinal %d", -proc.exitcode)
        return OOM_ERROR
    log.error("subprocesso terminou com código %s", proc.exitcode)
    return GENERIC_ERROR


def run_inline(args: tuple, tmp: Path) -> str | None:
    """Mesmo contrato de run_isolated, no próprio processo (só para testes)."""
    try:
        _child(*args)
    except SystemExit:
        return _scene_error(tmp)
    return None


def _terminate(proc: BaseProcess) -> None:
    proc.terminate()
    proc.join(5)
    if proc.is_alive():
        proc.kill()
        proc.join()


class JobRunner:
    def __init__(
        self,
        db: Database,
        storage: Storage,
        cfg: ClassificationConfig,
        *,
        isolate: bool = True,
        timeout_s: int = 300,
        reference_url: str = "",
    ):
        self.db, self.storage, self.cfg = db, storage, cfg
        self.reference_url = reference_url
        self.isolate, self.timeout_s = isolate, timeout_s
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="analysis")
        self._lock = threading.Lock()
        self._running: dict[str, BaseProcess] = {}
        self._futures: set[Future] = set()

    def submit(self, owner_id: str, analysis_id: str) -> None:
        fut = self._executor.submit(self._process, owner_id, analysis_id)
        with self._lock:
            self._futures.add(fut)
        fut.add_done_callback(self._forget)

    def _forget(self, fut: Future) -> None:
        with self._lock:
            self._futures.discard(fut)

    def cancel(self, analysis_id: str) -> None:
        """Chamado ao apagar a análise: termina o subprocesso, se estiver rodando."""
        with self._lock:
            proc = self._running.get(analysis_id)
        if proc is not None and proc.is_alive():
            _terminate(proc)

    def drain(self, timeout: float | None = None) -> None:
        """Espera a fila esvaziar (testes e desligamento)."""
        with self._lock:
            pending = list(self._futures)
        wait(pending, timeout=timeout)

    def shutdown(self) -> None:
        with self._lock:
            procs = list(self._running.values())
        for p in procs:
            _terminate(p)
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _process(self, owner_id: str, analysis_id: str) -> None:
        try:
            self._process_unsafe(owner_id, analysis_id)
        except Exception:
            # Nunca deixa exceção escapar da thread: registra e marca falha.
            log.exception("falha inesperada no job %s", analysis_id)
            if not self.db.set_status(analysis_id, "failed", error=GENERIC_ERROR):
                self.storage.remove_analysis(owner_id, analysis_id)
        finally:
            with self._lock:
                self._running.pop(analysis_id, None)

    def _process_unsafe(self, owner_id: str, analysis_id: str) -> None:
        if not self.db.set_status(analysis_id, "processing"):
            return  # apagada antes de começar
        inputs = self.storage.inputs_dir(owner_id, analysis_id)
        final = self.storage.outputs_dir(owner_id, analysis_id)
        tmp = final.with_name("outputs.tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        args = (
            str(inputs / INPUT_NAMES["primary"]),
            str(tmp),
            self.cfg.model_dump(),
            _optional(inputs / INPUT_NAMES["scl"]),
            _optional(inputs / INPUT_NAMES["secondary"]),
            self.reference_url,
        )
        t0 = time.perf_counter()
        if self.isolate:
            error = run_isolated(args, tmp, self.timeout_s, on_start=self._register(analysis_id))
        else:
            error = run_inline(args, tmp)

        try:
            if error is None:
                summary = json.loads((tmp / "summary.json").read_text("utf-8"))
                shutil.rmtree(final, ignore_errors=True)
                tmp.rename(final)
        except FileNotFoundError:
            # a análise foi apagada enquanto processava
            self.storage.remove_analysis(owner_id, analysis_id)
            return

        if error is not None:
            shutil.rmtree(tmp, ignore_errors=True)
            done = self.db.set_status(analysis_id, "failed", error=error)
        else:
            log.info("análise %s processada em %.1fs", analysis_id, time.perf_counter() - t0)
            done = self.db.set_status(analysis_id, "done", summary=summary)
        if not done:  # apagada durante o processamento
            self.storage.remove_analysis(owner_id, analysis_id)

    def _register(self, analysis_id: str):
        def on_start(proc: BaseProcess) -> None:
            with self._lock:
                self._running[analysis_id] = proc

        return on_start


def _optional(p: Path) -> str | None:
    return str(p) if p.exists() else None
