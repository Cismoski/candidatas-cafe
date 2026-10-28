"""Branches de validação e casos de borda."""

import numpy as np
import pytest
import rasterio
from pydantic import ValidationError
from rasterio.transform import Affine

from app.processing.classify import LandClass, classify
from app.processing.config import ClassificationConfig
from app.processing.pipeline import run_analysis
from app.processing.reading import SceneError, read_scene, read_scl_on_grid
from app.processing.render import true_color
from tests.conftest import COFFEE, CRS, make_scene, paint, write_stack


@pytest.mark.parametrize(
    ("section", "patch", "msg"),
    [
        ("bands", {"nir": 3}, "distintos"),
        ("indices", {"texture_window": 4}, "ímpar"),
        ("rules", {"dense_ndvi_default": 0.9}, "dense_ndvi_floor <="),
        ("rules", {"ndvi_min": 0.7}, "ndvi_min"),
        ("morphology", {"min_area_ha": -1}, "greater than or equal"),
    ],
)
def test_config_validation(cfg, section, patch, msg):
    data = cfg.model_dump()
    data[section].update(patch)
    with pytest.raises(ValidationError, match=msg):
        ClassificationConfig.model_validate(data)


def test_rotated_raster_rejected(tmp_path, cfg):
    p = tmp_path / "rot.tif"
    with rasterio.open(
        p,
        "w",
        driver="GTiff",
        dtype="uint16",
        count=4,
        height=4,
        width=4,
        crs=CRS,
        transform=Affine(10, 1, 323200, 0, -10, 7642980),
    ) as ds:
        ds.write(make_scene(4, 4))
    with pytest.raises(SceneError, match="rotacionado"):
        read_scene(p, cfg)


def _write_scl(path, data, crs=CRS):
    kw = {"crs": crs} if crs else {}
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        dtype=data.dtype,
        count=data.shape[0],
        height=data.shape[1],
        width=data.shape[2],
        transform=Affine(20, 0, 323200, 0, -20, 7642980),
        **kw,
    ) as ds:
        ds.write(data)
    return path


@pytest.mark.parametrize(
    ("data", "crs", "msg"),
    [
        (np.full((1, 2, 2), 4, np.uint8), None, "CRS"),
        (np.full((2, 2, 2), 4, np.uint8), CRS, "1 banda"),
        (np.full((1, 2, 2), 4, np.float32), CRS, "1 banda inteira"),
    ],
)
def test_invalid_scl_rejected(tmp_path, cfg, data, crs, msg):
    grid = read_scene(write_stack(tmp_path / "s.tif", make_scene(4, 4)), cfg).grid
    with pytest.raises(SceneError, match=msg):
        read_scl_on_grid(_write_scl(tmp_path / "scl.tif", data, crs), grid)


def test_all_nodata_scene_renders_black_and_has_no_candidates(tmp_path, cfg):
    p = write_stack(tmp_path / "z.tif", np.zeros((4, 20, 20), np.uint16))
    scene = read_scene(p, cfg)
    assert not true_color(scene).any()
    s = run_analysis(p, tmp_path / "o", cfg)
    assert s["results"]["analysed_area_ha"] == 0
    assert s["results"]["candidate_fraction_of_analysed"] == 0


def test_acquisition_override_only_when_tag_missing(tmp_path, cfg):
    dn = make_scene(30, 30)
    p = write_stack(tmp_path / "n.tif", dn)
    s = run_analysis(p, tmp_path / "o", cfg, acquired_utc_override="2026-01-10T13:00:00Z")
    assert s["inputs"]["primary"]["acquired_utc"] == "2026-01-10T13:00:00Z"
    assert s["attribution"].endswith("(2026)")
    p2 = write_stack(tmp_path / "t.tif", dn, tags={"ACQUISITION_UTC": "2025-08-16T00:00:00Z"})
    s2 = run_analysis(p2, tmp_path / "o2", cfg, acquired_utc_override="2026-01-10T13:00:00Z")
    assert s2["inputs"]["primary"]["acquired_utc"].startswith("2025-08-16")


def test_morphology_can_be_disabled(cfg_copy):
    cfg_copy.morphology.opening_iterations = 0
    cfg_copy.morphology.closing_iterations = 0
    cfg_copy.rules.dense_buffer_px = 0
    ndvi = np.full((20, 20), 0.3, np.float32)
    ndvi[2:12, 2:8] = 0.58
    ndvi[2, 2] = 0.3  # sem abertura/fechamento o pixel faltante continua faltando
    res = classify(
        ndvi=ndvi,
        ndwi=np.full_like(ndvi, -0.5),
        valid=np.ones(ndvi.shape, bool),
        quality_ok=None,
        other_ndvi=None,
        pixel_area_m2=100.0,
        cfg=cfg_copy,
    )
    assert (res.classes == LandClass.CANDIDATE).sum() == 59
    assert res.classes[2, 2] == LandClass.LOW_VEGETATION


def test_multipolygon_component_is_one_feature(tmp_path, cfg):
    """Dois blocos ligados só pela diagonal: 1 componente (8-conexo), 1 feature."""
    dn = make_scene(40, 40)
    paint(dn, slice(5, 15), slice(5, 15), **COFFEE)
    paint(dn, slice(15, 25), slice(15, 25), **COFFEE)
    s = run_analysis(write_stack(tmp_path / "d.tif", dn), tmp_path / "o", cfg)
    assert s["results"]["candidate_polygons"] == 1
    assert s["results"]["candidate_area_ha"] == pytest.approx(2.0)
