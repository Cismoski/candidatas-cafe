"""Índices espectrais. Entradas e saídas em float32; NaN propaga NoData."""

import numpy as np
import numpy.typing as npt
from scipy import ndimage

F32 = npt.NDArray[np.float32]


def _normalized_difference(a: F32, b: F32) -> F32:
    num = a - b
    den = a + b
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(den != 0, num / den, np.nan)
    return out.astype(np.float32)


def ndvi(nir: F32, red: F32) -> F32:
    """Rouse et al. (1974): (NIR - R) / (NIR + R)."""
    return _normalized_difference(nir, red)


def ndwi(green: F32, nir: F32) -> F32:
    """McFeeters (1996): (G - NIR) / (G + NIR). Positivo indica água."""
    return _normalized_difference(green, nir)


def savi(nir: F32, red: F32, l: float) -> F32:  # noqa: E741 (nome da literatura)
    """Huete (1988): (1 + L)(NIR - R) / (NIR + R + L)."""
    den = nir + red + np.float32(l)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(den != 0, (1 + l) * (nir - red) / den, np.nan)
    return out.astype(np.float32)


def local_std(x: F32, window: int) -> F32:
    """Desvio-padrão local (textura) ignorando NaN.

    Café em linhas (espaçamento ~3-4 m) não é resolvido a 10 m, mas mistura
    planta e entrelinha e gera variação local maior que um dossel fechado.
    """
    valid = np.isfinite(x)
    filled = np.where(valid, x, 0).astype(np.float64)
    w = valid.astype(np.float64)
    n = ndimage.uniform_filter(w, window, mode="constant")
    s1 = ndimage.uniform_filter(filled, window, mode="constant")
    s2 = ndimage.uniform_filter(filled * filled, window, mode="constant")
    with np.errstate(divide="ignore", invalid="ignore"):
        mean = s1 / n
        var = np.maximum(s2 / n - mean * mean, 0)
    out = np.sqrt(var)
    out[~valid] = np.nan
    return out.astype(np.float32)
