"""Comparação com o MapBiomas sem rede: rasters de referência sintéticos locais."""

import json

import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin

from app.processing.classify import LandClass
from app.processing.pipeline import run_analysis
from app.processing.reference import COFFEE, compare, mapbiomas_reference, reference_year
from tests.conftest import COFFEE as COFFEE_REFL
from tests.conftest import CRS, ORIGIN, make_scene, paint, write_stack

PASTURE = 15


def write_mb(path, data, *, crs=CRS, transform=None):
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=data.shape[1],
        height=data.shape[0],
        count=1,
        dtype="uint8",
        crs=crs,
        transform=transform or from_origin(*ORIGIN, 30, 30),
        nodata=0,
    ) as d:
        d.write(data, 1)
    return path


@pytest.fixture
def scene(tmp_path):
    """60x60 px de vegetação rala com um talhão candidato de 10x10 (1 ha) em [40:50, 40:50]."""
    dn = make_scene(60, 60)
    paint(dn, slice(40, 50), slice(40, 50), **COFFEE_REFL)
    tags = {"ACQUISITION_UTC": "2025-08-16T13:28:10Z", "SOURCE_ITEM": "SINTETICO"}
    return write_stack(tmp_path / "scene.tif", dn, tags=tags)


def mb_with_coffee(tmp_path, name="mb_2025.tif"):
    """Pastagem com café em 4x4 px de 30 m = [39:51, 39:51] a 10 m (1,44 ha, contém o talhão)."""
    mb = np.full((20, 20), PASTURE, np.uint8)
    mb[13:17, 13:17] = COFFEE
    return write_mb(tmp_path / name, mb)


# --- métricas -------------------------------------------------------------------
def test_compare_metrics_by_hand():
    classes = np.full((4, 4), LandClass.LOW_VEGETATION, np.uint8)
    classes[0, :2] = LandClass.CANDIDATE  # 2 px candidatos
    mb = np.full((4, 4), PASTURE, np.uint8)
    mb[0, 1:4] = COFFEE  # 3 px de café, 1 em comum
    r = compare(mb, classes, pixel_ha=0.01)
    assert r["iou"] == 0.25  # 1 / (2 + 3 - 1)
    assert r["candidates_on_reference_coffee"] == 0.5
    assert r["reference_coffee_in_candidates"] == pytest.approx(1 / 3, abs=1e-4)
    assert r["candidates_by_reference_class"] == {"Café": 0.5, "Pastagem": 0.5}
    assert r["reference_coffee_ha"] == 0.03 and r["compared_area_ha"] == 0.16


def test_compare_excludes_nodata_and_masked_and_handles_empty():
    classes = np.full((2, 2), LandClass.NODATA, np.uint8)
    classes[0, 0] = LandClass.MASKED_QUALITY
    r = compare(np.full((2, 2), COFFEE, np.uint8), classes, pixel_ha=0.01)
    assert r["compared_area_ha"] == 0 and r["reference_coffee_ha"] == 0
    assert r["iou"] is None and r["candidates_on_reference_coffee"] is None
    assert r["candidates_by_reference_class"] == {}


@pytest.mark.parametrize(
    ("acquired", "year"),
    [
        ("2024-08-16T13:28:10Z", 2024),
        ("2025-02-17T00:00:00Z", 2025),
        ("2026-07-01T00:00:00Z", 2025),  # depois do último ano publicado
        ("1984-12-31T00:00:00Z", 1985),
        (None, 2025),
        ("abcd", 2025),
    ],
)
def test_reference_year_bva(acquired, year):
    assert reference_year(acquired) == year


# --- leitura ------------------------------------------------------------------------
def test_pipeline_compares_with_reference_and_writes_overlay(tmp_path, scene, cfg):
    mb_with_coffee(tmp_path)
    s = run_analysis(scene, tmp_path / "o", cfg, reference_url=str(tmp_path / "mb_{year}.tif"))
    ref = s["reference"]
    assert ref["status"] == "ok" and ref["year"] == 2025 and ref["license"] == "CC BY 4.0"
    assert ref["reference_coffee_ha"] == 1.44 and ref["candidate_ha"] == 1.0
    assert ref["iou"] == pytest.approx(100 / 144, abs=1e-4)
    assert ref["candidates_on_reference_coffee"] == 1.0
    assert ref["reference_coffee_by_our_class"]["Candidata a café"] == pytest.approx(
        100 / 144, abs=1e-4
    )
    assert "não acurácia" in ref["note"]
    assert s["map"]["reference_overlay"] is True
    assert (tmp_path / "o" / "overlay_referencia.png").is_file()
    json.dumps(s)


def test_reference_in_geographic_crs_is_reprojected(tmp_path, scene, cfg):
    """O MapBiomas real está em EPSG:4326 a ~30 m."""
    to_ll = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)
    west, north = to_ll.transform(ORIGIN[0] - 300, ORIGIN[1] + 300)
    res = 0.00026949458523585647
    write_mb(
        tmp_path / "mb_2025.tif",
        np.full((40, 40), COFFEE, np.uint8),
        crs="EPSG:4326",
        transform=from_origin(west, north, res, res),
    )
    ref = run_analysis(scene, tmp_path / "o", cfg, reference_url=str(tmp_path / "mb_{year}.tif"))[
        "reference"
    ]
    assert ref["status"] == "ok"
    assert ref["reference_coffee_ha"] == ref["compared_area_ha"] == 36.0  # cobre tudo
    assert ref["candidates_on_reference_coffee"] == 1.0


def test_unreadable_reference_does_not_fail_the_analysis(tmp_path, scene, cfg):
    s = run_analysis(
        scene, tmp_path / "o", cfg, reference_url=str(tmp_path / "nao_existe_{year}.tif")
    )
    assert s["reference"]["status"] == "unavailable"
    assert s["results"]["candidate_polygons"] == 1  # a análise seguiu
    assert s["map"]["reference_overlay"] is False
    assert not (tmp_path / "o" / "overlay_referencia.png").exists()


def test_area_outside_reference_coverage(tmp_path, scene, cfg):
    write_mb(tmp_path / "mb_2025.tif", np.zeros((20, 20), np.uint8))
    s = run_analysis(scene, tmp_path / "o", cfg, reference_url=str(tmp_path / "mb_{year}.tif"))
    assert s["reference"]["status"] == "no_coverage"


def test_without_reference_url_there_is_no_comparison(tmp_path, scene, cfg):
    s = run_analysis(scene, tmp_path / "o", cfg)
    assert s["reference"] is None and s["map"]["reference_overlay"] is False


def test_year_follows_image_date(tmp_path, cfg):
    """Imagem de 2024 compara com o mapa de 2024 (aqui ausente: indisponível, não o de 2025)."""
    dn = make_scene(60, 60)
    p = write_stack(tmp_path / "s.tif", dn, tags={"ACQUISITION_UTC": "2024-08-16T00:00:00Z"})
    mb_with_coffee(tmp_path)  # só 2025
    s = run_analysis(p, tmp_path / "o", cfg, reference_url=str(tmp_path / "mb_{year}.tif"))
    assert s["reference"]["year"] == 2024 and s["reference"]["status"] == "unavailable"


def test_mask_returned_matches_coffee(tmp_path, scene, cfg):
    from app.processing.reading import read_scene

    mb_with_coffee(tmp_path)
    grid = read_scene(scene, cfg).grid
    classes = np.full((60, 60), LandClass.LOW_VEGETATION, np.uint8)
    _, mask = mapbiomas_reference(str(tmp_path / "mb_{year}.tif"), grid, classes, "2025-01-01")
    assert mask.sum() == 144 and mask[39:51, 39:51].all()
