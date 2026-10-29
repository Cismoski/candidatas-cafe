"""Contrato do summary.json: é o que o frontend e o chat consomem.

A mutação mostrou que trocar o nome de uma chave, um arredondamento ou a
fração candidata/analisada não quebrava nenhum teste. Aqui a estrutura fica
fixada num arquivo de referência e as estatísticas são recalculadas de forma
independente a partir dos rasters gravados.
"""

import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from PIL import Image
from shapely.geometry import Point, shape

from app.processing.classify import LandClass
from app.processing.pipeline import run_analysis
from app.processing.reading import read_scene
from app.processing.render import CLASS_COLORS
from tests.conftest import COFFEE, FOREST, WATER, make_scene, paint, write_stack

CONTRACT = Path(__file__).with_name("summary_contract.json")
VOLATILE = {"generated_utc"}


def key_paths(value, prefix="") -> set[str]:
    """Caminhos de chave; listas viram [] e dicts indexados por id viram {id}."""
    out: set[str] = set()
    if isinstance(value, dict):
        for k, v in value.items():
            name = "{id}" if k.isdigit() else k
            path = f"{prefix}.{name}" if prefix else name
            out.add(path)
            out |= key_paths(v, path)
    elif isinstance(value, list):
        for item in value:
            out |= key_paths(item, f"{prefix}[]")
    return out


@pytest.fixture
def summary(tmp_path, cfg):
    dn = make_scene(60, 60)
    paint(dn, slice(0, 30), slice(0, 15), **FOREST)
    paint(dn, slice(40, 50), slice(40, 50), **COFFEE)
    paint(dn, slice(5, 12), slice(45, 55), **WATER)
    # NIR variando dentro do fundo: percentis distintos entre si
    dn[3, 30:60, 20:40] += np.arange(20, dtype=np.uint16) * 40
    dn[:, 55:, 0:5] = 0
    tags = {"ACQUISITION_UTC": "2025-08-16T13:28:10Z", "SOURCE_ITEM": "SINTETICO"}
    path = write_stack(tmp_path / "s.tif", dn, tags=tags)
    out = tmp_path / "o"
    return run_analysis(path, out, cfg), out, path


def test_key_structure_matches_contract(summary):
    s, _, _ = summary
    expected = set(json.loads(CONTRACT.read_text("utf-8")))
    got = key_paths(s)
    assert got - expected == set(), "chave nova: atualize o contrato e quem consome"
    assert expected - got == set(), "chave sumiu ou foi renomeada"


def test_file_on_disk_is_the_returned_summary(summary):
    s, out, _ = summary
    text = (out / "summary.json").read_text("utf-8")
    assert json.loads(text) == s
    assert text.splitlines()[1].startswith('  "schema_version"')  # indent 2, legível
    assert s["schema_version"] == 2


def test_results_are_consistent_with_each_other(summary):
    r = summary[0]["results"]
    assert r["candidate_fraction_of_analysed"] == round(
        r["candidate_area_ha"] / r["analysed_area_ha"], 4
    )
    assert r["candidate_area_ha"] == r["class_areas"]["candidate"]["area_ha"]
    assert r["candidate_area_ha"] == pytest.approx(
        sum(p["area_ha"] for p in r["polygons"]), abs=0.01
    )


def test_index_stats_recomputed_independently(summary, cfg):
    s, out, path = summary
    scene = read_scene(path, cfg)
    with rasterio.open(out / "classes.tif") as src:
        classes = src.read(1)
    ndvi = (scene.nir - scene.red) / (scene.nir + scene.red)
    land = np.isin(
        classes,
        [
            LandClass.LOW_VEGETATION,
            LandClass.DENSE_CANOPY,
            LandClass.DISCARDED,
            LandClass.CANDIDATE,
        ],
    )
    v = ndvi[land]
    p = np.percentile(v, [5, 25, 50, 75, 95])
    got = s["results"]["index_stats"]["ndvi"]["analysed_land"]
    assert got["n_pixels"] == v.size
    assert got["mean"] == pytest.approx(float(v.mean()), abs=1e-4)
    for key, q in zip(["p05", "p25", "median", "p75", "p95"], p, strict=True):
        assert got[key] == pytest.approx(float(q), abs=1e-4)
    cand = s["results"]["index_stats"]["ndvi"]["candidates"]
    assert cand["n_pixels"] == int((classes == LandClass.CANDIDATE).sum()) == 100
    assert cand["mean"] == pytest.approx(0.22 / 0.38, abs=1e-4)
    assert set(s["results"]["index_stats"]) == {"ndvi", "ndwi", "savi", "texture"}


def test_polygon_attributes(summary):
    s, out, _ = summary
    (poly,) = s["results"]["polygons"]
    assert poly["ndvi_mean"] == pytest.approx(0.22 / 0.38, abs=1e-4)
    for k in ("point_lon", "point_lat"):
        assert poly[k] == round(poly[k], 6)
    gj = json.loads((out / "candidatas.geojson").read_text("utf-8"))
    (feat,) = gj["features"]
    assert feat["properties"]["classe"] == "candidata_cafe"
    pt = Point(feat["properties"]["point_lon"], feat["properties"]["point_lat"])
    assert shape(feat["geometry"]).buffer(1e-6).contains(pt)


def test_method_block(summary):
    m = summary[0]["method"]
    assert m["mode"] == "single_date"
    assert m["otsu_separability"] == round(m["otsu_separability"], 3)
    assert 0 < m["otsu_separability"] <= 1
    assert m["parameters"]["rules"]["ndvi_min"] == 0.45


def test_scene_info(summary):
    info = summary[0]["inputs"]["primary"]
    assert info == {
        "acquired_utc": "2025-08-16T13:28:10Z",
        "source_item": "SINTETICO",
        "crs": "EPSG:32723",
        "width": 60,
        "height": 60,
        "pixel_size_m": [10.0, 10.0],
        "radiometry": "metadados do GeoTIFF",
    }


def test_classes_overlay_is_drawn_from_the_classification(summary):
    _, out, _ = summary
    img = np.asarray(Image.open(out / "overlay_classes.png"))
    colors = {tuple(c) for c in img.reshape(-1, 4)}
    assert tuple(CLASS_COLORS[LandClass.CANDIDATE]) in colors
    assert tuple(CLASS_COLORS[LandClass.DENSE_CANOPY]) in colors
