# /// script
# requires-python = ">=3.13"
# dependencies = ["rasterio>=1.5.2", "numpy>=2.5.4", "httpx>=0.28.1"]
# ///
"""Recorta uma cena Sentinel-2 L2A do Earth Search na mesma grade do kit.

Uso (da raiz do repositório):
    uv run scripts/baixar_cena.py S2B_T23KLS_20250217T132718_L2A \\
        --grade frontend/public/amostra/imagem_multiespectral.tif \\
        --saida frontend/public/amostra --prefixo s2b_20250217 --acessado 2026-10-28

Lê só a janela do recorte nos COGs públicos (requisições HTTP de intervalo,
sem baixar o tile de 110 km). Não reamostra: a cena precisa estar no mesmo
CRS e na mesma grade de 10 m da imagem de referência, senão o script para.
O recorte também precisa caber na grade de 20 m da SCL (origem e tamanho em
número par de pixels de 10 m), como o do kit.

Gera, no formato do kit (uint16, DN original, nodata 0):
- <prefixo>_imagem.tif: B02, B03, B04, B08, para usar como imagem principal;
- <prefixo>_scl.tif: SCL a 20 m, para acompanhar a imagem principal;
- <prefixo>_segunda_data.tif: as 4 bandas com DN 0 onde a SCL não é
  vegetação, solo, água ou não classificado (classes 4-7). O upload da segunda
  data não tem campo de SCL, então a máscara vai embutida como nodata;
- <prefixo>_ATRIBUICAO.txt: origem, termos, verificação e SHA-256.
"""

import argparse
import hashlib
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import numpy as np
import rasterio
from rasterio.windows import Window

STAC = "https://earth-search.aws.element84.com/v1/collections/sentinel-2-c1-l2a/items/"
# Só lê dados do bucket público da coleção: o href vem do catálogo, não do usuário
DATA_PREFIX = "https://e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com/"
BANDS = [("blue", "B02_blue"), ("green", "B03_green"), ("red", "B04_red"), ("nir", "B08_nir")]
SCALE, OFFSET = 0.0001, -0.1  # o pipeline assume isso (baseline >= 04.00)
SCL_VALID = (4, 5, 6, 7)
SCL_NAMES = {
    0: "sem dado",
    1: "saturado/defeituoso",
    2: "área escura/topografia",
    3: "sombra de nuvem",
    4: "vegetação",
    5: "solo exposto",
    6: "água",
    7: "não classificado",
    8: "nuvem prob. média",
    9: "nuvem prob. alta",
    10: "cirrus fino",
    11: "neve",
}
TERMS = "https://sentinel.esa.int/documents/247904/690755/Sentinel_Data_Legal_Notice"
GDAL_ENV = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",  # não lista o bucket
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif",
    "GDAL_HTTP_MAX_RETRY": "3",
    "GDAL_HTTP_RETRY_DELAY": "2",
}


class SceneError(Exception):
    pass


def aligned_window(ref_bounds, transform, res: float) -> Window:
    """Janela inteira da grade da cena que cobre exatamente o recorte de referência."""
    left, bottom, right, top = ref_bounds
    if transform.b or transform.d:
        raise SceneError("grade da cena com rotação")
    col = (left - transform.c) / res
    row = (transform.f - top) / res
    width = (right - left) / res
    height = (top - bottom) / res
    for v in (col, row, width, height):
        if abs(v - round(v)) > 1e-6:
            raise SceneError(
                f"recorte fora da grade de {res:g} m da cena (deslocamento de "
                f"{abs(v - round(v)) * res:.2f} m); seria preciso reamostrar"
            )
    return Window(round(col), round(row), round(width), round(height))


def check_asset(item: dict, key: str, allowed_prefix: str | None) -> str:
    asset = item["assets"].get(key)
    if asset is None:
        raise SceneError(f"cena sem o asset {key}")
    href = asset["href"]
    if allowed_prefix and not href.startswith(allowed_prefix):
        raise SceneError(f"asset {key} fora do bucket esperado: {href}")
    if key != "scl":
        band = (asset.get("raster:bands") or [{}])[0]
        if band.get("scale") != SCALE or band.get("offset") != OFFSET:
            raise SceneError(
                f"{key}: scale/offset {band.get('scale')}/{band.get('offset')} diferentes de "
                f"{SCALE}/{OFFSET}, que o pipeline assume"
            )
    return href


def read_window(href: str, ref, res: float) -> tuple[np.ndarray, rasterio.Affine]:
    with rasterio.open(href) as ds:
        if ds.crs != ref.crs:
            raise SceneError(f"CRS da cena {ds.crs} diferente da referência {ref.crs}")
        # A janela é calculada com `res`: se o arquivo tiver outra resolução, leria
        # outra área sem erro (ex.: SCL de 10 m lida como 20 m cobre metade do recorte)
        if abs(ds.transform.a - res) > 1e-9 or abs(ds.transform.e + res) > 1e-9:
            raise SceneError(
                f"resolução {ds.transform.a:g} x {ds.transform.e:g} m, esperado {res:g} x -{res:g} m"
            )
        win = aligned_window(ref.bounds, ds.transform, res)
        if (
            win.col_off < 0
            or win.row_off < 0
            or win.col_off + win.width > ds.width
            or win.row_off + win.height > ds.height
        ):
            raise SceneError("o recorte sai dos limites do tile")
        return ds.read(1, window=win), ds.window_transform(win)


def scl_mask_10m(scl20: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """True onde o pixel de 10 m é válido (SCL 20 m replicada 2x2)."""
    up = np.repeat(np.repeat(scl20, 2, axis=0), 2, axis=1)
    if up.shape != shape:
        raise SceneError(f"SCL {scl20.shape} não corresponde às bandas {shape}")
    return np.isin(up, SCL_VALID)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(
    item: dict,
    ref_path: Path,
    out_dir: Path,
    prefix: str,
    allowed_prefix: str | None = DATA_PREFIX,
    accessed: datetime | None = None,
) -> dict:
    """Recorta, grava os três GeoTIFFs e a atribuição; devolve o relatório."""
    item_id = item["id"]
    acquired = item["properties"]["datetime"]
    year = acquired[:4]
    hrefs = {k: check_asset(item, k, allowed_prefix) for k, _ in BANDS} | {
        "scl": check_asset(item, "scl", allowed_prefix)
    }
    with rasterio.Env(**GDAL_ENV), rasterio.open(ref_path) as ref:
        bands, transform = [], None
        for key, _ in BANDS:
            arr, transform = read_window(hrefs[key], ref, 10.0)
            bands.append(arr)
        scl, scl_transform = read_window(hrefs["scl"], ref, 20.0)
        crs = ref.crs
    if any(b.dtype != np.uint16 for b in bands) or scl.dtype != np.uint8:
        raise SceneError("tipos inesperados (bandas uint16, SCL uint8)")
    stack = np.stack(bands)

    valid = scl_mask_10m(scl, stack.shape[1:])
    nodata = (stack == 0).any(axis=0)
    masked = np.where(valid & ~nodata, stack, 0).astype(np.uint16)

    tags = {
        "ACQUISITION_UTC": acquired,
        "SOURCE_ITEM": item_id,
        "ATTRIBUTION": f"Contains modified Copernicus Sentinel data ({year})",
        "TERMS": TERMS,
    }
    profile = dict(
        driver="GTiff",
        crs=crs,
        transform=transform,
        width=stack.shape[2],
        height=stack.shape[1],
        nodata=0,
        compress="deflate",
        predictor=2,
        tiled=True,
        blockxsize=256,
        blockysize=256,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "imagem": out_dir / f"{prefix}_imagem.tif",
        "scl": out_dir / f"{prefix}_scl.tif",
        "segunda_data": out_dir / f"{prefix}_segunda_data.tif",
    }
    for name, data, mod in [
        ("imagem", stack, "Spatial crop and four-band stack; original DN preserved"),
        (
            "segunda_data",
            masked,
            "Spatial crop and four-band stack; original DN preserved; "
            "DN set to 0 where SCL is not 4-7",
        ),
    ]:
        with rasterio.open(paths[name], "w", count=4, dtype="uint16", **profile) as dst:
            dst.write(data)
            dst.update_tags(**tags, MODIFICATION=mod)
            for i, (_, desc) in enumerate(BANDS, 1):
                dst.set_band_description(i, desc)
    scl_profile = profile | {
        "transform": scl_transform,
        "width": scl.shape[1],
        "height": scl.shape[0],
        "predictor": 1,
        "blockxsize": 128,
        "blockysize": 128,
    }
    with rasterio.open(paths["scl"], "w", count=1, dtype="uint8", **scl_profile) as dst:
        dst.write(scl, 1)
        dst.set_band_description(1, "Sentinel-2_SCL_20m")
        dst.update_tags(**tags, MODIFICATION="Spatial crop; original resolution and values")

    counts = {int(k): int(v) for k, v in zip(*np.unique(scl, return_counts=True), strict=True)}
    total = scl.size
    report = {
        "item": item_id,
        "aquisicao_utc": acquired,
        "pixels_sem_dado_pct": round(100 * float(nodata.mean()), 2),
        "pixels_validos_scl_pct": round(100 * float((valid & ~nodata).mean()), 2),
        "pixels_mascarados": int((~(valid & ~nodata)).sum()),
        "scl_pct": {SCL_NAMES.get(k, str(k)): round(100 * v / total, 2) for k, v in counts.items()},
        "sha256": {p.name: sha256(p) for p in paths.values()},
    }
    accessed = accessed or datetime.now(UTC)
    (out_dir / f"{prefix}_ATRIBUICAO.txt").write_text(
        attribution(item, hrefs, report, accessed), encoding="utf-8"
    )
    return report


def attribution(item: dict, hrefs: dict, report: dict, accessed: datetime) -> str:
    year = report["aquisicao_utc"][:4]
    scl = "\n".join(f"  {k}: {v}%" for k, v in report["scl_pct"].items())  # ordem da SCL
    files = "\n".join(f"  {v}  {k}" for k, v in report["sha256"].items())
    sources = "\n".join(f"  {k}: {v}" for k, v in hrefs.items())
    return f"""PROCEDÊNCIA DOS DADOS

Contains modified Copernicus Sentinel data ({year}).
Modificações: recorte espacial na grade da imagem do kit e empilhamento das
bandas B02, B03, B04 e B08 (DN original); recorte da SCL sem mudança de
resolução. O arquivo *_segunda_data.tif tem DN 0 onde a SCL não é 4-7.
Nenhuma classificação de café foi adicionada.

Cena: {item["id"]}.
Aquisição: {report["aquisicao_utc"]}.
Catálogo: Earth Search, Element 84, sentinel-2-c1-l2a.
Acessado em {accessed:%d/%m/%Y}:
{STAC}{item["id"]}

Arquivos de origem (COGs):
{sources}

Termos de dados Sentinel indicados pela coleção de origem:
{TERMS}

Verificação no recorte (gerada por scripts/baixar_cena.py):
  pixels sem dado: {report["pixels_sem_dado_pct"]}%
  pixels válidos pela SCL (classes 4-7): {report["pixels_validos_scl_pct"]}%
  pixels zerados em *_segunda_data.tif: {report["pixels_mascarados"]}
  classes da SCL:
{scl}

SHA-256:
{files}
"""


def fetch_item(item_id: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_]{1,80}", item_id):
        raise SceneError("id de cena inválido")
    r = httpx.get(STAC + item_id, timeout=30, follow_redirects=False)
    r.raise_for_status()
    item = r.json()
    if not isinstance(item, dict) or item.get("id") != item_id:
        raise SceneError("o catálogo devolveu outro item")
    return item


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("item", help="id da cena no Earth Search (sentinel-2-c1-l2a)")
    ap.add_argument("--grade", type=Path, required=True, help="GeoTIFF que define CRS e recorte")
    ap.add_argument("--saida", type=Path, required=True)
    ap.add_argument("--prefixo", required=True)
    ap.add_argument(
        "--acessado",
        type=lambda v: datetime.strptime(v, "%Y-%m-%d").replace(tzinfo=UTC),
        help="data de acesso a registrar (AAAA-MM-DD); padrão: hoje. Fixe para refazer "
        "o recorte sem mudar a atribuição",
    )
    a = ap.parse_args(argv)
    try:
        item = fetch_item(a.item)
        report = extract(item, a.grade, a.saida, a.prefixo, DATA_PREFIX, accessed=a.acessado)
    except (SceneError, httpx.HTTPError, rasterio.errors.RasterioIOError, KeyError, TypeError) as e:
        print(f"erro: {e}", file=sys.stderr)
        return 1
    for k, v in report.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
