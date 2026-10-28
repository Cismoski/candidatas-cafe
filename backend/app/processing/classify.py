"""Regras de classificação de áreas CANDIDATAS a café.

Isto não é uma classificação validada de café: é um filtro por regras que
separa vegetação com vigor intermediário e persistente (compatível com café)
de solo/pastagem seca, água e dossel fechado (mata/eucalipto).
"""

from dataclasses import dataclass
from enum import IntEnum

import numpy as np
import numpy.typing as npt
from scipy import ndimage

from .config import ClassificationConfig

F32 = npt.NDArray[np.float32]
Mask = npt.NDArray[np.bool_]

# Vizinhança 3x3 completa (8-conectividade), usada em toda a morfologia e rotulagem.
EIGHT = np.ones((3, 3), dtype=bool)
MIN_PIXELS_FOR_OTSU = 500


class LandClass(IntEnum):
    NODATA = 0
    MASKED_QUALITY = 1  # excluído pela SCL (sombra, nuvem, não vegetado...)
    WATER = 2
    LOW_VEGETATION = 3  # solo exposto, pastagem seca, área urbana
    DENSE_CANOPY = 4  # mata, eucalipto, dossel fechado
    DISCARDED = 5  # vigor intermediário, mas descartado (borda, temporal, área mínima)
    CANDIDATE = 6


CLASS_LABELS_PT = {
    LandClass.NODATA: "Sem dado",
    LandClass.MASKED_QUALITY: "Excluído pela máscara de qualidade (SCL)",
    LandClass.WATER: "Água / alta umidade",
    LandClass.LOW_VEGETATION: "Solo exposto ou vegetação rala",
    LandClass.DENSE_CANOPY: "Dossel fechado (mata/eucalipto)",
    LandClass.DISCARDED: "Vegetação intermediária descartada",
    LandClass.CANDIDATE: "Candidata a café",
}


@dataclass
class Classification:
    classes: npt.NDArray[np.uint8]
    labels: npt.NDArray[np.int32]  # rótulo do componente candidato (0 = fora)
    n_components: int
    dense_threshold: float
    dense_threshold_source: str
    temporal_unverified_px: int  # candidatos sem dado válido na segunda data


def otsu_threshold(values: F32, lo: float, hi: float, bins: int = 256) -> float:
    """Limiar de Otsu (1979): maximiza a variância entre as duas classes."""
    hist, edges = np.histogram(values, bins=bins, range=(lo, hi))
    centers = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist).astype(np.float64)
    w1 = w0[-1] - w0
    m0 = np.cumsum(hist * centers)
    mu0 = np.divide(m0, w0, out=np.zeros_like(m0), where=w0 > 0)
    mu1 = np.divide(m0[-1] - m0, w1, out=np.zeros_like(m0), where=w1 > 0)
    between = w0 * w1 * (mu0 - mu1) ** 2
    # Bins vazios entre as modas criam um platô de máximos; usa o meio dele em vez
    # do primeiro ponto (que colaria o limiar na moda inferior).
    ties = np.flatnonzero(between >= between.max() * (1 - 1e-9))
    return float((edges[ties[0] + 1] + edges[ties[-1] + 1]) / 2)


def dense_canopy_threshold(
    ndvi: F32, vegetated: Mask, cfg: ClassificationConfig
) -> tuple[float, str]:
    r = cfg.rules
    sample = ndvi[vegetated & (ndvi >= r.ndvi_min)]
    if sample.size < MIN_PIXELS_FOR_OTSU:
        return r.dense_ndvi_default, "padrão (poucos pixels de vegetação para Otsu)"
    t = otsu_threshold(sample, r.ndvi_min, 1.0)
    if r.dense_ndvi_floor <= t <= r.dense_ndvi_ceiling:
        return t, "Otsu sobre o NDVI da vegetação"
    return r.dense_ndvi_default, f"padrão (Otsu={t:.3f} fora de [floor, ceiling])"


def _min_pixels(area_ha: float, pixel_area_m2: float) -> int:
    return max(int(np.ceil(area_ha * 10_000 / pixel_area_m2 - 1e-9)), 1)


def _morph(op, mask: Mask, iterations: int) -> Mask:
    """Abertura/fechamento com a borda replicada.

    O scipy trata o lado de fora da imagem como fundo, o que faria um talhão
    encostado na borda do recorte perder a fileira da borda.
    """
    if iterations == 0:
        return mask
    padded = np.pad(mask, iterations, mode="edge")
    out = op(padded, structure=EIGHT, iterations=iterations)
    return out[iterations:-iterations, iterations:-iterations]


def remove_small(mask: Mask, min_pixels: int) -> tuple[npt.NDArray[np.int32], int]:
    """Rotula componentes 8-conexos e remove os menores que min_pixels."""
    labels, n = ndimage.label(mask, structure=EIGHT)
    if n == 0:
        return labels.astype(np.int32), 0
    sizes = np.bincount(labels.ravel())
    keep = sizes >= min_pixels
    keep[0] = False
    kept = keep[labels]
    labels, n = ndimage.label(kept, structure=EIGHT)
    return labels.astype(np.int32), int(n)


def classify(
    *,
    ndvi: F32,
    ndwi: F32,
    valid: Mask,
    quality_ok: Mask | None,
    other_ndvi: F32 | None,
    pixel_area_m2: float,
    cfg: ClassificationConfig,
) -> Classification:
    r, t, m = cfg.rules, cfg.temporal, cfg.morphology
    classes = np.full(ndvi.shape, LandClass.NODATA, dtype=np.uint8)

    usable = valid & np.isfinite(ndvi) & np.isfinite(ndwi)
    quality = usable if quality_ok is None else usable & quality_ok
    classes[usable & ~quality] = LandClass.MASKED_QUALITY

    # Limiares comparados em float32, o mesmo tipo dos índices: float32(0.45) < 0.45
    # em float64, e um pixel exatamente no limiar cairia do lado errado.
    ndvi_min, ndwi_max = np.float32(r.ndvi_min), np.float32(r.ndwi_max)
    water = quality & (ndwi > ndwi_max)
    land = quality & ~water
    classes[water] = LandClass.WATER

    threshold, source = dense_canopy_threshold(ndvi, land, cfg)
    dense_t = np.float32(threshold)
    low = land & (ndvi < ndvi_min)
    dense = land & (ndvi >= dense_t)
    intermediate = land & ~low & ~dense
    classes[low] = LandClass.LOW_VEGETATION
    classes[dense] = LandClass.DENSE_CANOPY

    # Núcleo de mata: manchas de dossel fechado >= dense_core_min_area_ha. A faixa
    # de dense_buffer_px em volta é descartada porque pixels mistos de borda e de
    # mata ciliar têm NDVI intermediário. Manchas pequenas (um pé vigoroso no
    # meio do talhão) não geram buffer.
    core_labels, _ = remove_small(dense, _min_pixels(r.dense_core_min_area_ha, pixel_area_m2))
    core = core_labels > 0
    if r.dense_buffer_px > 0 and core.any():
        near_core = ndimage.binary_dilation(core, structure=EIGHT, iterations=r.dense_buffer_px)
    else:
        near_core = np.zeros_like(core)
    candidate = intermediate & ~near_core

    other_ok = None
    if other_ndvi is not None:
        other_ok = np.isfinite(other_ndvi)
        persistent = (
            (other_ndvi >= np.float32(t.ndvi_min_other))
            & (other_ndvi < dense_t)
            & (np.abs(other_ndvi - ndvi) <= np.float32(t.max_abs_ndvi_change))
        )
        # Sem dado na segunda data (nuvem mascarada) => a regra não se aplica.
        candidate &= persistent | ~other_ok

    candidate = _morph(ndimage.binary_opening, candidate, m.opening_iterations)
    candidate = _morph(ndimage.binary_closing, candidate, m.closing_iterations)
    # O fechamento pode preencher pixels que não são intermediários (ex.: um pixel
    # de NoData ou de mata dentro do talhão); eles nunca podem virar candidatos.
    candidate &= intermediate

    labels, n = remove_small(candidate, _min_pixels(m.min_area_ha, pixel_area_m2))
    final = labels > 0

    classes[intermediate & ~final] = LandClass.DISCARDED
    classes[final] = LandClass.CANDIDATE
    return Classification(
        classes=classes,
        labels=labels,
        n_components=n,
        dense_threshold=threshold,
        dense_threshold_source=source,
        temporal_unverified_px=0 if other_ok is None else int((final & ~other_ok).sum()),
    )
