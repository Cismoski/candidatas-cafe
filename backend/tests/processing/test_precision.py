"""Testes de valor exato contra implementações de referência (força bruta).

Escritos a partir dos mutantes sobreviventes do mutmut: cada teste aqui mata
uma classe de mutação que os testes de comportamento não detectavam.
"""

import numpy as np
import pytest
import rasterio
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays
from rasterio.transform import from_origin

from app.processing import indices
from app.processing.classify import LandClass, classify, dense_canopy_threshold, otsu_threshold
from app.processing.pipeline import run_analysis
from app.processing.reading import SceneError, read_scene, read_scene_on_grid, read_scl_on_grid
from tests.conftest import COFFEE, FOREST, ORIGIN, make_scene, paint, refl_to_dn, write_stack


# --- textura vs. força bruta --------------------------------------------------
def brute_local_std(x, w):
    h, wd = x.shape
    r = w // 2
    out = np.full(x.shape, np.nan)
    for i in range(h):
        for j in range(wd):
            if not np.isfinite(x[i, j]):
                continue
            win = x[max(i - r, 0) : i + r + 1, max(j - r, 0) : j + r + 1]
            out[i, j] = np.nanstd(win)
    return out


@settings(max_examples=30, deadline=None)
@given(
    arrays(
        np.float32,
        (9, 9),
        elements=st.one_of(st.just(np.float32(np.nan)), st.floats(0, 1, width=32)),
    ),
    st.sampled_from([3, 5]),
)
def test_local_std_matches_brute_force(x, w):
    np.testing.assert_allclose(
        indices.local_std(x, w), brute_local_std(x, w), atol=2e-3, equal_nan=True
    )


# --- Otsu vs. força bruta -------------------------------------------------------
def brute_otsu(values, lo, hi, bins=256):
    hist, edges = np.histogram(values, bins=bins, range=(lo, hi))
    centers = (edges[:-1] + edges[1:]) / 2
    scores = np.zeros(bins)
    for k in range(bins):
        a, b = hist[: k + 1], hist[k + 1 :]
        if a.sum() == 0 or b.sum() == 0:
            continue
        m_a = (a * centers[: k + 1]).sum() / a.sum()
        m_b = (b * centers[k + 1 :]).sum() / b.sum()
        scores[k] = a.sum() * b.sum() * (m_a - m_b) ** 2
    ties = np.flatnonzero(np.isclose(scores, scores.max(), rtol=1e-9))
    return (edges[ties[0] + 1] + edges[ties[-1] + 1]) / 2


def test_otsu_plateau_takes_midpoint():
    v = np.array([0.5] * 100 + [0.9] * 100, np.float32)
    t, eta = otsu_threshold(v, 0.45, 1.0)
    assert t == pytest.approx(0.7, abs=0.01) and eta == pytest.approx(1.0)


@pytest.mark.parametrize("seed", range(5))
def test_otsu_matches_brute_force(seed):
    rng = np.random.default_rng(seed)
    v = np.concatenate([rng.normal(0.55, 0.05, 3000), rng.uniform(0.7, 0.9, 2000)]).astype(
        np.float32
    )
    v = v[(v >= 0.45) & (v <= 1)]
    assert otsu_threshold(v, 0.45, 1.0)[0] == pytest.approx(brute_otsu(v, 0.45, 1.0))


def test_dense_threshold_ignores_non_vegetated_and_low_pixels(cfg):
    rng = np.random.default_rng(3)
    veg = np.concatenate([rng.normal(0.58, 0.03, 600), rng.normal(0.82, 0.02, 600)]).astype(
        np.float32
    )
    noise = np.full(5000, 0.95, np.float32)  # fora da máscara de vegetação
    low = np.full(5000, 0.10, np.float32)  # abaixo de ndvi_min
    v = np.concatenate([veg, noise, low])
    mask = np.concatenate(
        [np.ones(veg.size, bool), np.zeros(noise.size, bool), np.ones(low.size, bool)]
    )
    t, _, _ = dense_canopy_threshold(v, mask, cfg)
    assert t == pytest.approx(otsu_threshold(veg, cfg.rules.ndvi_min, 1.0)[0])


@pytest.mark.parametrize(("n", "uses_otsu"), [(499, False), (500, True)])
def test_bva_min_pixels_for_otsu(cfg, n, uses_otsu):
    rng = np.random.default_rng(4)
    v = np.concatenate([rng.normal(0.55, 0.01, n // 2), rng.normal(0.85, 0.01, n - n // 2)]).astype(
        np.float32
    )
    _, src, _ = dense_canopy_threshold(v, np.ones(n, bool), cfg)
    assert src.startswith("Otsu") is uses_otsu


# --- buffer: tamanho e vizinhança diagonal --------------------------------------
def _forest_and_field(cfg, buffer_px):
    cfg.rules.dense_buffer_px = buffer_px
    ndvi = np.full((40, 40), 0.3, np.float32)
    ndvi[0:30, 0:10] = 0.86  # núcleo de mata (3 ha)
    ndvi[5:25, 10:30] = 0.58
    return classify(
        ndvi=ndvi,
        ndwi=np.full_like(ndvi, -0.5),
        valid=np.ones(ndvi.shape, bool),
        quality_ok=None,
        other_ndvi=None,
        pixel_area_m2=100.0,
        cfg=cfg,
    )


@pytest.mark.parametrize(("buffer_px", "cols"), [(0, 20), (1, 19), (2, 18)])
def test_buffer_width(cfg_copy, buffer_px, cols):
    res = _forest_and_field(cfg_copy, buffer_px)
    assert (res.classes == LandClass.CANDIDATE).sum() == 20 * cols


def test_buffer_uses_diagonal_neighbourhood(cfg_copy):
    cfg_copy.morphology.opening_iterations = 0
    ndvi = np.full((40, 40), 0.3, np.float32)
    ndvi[0:10, 0:10] = 0.86  # núcleo 1 ha
    ndvi[10:20, 10:20] = 0.58  # toca o núcleo só pela diagonal em (10, 10)
    res = classify(
        ndvi=ndvi,
        ndwi=np.full_like(ndvi, -0.5),
        valid=np.ones(ndvi.shape, bool),
        quality_ok=None,
        other_ndvi=None,
        pixel_area_m2=100.0,
        cfg=cfg_copy,
    )
    assert res.classes[10, 10] == LandClass.DISCARDED
    assert (res.classes == LandClass.CANDIDATE).sum() == 99


@pytest.mark.parametrize("iterations", [1, 2])
def test_opening_iterations_remove_thin_strips(cfg_copy, iterations):
    cfg_copy.morphology.opening_iterations = iterations
    cfg_copy.morphology.min_area_ha = 0
    ndvi = np.full((30, 30), 0.3, np.float32)
    ndvi[5:25, 5:9] = 0.58  # faixa de 4 px: sobrevive a 1 abertura, não a 2 (precisa de 5)
    res = classify(
        ndvi=ndvi,
        ndwi=np.full_like(ndvi, -0.5),
        valid=np.ones(ndvi.shape, bool),
        quality_ok=None,
        other_ndvi=None,
        pixel_area_m2=100.0,
        cfg=cfg_copy,
    )
    assert (res.n_components == 1) is (iterations == 1)


def test_zero_min_area_keeps_single_pixel(cfg_copy):
    cfg_copy.morphology.opening_iterations = 0
    cfg_copy.morphology.min_area_ha = 0
    ndvi = np.full((10, 10), 0.3, np.float32)
    ndvi[5, 5] = 0.58
    res = classify(
        ndvi=ndvi,
        ndwi=np.full_like(ndvi, -0.5),
        valid=np.ones(ndvi.shape, bool),
        quality_ok=None,
        other_ndvi=None,
        pixel_area_m2=100.0,
        cfg=cfg_copy,
    )
    assert res.n_components == 1


# --- temporal: limites e contagem ------------------------------------------------
def test_rejected_pixel_is_not_resurrected_by_morphology(cfg):
    """Revisão: o fechamento recolocava pixels rejeitados pela regra temporal."""
    ndvi = np.full((20, 20), 0.5, np.float32)
    other = np.full_like(ndvi, 0.5)
    other[10, 10] = 0.1  # um pixel que virou solo na outra data
    res = classify(
        ndvi=ndvi,
        ndwi=np.full_like(ndvi, -0.5),
        valid=np.ones(ndvi.shape, bool),
        quality_ok=None,
        other_ndvi=other,
        pixel_area_m2=100.0,
        cfg=cfg,
    )
    assert res.classes[10, 10] == LandClass.DISCARDED
    assert res.temporal_rejected_px == 1


def test_temporal_keeps_buffer_and_counts_only_candidate_gaps(cfg):
    ndvi = np.full((40, 40), 0.3, np.float32)
    ndvi[0:30, 0:10] = 0.86
    ndvi[5:25, 10:30] = 0.58
    other = np.full_like(ndvi, 0.6)
    other[30:, :] = np.nan  # nuvem fora dos candidatos não conta
    other[5:10, 20:30] = np.nan  # nuvem sobre parte do talhão: 50 px
    res = classify(
        ndvi=ndvi,
        ndwi=np.full_like(ndvi, -0.5),
        valid=np.ones(ndvi.shape, bool),
        quality_ok=None,
        other_ndvi=other,
        pixel_area_m2=100.0,
        cfg=cfg,
    )
    assert (res.classes == LandClass.CANDIDATE).sum() == 20 * 19  # buffer mantido
    assert res.temporal_unverified_px == 50


# --- leitura: CRS, bandas e alinhamento exato -------------------------------------
@pytest.mark.parametrize(
    ("crs", "origin"),
    [
        ("EPSG:2263", (1e6, 2e5)),  # projetado em pés
        ("EPSG:3857", (-5199000.0, -2431000.0)),  # metros, mas área distorcida ~15%
        ("EPSG:5880", (5e6, 7e6)),  # Policônica SIRGAS: metros, não UTM
    ],
)
def test_non_utm_crs_rejected(tmp_path, cfg, crs, origin):
    p = write_stack(tmp_path / "x.tif", make_scene(4, 4), crs=crs, origin=origin)
    with pytest.raises(SceneError, match="não é UTM"):
        read_scene(p, cfg)


def test_sirgas_utm_accepted(tmp_path, cfg):
    p = write_stack(tmp_path / "s.tif", make_scene(4, 4), crs="EPSG:31983")
    assert read_scene(p, cfg).grid.crs.to_epsg() == 31983


def test_south_up_rejected(tmp_path, cfg):
    p = tmp_path / "su.tif"
    with rasterio.open(
        p,
        "w",
        driver="GTiff",
        dtype="uint16",
        count=4,
        height=4,
        width=4,
        crs="EPSG:32723",
        transform=rasterio.transform.Affine(10, 0, 323200, 0, 10, 7642980),
    ) as ds:
        ds.write(make_scene(4, 4))
    with pytest.raises(SceneError, match="sul-acima"):
        read_scene(p, cfg)


@pytest.mark.parametrize("band", ["blue", "green", "red", "nir"])
def test_each_configured_band_index_is_checked(tmp_path, cfg_copy, band):
    others = [b for b in ("blue", "green", "red", "nir") if b != band]
    for i, b in enumerate(others, start=1):
        setattr(cfg_copy.bands, b, i)
    setattr(cfg_copy.bands, band, 5)
    with pytest.raises(SceneError, match="5 bandas"):
        read_scene(write_stack(tmp_path / "s.tif", make_scene(4, 4)), cfg_copy)


def test_reprojected_second_scene_is_pixel_exact_and_respects_nodata(tmp_path, cfg):
    target = read_scene(write_stack(tmp_path / "a.tif", make_scene(20, 20)), cfg).grid
    dn = make_scene(22, 22)
    dn[0, 3, 1:4] = refl_to_dn(0.5)  # azul, linha 3 da fonte = linha 2 do alvo
    dn[:, 15:, 15:] = 0  # NoData na fonte
    p = write_stack(tmp_path / "b.tif", dn, origin=(ORIGIN[0] - 10, ORIGIN[1] + 10))
    other = read_scene_on_grid(p, target, cfg)
    assert other.nir.dtype == np.float32
    assert other.blue[2, 1] == pytest.approx(0.5, abs=1e-4)
    assert other.blue[2, 5] == pytest.approx(0.04, abs=1e-4)
    assert np.isnan(other.nir[16, 16]) and not other.valid[16, 16]


def test_scl_offset_grid_is_aligned_and_keeps_zero_as_nodata(tmp_path, cfg):
    target = read_scene(write_stack(tmp_path / "a.tif", make_scene(20, 20)), cfg).grid
    scl = np.full((12, 12), 4, np.uint8)
    scl[0, :] = 8  # linha extra acima do alvo (origem 20 m mais ao norte)
    scl[5:, 5:] = 0
    with rasterio.open(
        tmp_path / "scl.tif",
        "w",
        driver="GTiff",
        dtype="uint8",
        count=1,
        height=12,
        width=12,
        crs="EPSG:32723",
        transform=from_origin(ORIGIN[0], ORIGIN[1] + 20, 20, 20),
        nodata=0,
    ) as ds:
        ds.write(scl, 1)
    out = read_scl_on_grid(tmp_path / "scl.tif", target)
    assert out.dtype == np.uint8
    assert 8 not in out  # a linha de nuvem ficou fora do recorte
    assert out[0, 0] == 4 and out[19, 19] == 0


def test_source_item_and_feature_keys_in_outputs(tmp_path, cfg):
    dn = make_scene(30, 30)
    paint(dn, slice(5, 15), slice(5, 15), **COFFEE)
    paint(dn, slice(20, 30), slice(20, 30), **FOREST)
    p = write_stack(tmp_path / "s.tif", dn, tags={"SOURCE_ITEM": "S2X_TESTE"})
    s = run_analysis(p, tmp_path / "o", cfg)
    assert s["inputs"]["primary"]["source_item"] == "S2X_TESTE"
    import json

    feat = json.loads((tmp_path / "o" / "candidatas.geojson").read_text())["features"][0]
    assert feat["type"] == "Feature" and feat["id"] == 1 and feat["properties"]["id"] == 1
