"""Leitura de cenas e alinhamento de rasters auxiliares na grade da cena principal."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
import rasterio
from affine import Affine
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.warp import reproject

from .config import ClassificationConfig
from .radiometry import dn_to_reflectance, resolve_scale_offset

F32 = npt.NDArray[np.float32]


class SceneError(ValueError):
    """Raster que não atende aos requisitos do pipeline (mensagem vai para o usuário)."""


@dataclass(frozen=True)
class Grid:
    crs: CRS
    transform: Affine
    height: int
    width: int

    @property
    def pixel_area_m2(self) -> float:
        return abs(self.transform.a * self.transform.e - self.transform.b * self.transform.d)

    def same_as(self, other: "Grid") -> bool:
        return (
            self.crs == other.crs
            and self.transform.almost_equals(other.transform)
            and (self.height, self.width) == (other.height, other.width)
        )


@dataclass
class Scene:
    grid: Grid
    blue: F32
    green: F32
    red: F32
    nir: F32
    valid: npt.NDArray[np.bool_]
    acquired_utc: str | None
    source_item: str | None
    radiometry_source: str


def _check_grid(ds: rasterio.DatasetReader) -> Grid:
    if ds.crs is None:
        raise SceneError("o raster não tem sistema de referência (CRS)")
    if not ds.crs.is_projected or (ds.crs.linear_units or "").lower() not in {"metre", "meter"}:
        raise SceneError(
            f"CRS {ds.crs.to_string()} não é projetado em metros; use UTM (ex.: EPSG:32723)"
        )
    if ds.transform.b != 0 or ds.transform.d != 0:
        raise SceneError("raster rotacionado não é suportado")
    return Grid(ds.crs, ds.transform, ds.height, ds.width)


def _reflectance_bands(
    dn: npt.NDArray[np.integer], scales, offsets, cfg: ClassificationConfig
) -> dict[str, F32]:
    out = {}
    for name in ("blue", "green", "red", "nir"):
        i = getattr(cfg.bands, name) - 1
        out[name] = dn_to_reflectance(dn[i], scales[i], offsets[i], cfg.radiometry.nodata_dn)
    return out


def _scene_from_dn(dn, ds, grid: Grid, cfg: ClassificationConfig) -> Scene:
    scales, offsets, source = resolve_scale_offset(
        ds.scales, ds.offsets, cfg.radiometry.default_scale, cfg.radiometry.default_offset
    )
    bands = _reflectance_bands(dn, scales, offsets, cfg)
    valid = np.logical_and.reduce([np.isfinite(b) for b in bands.values()])
    tags = ds.tags()
    return Scene(
        grid=grid,
        valid=valid,
        acquired_utc=tags.get("ACQUISITION_UTC"),
        source_item=tags.get("SOURCE_ITEM"),
        radiometry_source=source,
        **bands,
    )


def _require_bands(ds: rasterio.DatasetReader, cfg: ClassificationConfig) -> None:
    needed = max(cfg.bands.blue, cfg.bands.green, cfg.bands.red, cfg.bands.nir)
    if ds.count < needed:
        raise SceneError(
            f"esperadas ao menos {needed} bandas (B02, B03, B04, B08); recebidas {ds.count}"
        )
    if any(not np.issubdtype(np.dtype(t), np.integer) for t in ds.dtypes):
        raise SceneError(
            "esperado DN inteiro (uint16) como no produto L2A; recebido ponto flutuante"
        )


def read_scene(path: Path, cfg: ClassificationConfig) -> Scene:
    with rasterio.open(path) as ds:
        grid = _check_grid(ds)
        _require_bands(ds, cfg)
        dn = ds.read()
        return _scene_from_dn(dn, ds, grid, cfg)


def read_scene_on_grid(path: Path, target: Grid, cfg: ClassificationConfig) -> Scene:
    """Lê uma segunda data e a coloca na grade da cena principal.

    Mesma grade (mesmo tile) => leitura direta, sem reamostragem. Caso
    contrário, reprojeta o DN com bilinear respeitando NoData (interpolação
    linear em DN equivale a interpolar reflectância, pois a conversão é afim).
    """
    with rasterio.open(path) as ds:
        grid = _check_grid(ds)
        _require_bands(ds, cfg)
        if grid.same_as(target):
            dn = ds.read()
        else:
            nodata = cfg.radiometry.nodata_dn
            dn = np.full((ds.count, target.height, target.width), nodata, dtype=ds.dtypes[0])
            for b in range(ds.count):
                reproject(
                    source=rasterio.band(ds, b + 1),
                    destination=dn[b],
                    src_nodata=nodata,
                    dst_nodata=nodata,
                    dst_transform=target.transform,
                    dst_crs=target.crs,
                    resampling=Resampling.bilinear,
                )
        return _scene_from_dn(dn, ds, target, cfg)


def read_scl_on_grid(path: Path, target: Grid) -> npt.NDArray[np.uint8]:
    """SCL é categórica: reamostragem SEMPRE nearest e nenhuma conversão radiométrica."""
    with rasterio.open(path) as ds:
        if ds.crs is None:
            raise SceneError("a SCL não tem CRS")
        if ds.count != 1 or not np.issubdtype(np.dtype(ds.dtypes[0]), np.integer):
            raise SceneError("a SCL precisa ter 1 banda inteira")
        out = np.zeros((target.height, target.width), dtype=np.uint8)
        reproject(
            source=rasterio.band(ds, 1),
            destination=out,
            src_nodata=0,
            dst_nodata=0,
            dst_transform=target.transform,
            dst_crs=target.crs,
            resampling=Resampling.nearest,
        )
        return out
