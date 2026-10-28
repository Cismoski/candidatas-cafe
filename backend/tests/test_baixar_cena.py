"""scripts/baixar_cena.py sem rede: tiles sintéticos locais no lugar dos COGs do bucket."""

import importlib.util
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from app import chat
from app.processing.config import load_config
from app.processing.pipeline import run_analysis
from app.uploads import RasterLimits, validate_multispectral, validate_scl

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("baixar_cena", ROOT / "scripts" / "baixar_cena.py")
bc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bc)

CRS = "EPSG:32723"
TILE_X, TILE_Y = 300000.0, 7700020.0  # origem real do tile T23KLS
# Recorte de referência: 64x64 px a 10 m, a 100 px da origem do "tile"
REF_X, REF_Y, N = TILE_X + 1000, TILE_Y - 1000, 64
TILE_PX = 200


def _write(path, data, transform, dtype):
    data = data[None] if data.ndim == 2 else data
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=data.shape[2],
        height=data.shape[1],
        count=data.shape[0],
        dtype=dtype,
        crs=CRS,
        transform=transform,
        nodata=0,
    ) as d:
        d.write(data)


@pytest.fixture
def tile(tmp_path):
    """Tile 'COG' sintético de vegetação: DN = base da banda + (linha*TILE_PX + coluna) mod 500."""
    src = tmp_path / "bucket"
    src.mkdir()
    rows, cols = np.mgrid[0:TILE_PX, 0:TILE_PX]
    hrefs = {}
    for key, _ in bc.BANDS:
        base = {"blue": 1300, "green": 1600, "red": 1400, "nir": 4000}[key]
        arr = (base + (rows * TILE_PX + cols) % 500).astype(np.uint16)
        p = src / f"{key}.tif"
        _write(p, arr, from_origin(TILE_X, TILE_Y, 10, 10), "uint16")
        hrefs[key] = str(p)
    scl = np.full((TILE_PX // 2, TILE_PX // 2), 4, np.uint8)
    # dentro do recorte (linhas/colunas 50..81 a 20 m): nuvem, sombra e água
    scl[50, 50] = 9
    scl[51, 51] = 3
    scl[52, 52] = 6
    p = src / "scl.tif"
    _write(p, scl, from_origin(TILE_X, TILE_Y, 20, 20), "uint8")
    hrefs["scl"] = str(p)
    ref = tmp_path / "ref.tif"
    _write(ref, np.ones((4, N, N), np.uint16), from_origin(REF_X, REF_Y, 10, 10), "uint16")
    item = {
        "id": "S2B_T23KLS_20250217T132718_L2A",
        "properties": {"datetime": "2025-02-17T13:28:13.144000Z"},
        "assets": {
            k: {"href": v, "raster:bands": [{"scale": 0.0001, "offset": -0.1}]}
            for k, v in hrefs.items()
        },
    }
    return item, ref, tmp_path / "out"


def run(tile):
    item, ref, out = tile
    report = bc.extract(
        item, ref, out, "fev", allowed_prefix=None, accessed=datetime(2026, 10, 28, tzinfo=UTC)
    )
    return report, out


def test_window_is_exact_crop_with_tags_and_band_names(tile):
    report, out = run(tile)
    with (
        rasterio.open(out / "fev_imagem.tif") as d,
        rasterio.open(tile[0]["assets"]["red"]["href"]) as t,
    ):
        assert d.shape == (N, N) and d.transform == from_origin(REF_X, REF_Y, 10, 10)
        assert np.array_equal(d.read(3), t.read(1)[100 : 100 + N, 100 : 100 + N])
        assert d.descriptions == ("B02_blue", "B03_green", "B04_red", "B08_nir")
        tags = d.tags()
        assert tags["ACQUISITION_UTC"] == "2025-02-17T13:28:13.144000Z"
        assert tags["SOURCE_ITEM"] == "S2B_T23KLS_20250217T132718_L2A"
        assert tags["ATTRIBUTION"] == "Contains modified Copernicus Sentinel data (2025)"
    with rasterio.open(out / "fev_scl.tif") as s:
        assert s.shape == (N // 2, N // 2) and s.res == (20, 20)
        # a atribuição acompanha também a SCL
        assert s.tags()["ATTRIBUTION"] == "Contains modified Copernicus Sentinel data (2025)"
        assert s.tags()["TERMS"] == bc.TERMS


def test_second_date_masks_invalid_scl_as_nodata(tile):
    report, out = run(tile)
    with (
        rasterio.open(out / "fev_imagem.tif") as a,
        rasterio.open(out / "fev_segunda_data.tif") as b,
    ):
        full, masked = a.read(), b.read()
    # SCL (50,50)=nuvem e (51,51)=sombra no tile -> (0,0) e (1,1) no recorte a 20 m -> 2x2 px a 10 m
    zero = (masked == 0).all(axis=0)
    assert zero[0:2, 0:2].all() and zero[2:4, 2:4].all()
    assert not zero[4:6, 4:6].any()  # água (6) é válida
    assert zero.sum() == 8
    assert np.array_equal(full[:, ~zero], masked[:, ~zero])
    assert report["pixels_validos_scl_pct"] == round(100 * (1 - 8 / N**2), 2)
    assert report["scl_pct"]["nuvem prob. alta"] == round(100 / (N // 2) ** 2, 2)


def test_attribution_has_source_terms_and_matching_hashes(tile):
    report, out = run(tile)
    txt = (out / "fev_ATRIBUICAO.txt").read_text()
    assert "Contains modified Copernicus Sentinel data (2025)." in txt
    assert bc.STAC + "S2B_T23KLS_20250217T132718_L2A" in txt and bc.TERMS in txt
    assert "Acessado em 28/10/2026" in txt
    for name in ("fev_imagem.tif", "fev_scl.tif", "fev_segunda_data.tif"):
        assert f"{bc.sha256(out / name)}  {name}" in txt


def test_output_passes_upload_validation_and_runs_as_second_date(tile, tmp_path):
    """O que o script gera entra pela mesma porta que o upload do usuário."""
    _, out = run(tile)
    limits = RasterLimits(max_dim=1500)
    validate_multispectral(out / "fev_imagem.tif", limits)
    validate_multispectral(out / "fev_segunda_data.tif", limits)
    validate_scl(out / "fev_scl.tif", limits)
    s = run_analysis(
        out / "fev_imagem.tif",
        tmp_path / "res",
        load_config(),
        scl_path=out / "fev_scl.tif",
        secondary_path=out / "fev_segunda_data.tif",
    )
    assert s["inputs"]["secondary"]["source_item"] == "S2B_T23KLS_20250217T132718_L2A"
    json.dumps(s)
    # Contrato com os consumidores do summary (regressão: o pipeline gravava
    # "temporal" e o chat/frontend esperavam "two_dates": duas datas viravam uma)
    assert s["method"]["mode"] == "two_dates"
    assert any("estação chuvosa" in lim for lim in s["limitations"])  # imagem de fevereiro
    assert chat.build_context(s)["metodo"]["modo"] == "duas datas"
    assert "Só uma data" not in chat.automatic_answer("e a segunda data?", s)
    assert "segunda data foi usada" in chat.introduction(s)


def test_frontend_mode_type_matches_pipeline():
    types = (ROOT / "frontend" / "src" / "api" / "types.ts").read_text()
    union = re.search(r"mode: ([^;]+);", types).group(1)
    assert set(re.findall(r'"(\w+)"', union)) == {"single_date", "two_dates"}
    src = (ROOT / "backend" / "app" / "processing" / "pipeline.py").read_text()
    assert 'mode = "two_dates" if other_scene is not None else "single_date"' in src


@pytest.mark.parametrize(
    ("dx", "ok"), [(0, True), (0.001, False), (5, False), (10, True), (20, True)]
)
def test_aligned_window_bva(dx, ok):
    t = from_origin(TILE_X, TILE_Y, 10, 10)
    bounds = (REF_X + dx, REF_Y - 640, REF_X + dx + 640, REF_Y)
    if ok:
        w = bc.aligned_window(bounds, t, 10)
        assert (w.col_off, w.row_off, w.width, w.height) == (100 + dx // 10, 100, 64, 64)
    else:
        with pytest.raises(bc.SceneError, match="reamostrar"):
            bc.aligned_window(bounds, t, 10)


def test_scl_window_at_20m_requires_even_alignment():
    t = from_origin(TILE_X, TILE_Y, 20, 20)
    with pytest.raises(bc.SceneError):  # recorte começando no meio de um pixel de 20 m
        bc.aligned_window((REF_X + 10, REF_Y - 640, REF_X + 650, REF_Y), t, 20)


def test_crop_outside_tile_is_rejected(tile):
    item, ref, out = tile
    far = ref.parent / "far.tif"
    _write(far, np.ones((4, N, N), np.uint16), from_origin(TILE_X + 1800, REF_Y, 10, 10), "uint16")
    with pytest.raises(bc.SceneError, match="limites do tile"):
        bc.extract(item, far, out, "x", allowed_prefix=None)


def test_crs_mismatch_is_rejected(tile, tmp_path):
    item, _, out = tile
    other = tmp_path / "utm22.tif"
    with rasterio.open(
        other,
        "w",
        driver="GTiff",
        width=N,
        height=N,
        count=4,
        dtype="uint16",
        crs="EPSG:32722",
        transform=from_origin(REF_X, REF_Y, 10, 10),
    ) as d:
        d.write(np.ones((4, N, N), np.uint16))
    with pytest.raises(bc.SceneError, match="CRS"):
        bc.extract(item, other, out, "x", allowed_prefix=None)


def test_asset_outside_bucket_rejected(tile):
    item = tile[0]
    with pytest.raises(bc.SceneError, match="fora do bucket"):
        bc.check_asset(item, "red", bc.DATA_PREFIX)
    item["assets"]["red"]["href"] = "https://evil.example/" + bc.DATA_PREFIX + "B04.tif"
    with pytest.raises(bc.SceneError, match="fora do bucket"):
        bc.check_asset(item, "red", bc.DATA_PREFIX)


@pytest.mark.parametrize("band", [{"scale": 0.0001, "offset": 0}, {"scale": 1}, {}])
def test_unexpected_radiometric_scale_rejected(tile, band):
    item = tile[0]
    item["assets"]["nir"]["raster:bands"] = [band]
    with pytest.raises(bc.SceneError, match="scale/offset"):
        bc.check_asset(item, "nir", None)


def test_missing_asset_rejected(tile):
    item = tile[0]
    del item["assets"]["scl"]
    with pytest.raises(bc.SceneError, match="sem o asset scl"):
        bc.check_asset(item, "scl", None)


@pytest.mark.parametrize("item_id", ["../../etc", "a b", "x?y=1"])
def test_invalid_item_id_never_hits_network(item_id):
    with pytest.raises(bc.SceneError):
        bc.fetch_item(item_id)


def test_asset_with_unexpected_resolution_is_rejected(tile):
    """Regressão: a janela usa a resolução esperada; SCL de 10 m lida como 20 m
    cobriria metade do recorte sem erro."""
    item, ref, out = tile
    item["assets"]["scl"]["href"] = item["assets"]["red"]["href"]  # arquivo de 10 m
    with pytest.raises(bc.SceneError, match="resolução"):
        bc.extract(item, ref, out, "x", allowed_prefix=None)


def test_catalog_returning_other_item_is_rejected(monkeypatch):
    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"id": "OUTRO"}

    monkeypatch.setattr(bc.httpx, "get", lambda *a, **k: R())
    with pytest.raises(bc.SceneError, match="outro item"):
        bc.fetch_item("S2B_T23KLS_20250217T132718_L2A")


@pytest.mark.parametrize("item_id", ["S2B_é", "a" * 81, ""])
def test_item_id_ascii_and_length(item_id):
    with pytest.raises(bc.SceneError):
        bc.fetch_item(item_id)


def test_cli_fixed_access_date_is_reproducible(tile, monkeypatch, capsys):
    item, ref, out = tile
    monkeypatch.setattr(bc, "fetch_item", lambda _: item)
    monkeypatch.setattr(bc, "DATA_PREFIX", None)
    args = [
        item["id"],
        "--grade",
        str(ref),
        "--saida",
        str(out),
        "--prefixo",
        "r",
        "--acessado",
        "2026-10-28",
    ]
    assert bc.main(args) == 0
    first = (out / "r_ATRIBUICAO.txt").read_text()
    assert bc.main(args) == 0
    assert (out / "r_ATRIBUICAO.txt").read_text() == first and "28/10/2026" in first


def test_cli_reports_malformed_catalog_without_traceback(tile, monkeypatch, capsys):
    item, ref, out = tile
    del item["properties"]
    monkeypatch.setattr(bc, "fetch_item", lambda _: item)
    assert bc.main([item["id"], "--grade", str(ref), "--saida", str(out), "--prefixo", "r"]) == 1
    assert capsys.readouterr().err.startswith("erro:")
