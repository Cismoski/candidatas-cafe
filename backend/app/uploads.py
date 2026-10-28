"""Recebimento e validação de uploads.

Camadas de defesa, da mais barata para a mais cara:
1. BodySizeLimitMiddleware: limite de corpo em TODAS as rotas (64 KB por
   padrão; o limite de upload só em POST /analyses), por Content-Length e
   contando os bytes recebidos (cobre corpo chunked).
2. auth.BearerPrecheckMiddleware: POST /analyses sem token válido recebe 401
   antes de o multipart ser lido.
3. Formulário com no máximo 3 arquivos e 1 campo de texto.
4. Cópia em streaming para um nome gerado pelo servidor.
5. Assinatura mágica TIFF/BigTIFF (não confia em extensão nem em Content-Type).
6. Abertura com rasterio, só pelo cabeçalho: driver GTiff, número de bandas
   (mínimo E máximo), uint16, CRS UTM, dimensões, tamanho de pixel e tamanho
   decodificado. Um TIFF comprimido pequeno pode declarar gigabytes.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from fastapi import HTTPException
from starlette.datastructures import UploadFile
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .processing.reading import crs_problem, grid_problem

TIFF_MAGIC = (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+")
CHUNK = 1024 * 1024


class UploadRejected(ValueError):
    """Mensagem destinada ao usuário (português, sem detalhes internos)."""


class BodyTooLarge(HTTPException):
    """HTTPException para atravessar o parser de formulário como 413
    (outras exceções lá dentro viram 400 genérico)."""

    def __init__(self, max_bytes: int):
        super().__init__(413, _too_large_msg(max_bytes))


def _too_large_msg(max_bytes: int) -> str:
    if max_bytes >= 1024 * 1024:
        return f"Arquivo grande demais (máximo {max_bytes // (1024 * 1024)} MB no total)."
    return "Requisição grande demais."


class BodySizeLimitMiddleware:
    """Middleware ASGI puro: limita o corpo de toda requisição.

    `overrides` mapeia (método, caminho exato) -> limite próprio.
    """

    def __init__(self, app: ASGIApp, default_max: int, overrides: dict[tuple[str, str], int]):
        self.app, self.default_max, self.overrides = app, default_max, overrides

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = self.overrides.get((scope["method"], scope["path"]), self.default_max)
        for name, value in scope.get("headers", []):
            if name == b"content-length" and (not value.isdigit() or int(value) > limit):
                return await _send_413(send, limit)
        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            msg = await receive()
            if msg["type"] == "http.request":
                received += len(msg.get("body", b""))
                if received > limit:
                    raise BodyTooLarge(limit)
            return msg

        try:
            await self.app(scope, limited_receive, send)
        except BodyTooLarge:
            await _send_413(send, limit)


async def _send_413(send: Send, max_bytes: int) -> None:
    body = f'{{"detail":"{_too_large_msg(max_bytes)}"}}'.encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"connection", b"close"),
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
    max_bands: int = 13  # o Sentinel-2 tem 13 bandas; mais que isso não é um produto S2
    min_pixel_m: float = 5.0
    max_pixel_m: float = 60.0

    @property
    def max_decoded_bytes(self) -> int:
        return self.max_bands * self.max_dim * self.max_dim * 2


def _open(path: Path, label: str):
    try:
        return rasterio.open(path)
    except Exception:  # RasterioIOError, CRSError, erros do driver...
        raise UploadRejected(f"{label}: não foi possível ler o arquivo como GeoTIFF.") from None


def validate_multispectral(path: Path, limits: RasterLimits, label: str = "Imagem") -> None:
    with _open(path, label) as ds:
        if ds.driver != "GTiff":
            raise UploadRejected(f"{label}: formato {ds.driver} não suportado; envie GeoTIFF.")
        if not limits.min_bands <= ds.count <= limits.max_bands:
            raise UploadRejected(
                f"{label}: são necessárias de {limits.min_bands} a {limits.max_bands} bandas "
                f"(B02, B03, B04, B08 nas 4 primeiras); o arquivo tem {ds.count}."
            )
        if any(t != "uint16" for t in ds.dtypes):
            raise UploadRejected(f"{label}: as bandas devem ser uint16 (DN do Sentinel-2 L2A).")
        _check_crs_and_size(ds, limits, label, bytes_per_px=2 * ds.count)


def validate_scl(path: Path, limits: RasterLimits) -> None:
    label = "SCL"
    with _open(path, label) as ds:
        if ds.driver != "GTiff" or ds.count != 1:
            raise UploadRejected("SCL: esperado GeoTIFF de 1 banda.")
        dtype = np.dtype(ds.dtypes[0])
        if not np.issubdtype(dtype, np.integer):
            raise UploadRejected("SCL: a banda deve ser inteira (classes de 0 a 11).")
        _check_crs_and_size(ds, limits, label, bytes_per_px=dtype.itemsize)


def _check_crs_and_size(ds, limits: RasterLimits, label: str, bytes_per_px: int) -> None:
    # Mesmas regras do pipeline (uma fonte de verdade), checadas só pelo cabeçalho
    problem = crs_problem(ds.crs) or grid_problem(ds.transform)
    if problem:
        raise UploadRejected(f"{label}: {problem}.")
    if ds.width > limits.max_dim or ds.height > limits.max_dim:
        raise UploadRejected(
            f"{label}: {ds.width}x{ds.height} px excede o máximo de {limits.max_dim}x{limits.max_dim}."
        )
    if ds.width * ds.height * bytes_per_px > limits.max_decoded_bytes:
        raise UploadRejected(f"{label}: o raster descomprimido é grande demais.")
    res_x, res_y = abs(ds.transform.a), abs(ds.transform.e)
    if not (limits.min_pixel_m <= min(res_x, res_y) and max(res_x, res_y) <= limits.max_pixel_m):
        raise UploadRejected(
            f"{label}: pixel de {res_x:g} m fora da faixa aceita "
            f"({limits.min_pixel_m:g}-{limits.max_pixel_m:g} m)."
        )
