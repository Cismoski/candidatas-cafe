"""Value objects: validação na criação, forma canônica e imutabilidade."""

import uuid
from dataclasses import FrozenInstanceError
from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.values import AcquisitionDate, AnalysisId, AnalysisTitle, IdempotencyKey


# --- AnalysisId -------------------------------------------------------------------------
@given(st.uuids())
def test_analysis_id_accepts_any_uuid_in_canonical_form(u):
    for raw in (str(u), str(u).upper(), u.hex):
        assert AnalysisId(raw) == str(u)


@pytest.mark.parametrize(
    "raw", ["", "abc", "../../etc/passwd", "11111111-1111-4111-8111-11111111111", None, 42]
)
def test_analysis_id_rejects_non_uuid(raw):
    with pytest.raises(ValueError):
        AnalysisId(raw)


def test_analysis_id_is_a_str_for_sqlite_and_paths():
    a = AnalysisId.new()
    assert isinstance(a, str) and uuid.UUID(a).version == 4


# --- IdempotencyKey: BVA em 8 e 64 caracteres ---------------------------------------------
@pytest.mark.parametrize(
    ("raw", "ok"),
    [
        ("a" * 7, False),
        ("a" * 8, True),
        ("a" * 64, True),
        ("a" * 65, False),
        ("abc-def_12", True),
        ("abc def12", False),
        ("abcdefgh\n", False),
        ("ação-1234", False),
    ],
)
def test_idempotency_key_bva(raw, ok):
    if ok:
        assert IdempotencyKey(raw) == raw
    else:
        with pytest.raises(ValueError, match="Idempotency-Key"):
            IdempotencyKey(raw)


# --- AnalysisTitle ------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "filename", "expected"),
    [
        ("  Talhão   norte ", "x.tif", "Talhão norte"),
        ("", "cena_agosto.tif", "cena_agosto.tif"),
        ("   ", None, "Análise"),
        ("", "  ", "Análise"),
        ("", "a" * 100, "a" * 80),
        ("t" * 80, "x.tif", "t" * 80),
    ],
)
def test_title_normalizes_and_falls_back(raw, filename, expected):
    assert AnalysisTitle.from_form(raw, filename).value == expected


@pytest.mark.parametrize("raw", ["t" * 81, b"bytes", None])
def test_title_rejects_long_or_non_text(raw):
    with pytest.raises(ValueError):
        AnalysisTitle.from_form(raw, "x.tif")


@pytest.mark.parametrize("bad", ["", " a", "a  b", "t" * 81])
def test_title_invariant_holds_even_when_built_directly(bad):
    with pytest.raises(ValueError):
        AnalysisTitle(bad)


# --- AcquisitionDate --------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "iso", "br"),
    [
        ("2025-08-16T13:27:18Z", "2025-08-16", "16/08/2025"),
        ("2025-08-16", "2025-08-16", "16/08/2025"),
        ("2024-02-29T00:00:00+00:00", "2024-02-29", "29/02/2024"),
        ("2025-02-29", None, "data desconhecida"),  # não existe
        ("2025-13-45", None, "data desconhecida"),
        ("", None, "data desconhecida"),
        (None, None, "data desconhecida"),
        (20250816, None, "data desconhecida"),
    ],
)
def test_acquisition_date_never_raises(raw, iso, br):
    d = AcquisitionDate.parse(raw)
    assert (d.iso(), d.br(), d.known) == (iso, br, iso is not None)


@given(st.dates())
def test_acquisition_date_round_trip(day):
    assert AcquisitionDate.parse(day.isoformat()).day == day


def test_value_objects_are_immutable():
    with pytest.raises(FrozenInstanceError):
        AcquisitionDate(date(2025, 8, 16)).day = None  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        AnalysisTitle("a").value = "b"  # type: ignore[misc]
