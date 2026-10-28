import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

from app.processing import indices

f32 = np.float32
refl = st.floats(0, 1.5, width=32, allow_nan=False)


def a(*v):
    return np.array(v, dtype=f32)


def test_ndvi_known_values():
    np.testing.assert_allclose(
        indices.ndvi(a(0.30, 0.40), a(0.08, 0.03)), [0.578947, 0.860465], rtol=1e-5
    )


def test_ndwi_known_value():
    assert indices.ndwi(a(0.08), a(0.02))[0] == pytest.approx(0.6)


def test_zero_denominator_is_nan_not_inf():
    assert np.isnan(indices.ndvi(a(0.0), a(0.0))[0])
    assert np.isnan(indices.savi(a(-0.25), a(-0.25), 0.5)[0])


def test_nan_propagates():
    assert np.isnan(indices.ndvi(a(np.nan), a(0.1))[0])


def test_savi_with_l_zero_equals_ndvi():
    nir, red = a(0.3, 0.5, 0.2), a(0.1, 0.05, 0.2)
    np.testing.assert_allclose(indices.savi(nir, red, 0.0), indices.ndvi(nir, red), rtol=1e-6)


def test_savi_known_value():
    # 1.5 * (0.3 - 0.1) / (0.3 + 0.1 + 0.5) = 0.3333
    assert indices.savi(a(0.3), a(0.1), 0.5)[0] == pytest.approx(1 / 3, rel=1e-5)


@given(arrays(f32, 32, elements=refl), arrays(f32, 32, elements=refl))
def test_property_ndvi_bounded_and_antisymmetric(nir, red):
    v = indices.ndvi(nir, red)
    finite = np.isfinite(v)
    assert np.all((v[finite] >= -1) & (v[finite] <= 1))
    np.testing.assert_allclose(indices.ndvi(red, nir)[finite], -v[finite], atol=1e-6)
    # NaN só quando o denominador é zero
    assert np.array_equal(~finite, (nir + red) == 0)


def test_local_std_constant_is_zero_and_ignores_nan():
    x = np.full((7, 7), 0.5, dtype=f32)
    x[3, 3] = np.nan
    out = indices.local_std(x, 3)
    assert np.isnan(out[3, 3])
    np.testing.assert_allclose(out[np.isfinite(out)], 0, atol=1e-6)


def test_local_std_detects_heterogeneity():
    x = np.zeros((5, 5), dtype=f32)
    x[:, ::2] = 1.0  # listras
    assert indices.local_std(x, 3)[2, 2] > 0.4
