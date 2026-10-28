import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

from app.processing.radiometry import RadiometryError, dn_to_reflectance, resolve_scale_offset

S, O = 0.0001, -0.1  # noqa: E741 (scale, offset)


# --- BVA nos limites do uint16 e do NoData -----------------------------------------
@pytest.mark.parametrize(
    ("dn", "expected"),
    [
        (1, -0.0999),  # menor DN válido (logo acima do NoData)
        (999, -0.0001),
        (1000, 0.0),  # zero de reflectância
        (1001, 0.0001),
        (3000, 0.2),
        (11000, 1.0),
        (65535, 6.4535),  # maior uint16
    ],
)
def test_bva_valid_dn(dn, expected):
    out = dn_to_reflectance(np.array([dn], dtype=np.uint16), S, O, nodata_dn=0)
    assert out.dtype == np.float32
    assert out[0] == pytest.approx(expected, abs=1e-6)


def test_bva_nodata_becomes_nan():
    out = dn_to_reflectance(np.array([0, 1], dtype=np.uint16), S, O, nodata_dn=0)
    assert np.isnan(out[0]) and np.isfinite(out[1])


def test_float_input_is_rejected_to_prevent_double_conversion():
    once = dn_to_reflectance(np.array([3000], dtype=np.uint16), S, O, 0)
    with pytest.raises(RadiometryError, match="já convertido"):
        dn_to_reflectance(once, S, O, 0)


# --- property test ---------------------------------------------------------------
@given(arrays(np.uint16, st.integers(1, 64)))
def test_property_affine_and_nan_iff_nodata(dn):
    out = dn_to_reflectance(dn, S, O, nodata_dn=0)
    nod = dn == 0
    assert np.array_equal(np.isnan(out), nod)
    np.testing.assert_allclose(out[~nod], dn[~nod] * S + O, rtol=1e-6, atol=1e-6)


# --- branches de resolve_scale_offset ---------------------------------------------
def test_scale_offset_from_file_when_present():
    s, o, src = resolve_scale_offset((S,) * 4, (O,) * 4, 1.0, 0.0)
    assert s == (S,) * 4 and o == (O,) * 4 and src == "metadados do GeoTIFF"


def test_scale_offset_offset_only_counts_as_metadata():
    s, o, src = resolve_scale_offset((1.0,), (-0.1,), 9.0, 9.0)
    assert (s, o, src) == ((1.0,), (-0.1,), "metadados do GeoTIFF")


def test_scale_offset_defaults_when_file_has_none():
    s, o, src = resolve_scale_offset((1.0,) * 4, (0.0,) * 4, S, O)
    assert s == (S,) * 4 and o == (O,) * 4 and "padrão" in src
