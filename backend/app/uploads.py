"""Recebimento e validação de uploads.

Camadas de defesa, da mais barata para a mais cara:
1. LimitUploadSizeMiddleware: corta o corpo da requisição acima do limite (413)
   antes de o multipart ser gravado em disco, mesmo sem Content-Length.
2. Cópia em streaming para um nome gerado pelo servidor, contando bytes.
3. Assinatura mágica TIFF/BigTIFF (não confia em extensão nem em Content-Type).
4. Abertura com rasterio: driver GTiff, bandas, dtype, CRS projetado em metros,
   dimensões máximas e tamanho de pixel.
"""

import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from fastapi import HTTPException, UploadFile
from rasterio.errors import RasterioIOError
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .processing.reading import crs_problem, grid_problem

TIFF_MAGIC = (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+")
CHUNK = 1024 * 1024


class UploadRejected(ValueError):
    """Mensagem destinada ao usuário (português, sem detalhes internos)."""


class BodyTooLarge(HTTPException):
    """HTTPException para atravessar o parser de formulário do FastAPI como 413
    (outras exceções lá dentro viram 400 genérico)."""

    def __init__(self, max_bytes: int):
        mb = max_bytes // (1024 * 1024)
        super().__init__(413, f"Arquivo grande demais (máximo {mb} MB no total).")


class LimitUploadSizeMiddleware:
    """Middleware ASGI puro: conta os bytes do corpo e aborta acima do limite."""

    def __init__(self, app: ASGIApp, max_bytes: int, paths: tuple[str, ...]):
        self.app, self.max_bytes, self.paths = app, max_bytes, paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(self.paths):
            return await self.app(scope, receive, send)
        for name, value in scope.get("headers", []):
            if name == b"content-length" and value.isdigit() and int(value) > self.max_bytes:
                return await _send_413(send, self.max_bytes)
        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            msg = await receive()
            if msg["type"] == "http.request":
                received += len(msg.get("body", b""))
                if received > self.max_bytes:
                    raise BodyTooLarge(self.max_bytes)
            return msg

        try:
            await self.app(scope, limited_receive, send)
        except BodyTooLarge:
            await _send_413(send, self.max_bytes)


async def _send_413(send: Send, max_bytes: int) -> None:
    mb = max_bytes // (1024 * 1024)
    body = f'{{"detail":"Arquivo grande demais (máximo {mb} MB no total)."}}'.encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def save_upload(upload: UploadFile, dest: Path, max_bytes: int) -> int:
    """Copia em blocos para dest (nome do servidor). O filename do cliente é ignorado."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    upload.file.seek(0)
    with open(dest, "wb") as out:
        while chunk := upload.file.read(CHUNK):
            size += len(chunk)
            if size > max_bytes:
                raise UploadRejected("Arquivo grande demais.")
            out.write(chunk)
    if size == 0:
        raise UploadRejected("Arquivo vazio.")
    with open(dest, "rb") as f:
        if f.read(4) not in TIFF_MAGIC:
            raise UploadRejected("O arquivo não é um GeoTIFF (.tif).")
    return size


@dataclass(frozen=True)
class RasterLimits:
    max_dim: int
    min_bands: int = 4
    min_pixel_m: float = 5.0
    max_pixel_m: float = 60.0


def _open(path: Path, label: str):
    try:
        return rasterio.open(path)
    except RasterioIOError:
        raise UploadRejected(f"{label}: não foi possível ler o arquivo como GeoTIFF.") from None


def validate_multispectral(path: Path, limits: RasterLimits, label: str = "Imagem") -> None:
    with _open(path, label) as ds:
        if ds.driver != "GTiff":
            raise UploadRejected(f"{label}: formato {ds.driver} não suportado; envie GeoTIFF.")
        if ds.count < limits.min_bands:
            raise UploadRejected(
                f"{label}: são necessárias {limits.min_bands} bandas (B02, B03, B04, B08); "
                f"o arquivo tem {ds.count}."
            )
        if any(t != "uint16" for t in ds.dtypes):
            raise UploadRejected(f"{label}: as bandas devem ser uint16 (DN do Sentinel-2 L2A).")
        _check_crs_and_size(ds, limits, label)


def validate_scl(path: Path, limits: RasterLimits) -> None:
    label = "SCL"
    with _open(path, label) as ds:
        if ds.driver != "GTiff" or ds.count != 1:
            raise UploadRejected("SCL: esperado GeoTIFF de 1 banda.")
        if not np.issubdtype(np.dtype(ds.dtypes[0]), np.integer):
            raise UploadRejected("SCL: a banda deve ser inteira (classes de 0 a 11).")
        # SCL nativa tem 20 m; aceita a mesma faixa de pixel da imagem
        _check_crs_and_size(ds, limits, label)


def _check_crs_and_size(ds, limits: RasterLimits, label: str) -> None:
    # Mesmas regras do pipeline (uma fonte de verdade), checadas só pelo cabeçalho
    problem = crs_problem(ds.crs) or grid_problem(ds.transform)
    if problem:
        raise UploadRejected(f"{label}: {problem}.")
    if ds.width > limits.max_dim or ds.height > limits.max_dim:
        raise UploadRejected(
            f"{label}: {ds.width}x{ds.height} px excede o máximo de {limits.max_dim}x{limits.max_dim}."
        )
    res_x, res_y = abs(ds.transform.a), abs(ds.transform.e)
    if not (limits.min_pixel_m <= min(res_x, res_y) and max(res_x, res_y) <= limits.max_pixel_m):
        raise UploadRejected(
            f"{label}: pixel de {res_x:g} m fora da faixa aceita "
            f"({limits.min_pixel_m:g}-{limits.max_pixel_m:g} m)."
        )


def discard(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
