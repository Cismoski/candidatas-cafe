"""Fábrica de rasters sintéticos com valores conhecidos (EPSG:32723, 10 m)."""

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from app.processing.config import ClassificationConfig, load_config

ORIGIN = (323200.0, 7642980.0)  # mesmo canto do kit
CRS = "EPSG:32723"
SCALE, OFFSET = 0.0001, -0.1


def refl_to_dn(r: float) -> int:
    """Inverso da conversão S2 L2A: DN = (refl - offset) / scale."""
    return round((r - OFFSET) / SCALE)


def write_stack(
    path: Path,
    dn: np.ndarray,
    *,
    crs: str | None = CRS,
    res: float = 10.0,
    origin: tuple[float, float] = ORIGIN,
    scale_offset: bool = True,
    tags: dict | None = None,
) -> Path:
    """Grava um GeoTIFF (bands, h, w) com scale/offset nas bandas, como o kit."""
    count, h, w = dn.shape
    profile = {
        "driver": "GTiff",
        "dtype": dn.dtype,
        "count": count,
        "height": h,
        "width": w,
        "transform": from_origin(*origin, res, res),
        "nodata": 0,
    }
    if crs:
        profile["crs"] = crs
    with rasterio.open(path, "w", **profile) as ds:
        ds.write(dn)
        if scale_offset:
            ds.scales = (SCALE,) * count
            ds.offsets = (OFFSET,) * count
        if tags:
            ds.update_tags(**tags)
    return path


def make_scene(h: int, w: int, blue=0.04, green=0.06, red=0.15, nir=0.25) -> np.ndarray:
    """Cena uniforme em DN uint16 (padrão: vegetação rala, NDVI = 0.25)."""
    dn = np.empty((4, h, w), dtype=np.uint16)
    for i, r in enumerate((blue, green, red, nir)):
        dn[i] = refl_to_dn(r)
    return dn


def paint(dn: np.ndarray, rows: slice, cols: slice, **refl: float) -> None:
    order = {"blue": 0, "green": 1, "red": 2, "nir": 3}
    for name, r in refl.items():
        dn[order[name], rows, cols] = refl_to_dn(r)


# Reflectâncias de referência e seus NDVI:
COFFEE = {"red": 0.08, "nir": 0.30}  # NDVI = 0.22/0.38 = 0.5789
FOREST = {"red": 0.03, "nir": 0.40}  # NDVI = 0.37/0.43 = 0.8605
WATER = {"green": 0.08, "nir": 0.02, "red": 0.03}  # NDWI = 0.6


@pytest.fixture(scope="session")
def cfg() -> ClassificationConfig:
    return load_config()


@pytest.fixture
def cfg_copy(cfg: ClassificationConfig) -> ClassificationConfig:
    return cfg.model_copy(deep=True)
