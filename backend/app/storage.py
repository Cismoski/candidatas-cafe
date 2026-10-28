"""Layout em disco: {data_dir}/users/{owner_id}/{analysis_id}/{inputs,outputs}.

Nenhum nome vindo do cliente vira caminho: diretórios são UUIDs gerados pelo
servidor e arquivos têm nomes fixos. Mesmo assim, todo caminho é resolvido e
conferido contra a raiz (defesa em profundidade contra path traversal).
"""

import contextlib
import shutil
import time
import uuid
from pathlib import Path

INPUT_NAMES = {"primary": "primaria.tif", "scl": "scl.tif", "secondary": "secundaria.tif"}

# Arquivos que o cliente pode baixar: nome público -> (arquivo, media type, anexo?)
DOWNLOADS: dict[str, tuple[str, str, bool]] = {
    "geojson": ("candidatas.geojson", "application/geo+json", True),
    "png": ("classificacao.png", "image/png", True),
    "geotiff": ("classes.tif", "image/tiff", True),
    "overlay-rgb": ("overlay_rgb.png", "image/png", False),
    "overlay-classes": ("overlay_classes.png", "image/png", False),
}


class Storage:
    def __init__(self, data_dir: Path):
        self.root = (data_dir / "users").resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _safe(self, *parts: str) -> Path:
        for p in parts:
            uuid.UUID(p)  # só UUIDs viram diretório; ValueError caso contrário
        path = self.root.joinpath(*parts).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("caminho fora da raiz de dados")
        return path

    def analysis_dir(self, owner_id: str, analysis_id: str) -> Path:
        return self._safe(owner_id, analysis_id)

    def inputs_dir(self, owner_id: str, analysis_id: str) -> Path:
        return self.analysis_dir(owner_id, analysis_id) / "inputs"

    def outputs_dir(self, owner_id: str, analysis_id: str) -> Path:
        return self.analysis_dir(owner_id, analysis_id) / "outputs"

    def remove_analysis(self, owner_id: str, analysis_id: str) -> None:
        shutil.rmtree(self.analysis_dir(owner_id, analysis_id), ignore_errors=True)

    def remove_orphans(self, known_ids: set[str], grace_seconds: float = 3600) -> int:
        """Remove diretórios de análise sem registro no banco (ex.: crash no meio do delete).

        Diretórios modificados há menos de grace_seconds são poupados: os
        arquivos do upload são gravados antes da linha no banco existir, e
        known_ids é um retrato tirado antes da varredura.
        """
        removed = 0
        cutoff = time.time() - grace_seconds
        for owner in self.root.iterdir():
            if not owner.is_dir():
                continue
            for d in owner.iterdir():
                if d.name in known_ids:
                    continue
                with contextlib.suppress(FileNotFoundError):  # apagado em paralelo
                    if d.is_dir() and d.stat().st_mtime < cutoff:
                        shutil.rmtree(d, ignore_errors=True)
                        removed += 1
            with contextlib.suppress(OSError):  # não vazio ou recriado por um upload
                owner.rmdir()
        return removed
