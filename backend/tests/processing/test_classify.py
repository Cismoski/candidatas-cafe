import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

from app.processing.classify import (
    LandClass,
    classify,
    dense_canopy_threshold,
    otsu_threshold,
    remove_small,
)

PX = 100.0  # m² por pixel (10 m)
LOW, MID, DENSE = 0.30, 0.58, 0.86


def field(h=40, w=40, value=LOW):
    return np.full((h, w), value, dtype=np.float32)


def run(cfg, ndvi, *, ndwi=None, valid=None, quality=None, other=None):
    return classify(
        ndvi=ndvi,
        ndwi=np.full_like(ndvi, -0.5) if ndwi is None else ndwi,
        valid=np.ones(ndvi.shape, bool) if valid is None else valid,
        quality_ok=quality,
        other_ndvi=other,
        pixel_area_m2=PX,
        cfg=cfg,
    )


def n_candidates(res):
    return int((res.classes == LandClass.CANDIDATE).sum())


# --- caminho feliz --------------------------------------------------------------
def test_intermediate_block_is_one_candidate(cfg):
    ndvi = field()
    ndvi[10:20, 10:20] = MID
    res = run(cfg, ndvi)
    assert res.n_components == 1
    assert n_candidates(res) == 100
    assert res.dense_threshold_source.startswith("padrão")  # < 500 px de vegetação


def test_all_nan_does_not_crash(cfg):
    res = run(cfg, field(value=np.nan))
    assert res.n_components == 0
    assert (res.classes == LandClass.NODATA).all()


# --- BVA: limiar de NDVI mínimo ---------------------------------------------------
@pytest.mark.parametrize(
    ("value", "expected"), [(0.45, 100), (np.nextafter(np.float32(0.45), 0), 0)]
)
def test_bva_ndvi_min(cfg, value, expected):
    ndvi = field()
    ndvi[10:20, 10:20] = value
    assert n_candidates(run(cfg, ndvi)) == expected


# --- BVA: limiar de dossel fechado (padrão 0.72 neste cenário) -----------------
@pytest.mark.parametrize(
    ("value", "cls"), [(0.72, LandClass.DENSE_CANOPY), (0.7199, LandClass.CANDIDATE)]
)
def test_bva_dense_threshold(cfg, value, cls):
    ndvi = field()
    ndvi[10:20, 10:20] = value
    assert run(cfg, ndvi).classes[15, 15] == cls


# --- BVA: área mínima de 0,5 ha = 50 px ---------------------------------------
@pytest.mark.parametrize(("shape", "kept"), [((7, 7), False), ((5, 10), True), ((5, 11), True)])
def test_bva_min_area(cfg, shape, kept):
    ndvi = field()
    ndvi[5 : 5 + shape[0], 5 : 5 + shape[1]] = MID
    assert (run(cfg, ndvi).n_components == 1) is kept


# --- BVA: água (NDWI > 0) -------------------------------------------------------
@pytest.mark.parametrize(("ndwi", "water"), [(0.0, False), (np.float32(1e-6), True)])
def test_bva_water(cfg, ndwi, water):
    ndvi = field()
    ndvi[10:20, 10:20] = MID
    w = np.full_like(ndvi, -0.5)
    w[10:20, 10:20] = ndwi
    res = run(cfg, ndvi, ndwi=w)
    assert bool(res.classes[15, 15] == LandClass.WATER) is water


def test_scl_mask_excludes(cfg):
    ndvi = field()
    ndvi[10:20, 10:20] = MID
    quality = np.ones(ndvi.shape, bool)
    quality[10:20, 10:20] = False
    res = run(cfg, ndvi, quality=quality)
    assert res.n_components == 0
    assert res.classes[15, 15] == LandClass.MASKED_QUALITY


# --- buffer de borda de mata ----------------------------------------------------
def test_buffer_removes_one_column_next_to_forest_core(cfg):
    ndvi = field()
    ndvi[5:30, 0:10] = DENSE  # 250 px = 2,5 ha -> núcleo de mata
    ndvi[10:20, 10:21] = MID  # 11 colunas encostadas na mata
    res = run(cfg, ndvi)
    assert n_candidates(res) == 100  # a coluna 10 foi descartada
    assert res.classes[15, 10] == LandClass.DISCARDED


def test_small_dense_patch_does_not_create_buffer(cfg):
    ndvi = field()
    ndvi[10:20, 10:20] = MID
    ndvi[15, 15] = DENSE  # um pé vigoroso no meio do talhão
    res = run(cfg, ndvi)
    assert n_candidates(res) == 99
    assert res.classes[15, 15] == LandClass.DENSE_CANOPY


def test_closing_never_turns_nodata_into_candidate(cfg):
    ndvi = field()
    ndvi[10:20, 10:20] = MID
    ndvi[15, 15] = np.nan
    res = run(cfg, ndvi)
    assert res.classes[15, 15] == LandClass.NODATA
    assert n_candidates(res) == 99


def test_field_touching_image_border_keeps_border_row(cfg):
    ndvi = field()
    ndvi[0:10, 0:10] = MID
    assert n_candidates(run(cfg, ndvi)) == 100


# --- regra temporal ---------------------------------------------------------------
def _temporal(cfg, other_value):
    ndvi = field(value=0.5)  # tudo intermediário
    ndvi[:, :20] = LOW
    other = np.full_like(ndvi, LOW)
    other[:, 20:] = other_value
    return run(cfg, ndvi, other=other)


@pytest.mark.parametrize(
    ("other", "kept"),
    [
        (0.625, True),  # |Δ| = 0.125 = limite (valores exatos em float32)
        (float(np.nextafter(np.float32(0.625), 1)), False),
        (0.375, True),  # |Δ| = 0.125 para baixo
    ],
)
def test_bva_temporal_change(cfg_copy, other, kept):
    cfg_copy.temporal.max_abs_ndvi_change = 0.125
    cfg_copy.temporal.ndvi_min_other = 0.3
    assert (_temporal(cfg_copy, other).n_components > 0) is kept


@pytest.mark.parametrize(
    ("other", "kept"), [(0.45, True), (float(np.nextafter(np.float32(0.45), 0)), False)]
)
def test_bva_temporal_floor(cfg, other, kept):
    assert (_temporal(cfg, other).n_components > 0) is kept


def test_temporal_accepts_wet_season_increase(cfg):
    """Café sobe de NDVI na chuva (0,5 -> 0,72): não pode ser descartado."""
    res = _temporal(cfg, 0.72)
    assert res.n_components == 1 and res.temporal_rejected_px == 0


def test_temporal_reports_rejected_pixels(cfg):
    res = _temporal(cfg, 0.1)  # virou solo na outra data
    assert res.n_components == 0 and res.temporal_rejected_px == 40 * 20


def test_temporal_missing_data_keeps_and_reports(cfg):
    res = _temporal(cfg, np.nan)
    assert res.n_components == 1
    assert res.temporal_unverified_px == n_candidates(res) > 0


def test_no_temporal_reports_zero_unverified(cfg):
    ndvi = field()
    ndvi[10:20, 10:20] = MID
    assert run(cfg, ndvi).temporal_unverified_px == 0


# --- limiar de dossel por Otsu (branches) -------------------------------------
def test_otsu_splits_bimodal():
    rng = np.random.default_rng(0)
    v = np.concatenate([rng.normal(0.55, 0.03, 5000), rng.normal(0.82, 0.02, 5000)]).astype(
        np.float32
    )
    t, eta = otsu_threshold(v, 0.45, 1.0)
    assert 0.62 < t < 0.76 and eta > 0.85


def test_dense_threshold_uses_otsu_when_in_range(cfg):
    rng = np.random.default_rng(1)
    v = np.concatenate([rng.normal(0.58, 0.03, 600), rng.normal(0.82, 0.02, 600)]).astype(
        np.float32
    )
    t, src, _ = dense_canopy_threshold(v, np.ones(v.shape, bool), cfg)
    assert (
        src.startswith("Otsu") and cfg.rules.dense_ndvi_floor <= t <= cfg.rules.dense_ndvi_ceiling
    )


def test_dense_threshold_falls_back_when_otsu_out_of_range(cfg):
    rng = np.random.default_rng(2)
    v = np.concatenate([rng.normal(0.47, 0.005, 600), rng.normal(0.55, 0.005, 600)]).astype(
        np.float32
    )
    t, src, _ = dense_canopy_threshold(v, np.ones(v.shape, bool), cfg)
    assert t == cfg.rules.dense_ndvi_default and "fora" in src


def test_dense_threshold_falls_back_with_few_pixels(cfg):
    v = np.full(499, 0.6, dtype=np.float32)
    t, src, _ = dense_canopy_threshold(v, np.ones(v.shape, bool), cfg)
    assert t == cfg.rules.dense_ndvi_default and "poucos" in src


@pytest.mark.parametrize(
    "sample",
    [
        np.full(2000, 0.6, np.float32),  # constante: eta = 0
        np.random.default_rng(5).normal(0.62, 0.05, 5000).astype(np.float32),  # unimodal
    ],
)
def test_dense_threshold_falls_back_without_two_populations(cfg, sample):
    t, src, eta = dense_canopy_threshold(sample, np.ones(sample.shape, bool), cfg)
    assert t == cfg.rules.dense_ndvi_default and "duas populações" in src
    assert eta < cfg.rules.otsu_min_separability


def test_remove_small_empty_and_diagonal_connectivity():
    assert remove_small(np.zeros((5, 5), bool), 1)[1] == 0
    diag = np.eye(5, dtype=bool)
    labels, n = remove_small(diag, 5)
    assert n == 1 and (labels > 0).sum() == 5  # 8-conectividade


# --- property tests ---------------------------------------------------------------
grids = arrays(
    np.float32,
    (24, 24),
    elements=st.one_of(st.just(np.float32(np.nan)), st.floats(-0.25, 0.9375, width=32)),
)


@settings(max_examples=60, deadline=None)
@given(grids, st.integers(0, 14), st.integers(0, 14), st.floats(0.5, 0.625, width=32))
def test_property_invariants(cfg, noise, y, x, value):
    # ruído aleatório + um talhão garantido: o teste não fica vazio
    ndvi = noise.copy()
    block = ndvi[y : y + 9, x : x + 9]
    ndvi[y : y + 9, x : x + 9] = np.where(np.isnan(block), np.nan, np.float32(value))
    res = run(cfg, ndvi)
    cand = res.classes == LandClass.CANDIDATE
    # NoData nunca vira candidato
    assert not (cand & np.isnan(ndvi)).any()
    # candidato sempre tem NDVI intermediário
    assert np.all(
        (ndvi[cand] >= np.float32(cfg.rules.ndvi_min))
        & (ndvi[cand] < np.float32(res.dense_threshold))
    )
    # todo componente respeita a área mínima
    sizes = np.bincount(res.labels.ravel())[1:]
    assert np.all(sizes * PX / 10_000 >= cfg.morphology.min_area_ha)
    assert res.n_components == len(sizes)


@settings(max_examples=25, deadline=None)
@given(st.integers(0, 20), st.integers(0, 20))
def test_property_translation_invariant_area(cfg, dy, dx):
    ndvi = field(value=LOW)
    ndvi[dy : dy + 8, dx : dx + 9] = MID
    assert n_candidates(run(cfg, ndvi)) == 72
