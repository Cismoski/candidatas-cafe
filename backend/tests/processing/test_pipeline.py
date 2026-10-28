"""Testes ponta a ponta com GeoTIFFs sintéticos gravados em disco."""

import json

import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin
from shapely.geometry import shape

from app.processing.classify import LandClass
from app.processing.pipeline import run_analysis
from app.processing.reading import SceneError, read_scene, read_scene_on_grid, read_scl_on_grid
from tests.conftest import COFFEE, FOREST, ORIGIN, WATER, make_scene, paint, write_stack


@pytest.fixture
def synthetic(tmp_path):
    """60x60 px: fundo de vegetação rala, mata 30x15 à esquerda, talhão 10x10 isolado."""
    dn = make_scene(60, 60)
    paint(dn, slice(0, 30), slice(0, 15), **FOREST)  # 4,5 ha
    paint(dn, slice(40, 50), slice(40, 50), **COFFEE)  # 1,0 ha exato
    paint(dn, slice(5, 12), slice(45, 55), **WATER)
    dn[:, 55:, 0:5] = 0  # canto NoData
    tags = {"ACQUISITION_UTC": "2025-08-16T13:28:10Z", "SOURCE_ITEM": "SINTETICO"}
    return write_stack(tmp_path / "scene.tif", dn, tags=tags)


# --- leitura / radiometria --------------------------------------------------------
def test_reflectance_applied_exactly_once(synthetic, cfg):
    scene = read_scene(synthetic, cfg)
    assert scene.radiometry_source == "metadados do GeoTIFF"
    assert scene.nir[45, 45] == pytest.approx(0.30, abs=1e-6)  # não 0.30*1e-4-0.1
    assert scene.red[45, 45] == pytest.approx(0.08, abs=1e-6)


def test_defaults_used_without_scale_tags(tmp_path, cfg):
    p = write_stack(tmp_path / "a.tif", make_scene(4, 4), scale_offset=False)
    scene = read_scene(p, cfg)
    assert "padrão" in scene.radiometry_source
    assert scene.nir[0, 0] == pytest.approx(0.25, abs=1e-6)


def test_nodata_excluded_from_valid(synthetic, cfg):
    scene = read_scene(synthetic, cfg)
    assert not scene.valid[55:, 0:5].any()
    assert np.isnan(scene.nir[57, 2])
    assert scene.valid.sum() == 60 * 60 - 25


@pytest.mark.parametrize(
    ("kwargs", "dn", "msg"),
    [
        ({"crs": "EPSG:4326", "res": 0.0001, "origin": (-46.7, -21.3)}, None, "não é UTM"),
        ({"crs": None}, None, "CRS"),
        ({}, make_scene(4, 4)[:3], "4 bandas"),
        ({}, make_scene(4, 4).astype(np.float32), "inteiro"),
    ],
)
def test_invalid_rasters_rejected(tmp_path, cfg, kwargs, dn, msg):
    p = write_stack(tmp_path / "bad.tif", make_scene(4, 4) if dn is None else dn, **kwargs)
    with pytest.raises(SceneError, match=msg):
        read_scene(p, cfg)


def test_scl_is_resampled_with_nearest(tmp_path, synthetic, cfg):
    grid = read_scene(synthetic, cfg).grid
    scl = np.array([[4, 5], [2, 9]], dtype=np.uint8).repeat(15, 0).repeat(15, 1)  # 30x30 a 20 m
    with rasterio.open(
        tmp_path / "scl.tif",
        "w",
        driver="GTiff",
        dtype="uint8",
        count=1,
        height=30,
        width=30,
        crs="EPSG:32723",
        transform=from_origin(*ORIGIN, 20, 20),
        nodata=0,
    ) as ds:
        ds.write(scl, 1)
    out = read_scl_on_grid(tmp_path / "scl.tif", grid)
    assert out.shape == (60, 60)
    assert set(np.unique(out)) == {2, 4, 5, 9}  # nenhuma classe "interpolada" (ex.: 3, 6, 7)
    assert out[0, 0] == 4 and out[59, 59] == 9 and out[0, 59] == 5


def test_second_scene_on_same_grid_is_read_directly(tmp_path, synthetic, cfg):
    grid = read_scene(synthetic, cfg).grid
    other = read_scene_on_grid(synthetic, grid, cfg)
    assert other.nir[45, 45] == pytest.approx(0.30, abs=1e-6)


def test_second_scene_on_other_grid_is_reprojected(tmp_path, synthetic, cfg):
    grid = read_scene(synthetic, cfg).grid
    # mesma área, origem deslocada 1 pixel e cobertura maior
    p = write_stack(
        tmp_path / "b.tif",
        make_scene(70, 70, nir=0.3, red=0.1),
        origin=(ORIGIN[0] - 10, ORIGIN[1] + 10),
    )
    other = read_scene_on_grid(p, grid, cfg)
    assert other.nir.shape == (60, 60)
    assert np.nanmean(other.nir) == pytest.approx(0.3, abs=1e-4)


# --- pipeline completo ---------------------------------------------------------
def test_pipeline_end_to_end(tmp_path, synthetic, cfg):
    out = tmp_path / "out"
    s = run_analysis(synthetic, out, cfg)
    r = s["results"]

    assert r["candidate_polygons"] == 1
    assert r["candidate_area_ha"] == pytest.approx(1.0, abs=1e-9)  # 100 px * 100 m²
    assert r["analysed_area_ha"] == pytest.approx((3600 - 25) * 0.01)
    assert r["class_areas"]["water"]["area_ha"] == pytest.approx(0.7)
    assert r["class_areas"]["dense_canopy"]["area_ha"] == pytest.approx(4.5)
    assert s["method"]["mode"] == "single_date"
    assert s["inputs"]["primary"]["acquired_utc"].startswith("2025-08-16")
    assert s["attribution"] == "Contains modified Copernicus Sentinel data (2025)"
    p = r["polygons"][0]
    assert p["ndvi_mean"] == pytest.approx(0.5789, abs=1e-3)

    for f in (
        "summary.json",
        "candidatas.geojson",
        "classes.tif",
        "classificacao.png",
        "overlay_rgb.png",
        "overlay_classes.png",
    ):
        assert (out / f).stat().st_size > 0
    assert json.loads((out / "summary.json").read_text()) == s


def test_geojson_is_wgs84_and_matches_projected_area(tmp_path, synthetic, cfg):
    run_analysis(synthetic, tmp_path / "o", cfg)
    fc = json.loads((tmp_path / "o" / "candidatas.geojson").read_text())
    assert "crs" not in fc  # RFC 7946: sem membro crs, sempre WGS84
    feat = fc["features"][0]
    geom = shape(feat["geometry"])
    lon, lat = geom.centroid.x, geom.centroid.y
    assert -46.71 < lon < -46.65 and -21.36 < lat < -21.30  # Guaxupé, não metros
    # o anel externo é anti-horário (RFC 7946 §3.1.6)
    assert geom.exterior.is_ccw
    # reprojetar de volta para UTM recupera ~1 ha (a área oficial vem do CRS métrico)
    to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32723", always_xy=True)
    xs, ys = to_utm.transform(*geom.exterior.xy)
    from shapely.geometry import Polygon

    assert Polygon(zip(xs, ys, strict=True)).area / 10_000 == pytest.approx(1.0, rel=0.01)
    assert feat["properties"]["area_ha"] == pytest.approx(1.0)


def test_classes_geotiff_preserves_grid(tmp_path, synthetic, cfg):
    run_analysis(synthetic, tmp_path / "o", cfg)
    with rasterio.open(tmp_path / "o" / "classes.tif") as ds, rasterio.open(synthetic) as src:
        assert ds.crs == src.crs and ds.transform == src.transform
        cls = ds.read(1)
        assert ds.tags()["ATTRIBUTION"].startswith("Contains modified Copernicus")
    assert (cls == LandClass.CANDIDATE).sum() == 100
    assert (cls[55:, 0:5] == LandClass.NODATA).all()


def test_map_overlay_corners_are_lonlat(tmp_path, synthetic, cfg):
    s = run_analysis(synthetic, tmp_path / "o", cfg)
    corners = s["map"]["coordinates"]
    assert len(corners) == 4
    tl, tr, br, bl = corners
    assert tl[0] < tr[0] and bl[1] < tl[1]  # TL, TR, BR, BL
    assert all(-47 < x < -46 and -22 < y < -21 for x, y in corners)


def test_pipeline_temporal_mode_and_scl(tmp_path, synthetic, cfg):
    scl = np.full((30, 30), 4, dtype=np.uint8)
    with rasterio.open(
        tmp_path / "scl.tif",
        "w",
        driver="GTiff",
        dtype="uint8",
        count=1,
        height=30,
        width=30,
        crs="EPSG:32723",
        transform=from_origin(*ORIGIN, 20, 20),
        nodata=0,
    ) as ds:
        ds.write(scl, 1)
    # segunda data: o talhão vira solo (cultura anual colhida) -> deve sair
    dn2 = make_scene(60, 60)
    p2 = write_stack(tmp_path / "wet.tif", dn2)
    s = run_analysis(
        synthetic, tmp_path / "o", cfg, scl_path=tmp_path / "scl.tif", secondary_path=p2
    )
    assert s["method"]["mode"] == "two_dates"
    assert s["inputs"]["scl_used"] is True
    assert s["results"]["candidate_polygons"] == 0
    assert s["results"]["polygons"] == []
    assert not any("segunda data" in lim for lim in s["limitations"])


def test_pipeline_no_candidates_still_writes_products(tmp_path, cfg):
    p = write_stack(tmp_path / "bare.tif", make_scene(30, 30))
    s = run_analysis(p, tmp_path / "o", cfg)
    assert s["results"]["candidate_polygons"] == 0
    assert s["results"]["index_stats"]["ndvi"]["candidates"] is None
    fc = json.loads((tmp_path / "o" / "candidatas.geojson").read_text())
    assert fc == {"type": "FeatureCollection", "features": []}


# --- itens da revisão da fase 1 -------------------------------------------------
def test_geometries_valid_with_diagonal_touching_blocks(tmp_path, cfg):
    """Com connectivity=8 na vetorização, blocos que se tocam na quina geravam anel inválido."""
    dn = make_scene(50, 50)
    paint(dn, slice(5, 15), slice(5, 15), **COFFEE)
    paint(dn, slice(15, 25), slice(15, 25), **COFFEE)
    paint(dn, slice(25, 35), slice(5, 15), **COFFEE)  # toca o segundo bloco pela quina
    s = run_analysis(write_stack(tmp_path / "d.tif", dn), tmp_path / "o", cfg)
    fc = json.loads((tmp_path / "o" / "candidatas.geojson").read_text())
    assert s["results"]["candidate_polygons"] == 1
    assert all(shape(f["geometry"]).is_valid for f in fc["features"])
    for p in s["results"]["polygons"]:  # ponto representativo dentro do polígono
        geom = shape(fc["features"][0]["geometry"])
        from shapely.geometry import Point

        assert geom.buffer(1e-9).contains(Point(p["point_lon"], p["point_lat"]))


def test_overlay_corners_match_transformed_bounds(tmp_path, synthetic, cfg):
    s = run_analysis(synthetic, tmp_path / "o", cfg)
    to_ll = Transformer.from_crs("EPSG:32723", "EPSG:4326", always_xy=True)
    left, top = ORIGIN
    right, bottom = left + 600, top - 600
    expected = [  # TL, TR, BR, BL
        to_ll.transform(left, top),
        to_ll.transform(right, top),
        to_ll.transform(right, bottom),
        to_ll.transform(left, bottom),
    ]
    for got, exp in zip(s["map"]["coordinates"], expected, strict=True):
        # a grade em 3857 envolve a da UTM: tolerância de ~1 pixel
        assert got == pytest.approx(exp, abs=1.5e-4)


def test_secondary_without_overlap_is_rejected(tmp_path, synthetic, cfg):
    far = write_stack(tmp_path / "far.tif", make_scene(60, 60), origin=(400000.0, 7600000.0))
    with pytest.raises(SceneError, match="segunda data"):
        run_analysis(synthetic, tmp_path / "o", cfg, secondary_path=far)


def test_scl_without_overlap_is_rejected(tmp_path, synthetic, cfg):
    with rasterio.open(
        tmp_path / "scl.tif",
        "w",
        driver="GTiff",
        dtype="uint8",
        count=1,
        height=10,
        width=10,
        crs="EPSG:32723",
        transform=from_origin(400000.0, 7600000.0, 20, 20),
        nodata=0,
    ) as ds:
        ds.write(np.full((1, 10, 10), 4, np.uint8))
    with pytest.raises(SceneError, match="SCL"):
        run_analysis(synthetic, tmp_path / "o", cfg, scl_path=tmp_path / "scl.tif")


def test_cloud_in_secondary_is_nodata_not_rejection(tmp_path, synthetic, cfg):
    """Nuvem na 2ª data (azul alto, NDVI baixo) não pode apagar o candidato."""
    dn2 = make_scene(60, 60)
    paint(dn2, slice(0, 60), slice(0, 60), **COFFEE)
    paint(dn2, slice(40, 50), slice(40, 50), blue=0.35, green=0.35, red=0.35, nir=0.38)
    s = run_analysis(
        synthetic, tmp_path / "o", cfg, secondary_path=write_stack(tmp_path / "w.tif", dn2)
    )
    assert s["results"]["candidate_polygons"] == 1
    assert s["results"]["temporal_unverified_ha"] == pytest.approx(1.0)
    assert s["results"]["temporal_rejected_ha"] == 0


def test_rerun_into_same_dir_overwrites_consistently(tmp_path, synthetic, cfg):
    out = tmp_path / "o"
    first = run_analysis(synthetic, out, cfg)
    second = run_analysis(write_stack(tmp_path / "bare.tif", make_scene(60, 60)), out, cfg)
    assert first["results"]["candidate_polygons"] == 1
    assert second["results"]["candidate_polygons"] == 0
    assert json.loads((out / "candidatas.geojson").read_text())["features"] == []


def test_masked_pixels_are_not_counted_as_analysed(tmp_path, synthetic, cfg):
    scl = np.full((30, 30), 4, np.uint8)
    scl[:15, :] = 9  # metade norte: nuvem
    with rasterio.open(
        tmp_path / "scl.tif",
        "w",
        driver="GTiff",
        dtype="uint8",
        count=1,
        height=30,
        width=30,
        crs="EPSG:32723",
        transform=from_origin(*ORIGIN, 20, 20),
        nodata=0,
    ) as ds:
        ds.write(scl, 1)
    s = run_analysis(synthetic, tmp_path / "o", cfg, scl_path=tmp_path / "scl.tif")
    r = s["results"]
    assert r["class_areas"]["masked_quality"]["area_ha"] == pytest.approx(18.0)
    assert r["analysed_area_ha"] == pytest.approx((3600 - 25) * 0.01 - 18.0)
    assert r["input_coverage"]["scl"] == 1.0
