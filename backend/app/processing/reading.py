"""Leitura de cenas e alinhamento de rasters auxiliares na grade da cena principal."""

import re
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


ISO_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?Z?)?$")
ITEM_ID = re.compile(r"^[A-Za-z0-9_\-]{1,80}$")


def crs_problem(crs: CRS | None) -> str | None:
    """Só UTM é aceito: a área em hectares vem da grade, e em UTM o fator de
    escala é <= 0,04%. Em Web Mercator (também "projetado em metros") a área
    sairia ~15% maior nesta latitude."""
    if crs is None:
        return "o raster não tem sistema de referência (CRS)"
    if not crs.is_projected or crs.to_dict().get("proj") != "utm":
        return f"CRS {crs.to_string()} não é UTM; use a projeção UTM da cena (ex.: EPSG:32723)"
    return None


def grid_problem(transform: Affine) -> str | None:
    if transform.b != 0 or transform.d != 0:
        return "raster rotacionado não é suportado"
    if transform.e >= 0:
        return "raster com orientação sul-acima não é suportado"
    return None


def _check_grid(ds: rasterio.DatasetReader) -> Grid:
    problem = crs_problem(ds.crs) or grid_problem(ds.transform)
    if problem:
        raise SceneError(problem)
    return Grid(ds.crs, ds.transform, ds.height, ds.width)


def _safe_tag(value: str | None, pattern: re.Pattern) -> str | None:
    """Tags do arquivo vão para o summary.json (contexto do LLM): só aceita o formato esperado."""
    return value if value is not None and pattern.fullmatch(value) else None


BAND_ORDER = ("blue", "green", "red", "nir")


def _band_indexes(cfg: ClassificationConfig) -> list[int]:
    return [getattr(cfg.bands, name) for name in BAND_ORDER]


def _scene_from_dn(dn, ds, grid: Grid, cfg: ClassificationConfig) -> Scene:
    """dn: (4, h, w) já na ordem BAND_ORDER (só as bandas usadas são lidas)."""
    scales, offsets, source = resolve_scale_offset(
        ds.scales, ds.offsets, cfg.radiometry.default_scale, cfg.radiometry.default_offset
    )
    # NoData declarado no arquivo tem precedência; senão, o padrão do L2A (0)
    nodata = int(ds.nodata) if ds.nodata is not None else cfg.radiometry.nodata_dn
    bands = {
        name: dn_to_reflectance(dn[i], scales[idx - 1], offsets[idx - 1], nodata)
        for i, (name, idx) in enumerate(zip(BAND_ORDER, _band_indexes(cfg), strict=True))
    }
    valid = np.logical_and.reduce([np.isfinite(b) for b in bands.values()])
    tags = ds.tags()
    return Scene(
        grid=grid,
        valid=valid,
        acquired_utc=_safe_tag(tags.get("ACQUISITION_UTC"), ISO_DATETIME),
        source_item=_safe_tag(tags.get("SOURCE_ITEM"), ITEM_ID),
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
        # Só as 4 bandas usadas: um arquivo com muitas bandas não vira muitos GB
        dn = ds.read(_band_indexes(cfg))
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
        indexes = _band_indexes(cfg)
        if grid.same_as(target):
            dn = ds.read(indexes)
        else:
            nodata = cfg.radiometry.nodata_dn
            dn = np.full((4, target.height, target.width), nodata, dtype=ds.dtypes[0])
            for i, idx in enumerate(indexes):
                reproject(
                    source=rasterio.band(ds, idx),
                    destination=dn[i],
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
