"""Comparação com o MapBiomas (referência independente, NÃO verdade de campo).

O MapBiomas Coleção 11 tem a classe Café (46) a 30 m, em EPSG:4326, num COG
público por ano (CC BY 4.0). Lemos só a janela da análise, reprojetada para a
grade da cena por vizinho mais próximo, e medimos a CONCORDÂNCIA:
- IoU entre nossas candidatas e o café do MapBiomas;
- quanto das candidatas cai sobre o café dele e vice-versa;
- em que classes do MapBiomas caem nossas candidatas.

Nada disso é acurácia: o MapBiomas é outro mapa, com erros próprios, a 30 m.
Falha de rede ou área fora do Brasil não derruba a análise: o resultado diz
que a referência ficou indisponível.
"""

import logging
import threading

import numpy as np
import numpy.typing as npt
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject

from .classify import CLASS_LABELS_PT, LandClass
from .reading import Grid

log = logging.getLogger("cafe.reference")

MAPBIOMAS_URL = (
    "https://storage.googleapis.com/mapbiomas-public/initiatives/brasil/collection11/"
    "lulc/coverage/brazil_coverage/brazil_coverage-col11_{year}.tif"
)
FIRST_YEAR, LAST_YEAR = 1985, 2025
COFFEE = 46
SOURCE = "MapBiomas Coleção 11, cobertura e uso da terra (30 m)"
LICENSE = "CC BY 4.0"
INFO_URL = "https://brasil.mapbiomas.org/downloads/mapas-para-download-geotiff/"
CITATION = "Souza Jr. et al. (2020), Remote Sensing 12(17):2735, doi:10.3390/rs12172735"

# Legenda da Coleção 11 (só os códigos que podem aparecer em MG; resto vira "classe N")
LABELS = {
    3: "Formação florestal",
    4: "Formação savânica",
    9: "Silvicultura",
    11: "Campo alagado e área pantanosa",
    12: "Formação campestre",
    15: "Pastagem",
    20: "Cana",
    21: "Mosaico de usos",
    23: "Praia, duna e areal",
    24: "Área urbanizada",
    25: "Outras áreas não vegetadas",
    29: "Afloramento rochoso",
    30: "Mineração",
    33: "Rio, lago e oceano",
    39: "Soja",
    40: "Arroz",
    41: "Outras lavouras temporárias",
    46: "Café",
    47: "Citrus",
    48: "Outras lavouras perenes",
    62: "Algodão",
    # códigos novos ou menos comuns da Coleção 11 que podem aparecer em MG
    5: "Mangue",
    6: "Floresta alagável",
    19: "Lavoura temporária",
    31: "Aquicultura",
    36: "Lavoura perene",
    75: "Usina fotovoltaica",
    77: "Formação herbáceo-arbustiva",
    91: "Parque eólico",
}
# Os timeouts do GDAL valem por requisição e somam (abrir o COG faz várias;
# com retry, o padrão de espera é 30 s). Por isso: sem retry, conexão lenta
# aborta, e a leitura inteira tem um orçamento próprio (READ_BUDGET_S).
GDAL_ENV = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif",
    "GDAL_HTTP_TIMEOUT": "10",
    "GDAL_HTTP_CONNECTTIMEOUT": "5",
    "GDAL_HTTP_MAX_RETRY": "0",
    "GDAL_HTTP_LOW_SPEED_LIMIT": "1024",  # bytes/s
    "GDAL_HTTP_LOW_SPEED_TIME": "5",
}
# Leitura medida: ~4 s. Acima disso a análise segue sem a referência.
READ_BUDGET_S = 30.0


def reference_year(acquired_utc: str | None) -> int:
    """Ano do MapBiomas mais próximo da data da imagem (o mapa é anual)."""
    try:
        year = int((acquired_utc or "")[:4])
    except ValueError:
        return LAST_YEAR
    return min(max(year, FIRST_YEAR), LAST_YEAR)


def _open_path(url: str) -> str:
    return f"/vsicurl/{url}" if url.startswith(("http://", "https://")) else url


def read_on_grid(url: str, grid: Grid) -> npt.NDArray[np.uint8]:
    out = np.zeros((grid.height, grid.width), dtype=np.uint8)
    with rasterio.Env(**GDAL_ENV), rasterio.open(_open_path(url)) as src:
        reproject(
            source=rasterio.band(src, 1),
            destination=out,
            dst_transform=grid.transform,
            dst_crs=grid.crs,
            resampling=Resampling.nearest,
            dst_nodata=0,
        )
    return out


def read_with_budget(url: str, grid: Grid, budget_s: float) -> npt.NDArray[np.uint8]:
    """read_on_grid com teto de tempo total. A thread que estourar é abandonada
    (daemon): o job roda num subprocesso que termina logo depois."""
    box: dict = {}

    def work():
        try:
            box["data"] = read_on_grid(url, grid)
        except BaseException as e:  # noqa: BLE001 - repassado abaixo
            box["error"] = e

    t = threading.Thread(target=work, daemon=True, name="mapbiomas")
    t.start()
    t.join(budget_s)
    if t.is_alive():
        raise TimeoutError(f"MapBiomas não respondeu em {budget_s:g} s")
    if "error" in box:
        raise box["error"]
    return box["data"]


def _label(code: int) -> str:
    return LABELS.get(code, f"classe {code}")


def _share(values: npt.NDArray, names) -> dict[str, float]:
    """Fração de cada valor, maior primeiro (até 6 entradas)."""
    if values.size == 0:
        return {}
    codes, counts = np.unique(values, return_counts=True)
    order = np.argsort(-counts)[:6]
    return {names(int(codes[i])): round(float(counts[i] / values.size), 4) for i in order}


def compare(mb: npt.NDArray[np.uint8], classes: npt.NDArray[np.uint8], pixel_ha: float) -> dict:
    """Métricas de concordância onde os dois mapas têm dado."""
    both = (mb > 0) & (classes != LandClass.NODATA) & (classes != LandClass.MASKED_QUALITY)
    ours = both & (classes == LandClass.CANDIDATE)
    theirs = both & (mb == COFFEE)
    inter, union = int((ours & theirs).sum()), int((ours | theirs).sum())
    n_ours, n_theirs = int(ours.sum()), int(theirs.sum())
    return {
        "compared_area_ha": round(float(both.sum()) * pixel_ha, 2),
        "reference_coffee_ha": round(n_theirs * pixel_ha, 2),
        "candidate_ha": round(n_ours * pixel_ha, 2),
        "intersection_ha": round(inter * pixel_ha, 2),
        "iou": round(inter / union, 4) if union else None,
        # fração das nossas candidatas que o MapBiomas chama de café
        "candidates_on_reference_coffee": round(inter / n_ours, 4) if n_ours else None,
        # fração do café do MapBiomas que marcamos como candidata
        "reference_coffee_in_candidates": round(inter / n_theirs, 4) if n_theirs else None,
        "candidates_by_reference_class": _share(mb[ours], _label),
        "reference_coffee_by_our_class": _share(
            classes[theirs], lambda c: CLASS_LABELS_PT[LandClass(c)]
        ),
    }


def unavailable(meta: dict, reason: str) -> dict:
    return {**meta, "status": "unavailable", "reason": reason}


def metadata(acquired_utc: str | None) -> dict:
    return {
        "source": SOURCE,
        "year": reference_year(acquired_utc),
        "license": LICENSE,
        "info_url": INFO_URL,
        "citation": CITATION,
        "note": "Concordância com outro mapa (30 m, reamostrado por vizinho mais próximo), "
        "não acurácia.",
    }


def mapbiomas_reference(
    url_template: str,
    grid: Grid,
    classes: npt.NDArray[np.uint8],
    acquired_utc: str | None,
    budget_s: float = READ_BUDGET_S,
) -> tuple[dict, npt.NDArray[np.bool_] | None]:
    """(bloco do summary, máscara de café do MapBiomas na grade ou None)."""
    meta = metadata(acquired_utc)
    year = meta["year"]
    try:
        mb = read_with_budget(url_template.format(year=year), grid, budget_s)
    except Exception as e:  # rede, 404, timeout, arquivo inválido
        log.warning("MapBiomas indisponível: %s", type(e).__name__)
        reason = (
            "o MapBiomas demorou demais para responder"
            if isinstance(e, TimeoutError)
            else "não foi possível ler o MapBiomas"
        )
        return unavailable(meta, reason), None
    if not (mb > 0).any():
        return {
            **meta,
            "status": "no_coverage",
            "reason": "área fora da cobertura do MapBiomas",
        }, None
    pixel_ha = grid.pixel_area_m2 / 10_000
    return {**meta, "status": "ok", **compare(mb, classes, pixel_ha)}, mb == COFFEE
