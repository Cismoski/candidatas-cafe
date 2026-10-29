"""Sensibilidade da regra temporal: variantes medidas contra o café do MapBiomas.

Uso (da raiz do repositório; baixa só a janela do MapBiomas, ~30 s):
    uv run --project backend python scripts/sensibilidade_temporal.py

Roda o pipeline do app (mesma configuração) nas amostras de ago/2025 e
fev/2025 e troca só a regra temporal. As variantes "mata" não usam rótulos: a
referência de cultura perene é o próprio núcleo de mata da cena (dossel
fechado >= 0,5 ha, erodido 2 px), válido nas duas datas.

Imprime, por variante: área candidata, IoU, precisão e revocação contra a
classe 46 (Café) do MapBiomas 2025, e o IoU nas metades oeste/leste. O IoU de
acaso é o de uma máscara com a mesma área espalhada ao acaso. Concordância com
outro mapa de 30 m, não acurácia.
"""

import sys
from pathlib import Path

import numpy as np
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.processing import indices  # noqa: E402
from app.processing.classify import (  # noqa: E402
    EIGHT,
    LandClass,
    _min_pixels,
    _opening,
    classify,
    remove_small,
)
from app.processing.config import load_config  # noqa: E402
from app.processing.reading import (  # noqa: E402
    read_scene,
    read_scene_on_grid,
    read_scl_on_grid,
)
from app.processing.reference import read_on_grid  # noqa: E402
from app.settings import Settings  # noqa: E402

AMOSTRA = ROOT / "frontend/public/amostra"
COFFEE = 46


def main() -> None:
    cfg = load_config()
    main_scene = read_scene(AMOSTRA / "imagem_multiespectral.tif", cfg)
    grid = main_scene.grid
    other = read_scene_on_grid(AMOSTRA / "s2b_20250217_segunda_data.tif", grid, cfg)
    scl = read_scl_on_grid(AMOSTRA / "qualidade_scl.tif", grid)
    quality = np.isin(scl, cfg.scl.keep_classes)

    ndvi = indices.ndvi(main_scene.nir, main_scene.red)
    ndwi = indices.ndwi(main_scene.green, main_scene.nir)
    other_ndvi = indices.ndvi(other.nir, other.red)
    other_ndvi[~(other.valid & (other.blue < cfg.temporal.cloud_blue_min))] = np.nan

    def run(other_ndvi_or_none, **temporal):
        c = cfg.model_copy(deep=True)
        for k, v in temporal.items():
            setattr(c.temporal, k, v)
        return classify(
            ndvi=ndvi,
            ndwi=ndwi,
            valid=main_scene.valid,
            quality_ok=quality,
            other_ndvi=other_ndvi_or_none,
            pixel_area_m2=grid.pixel_area_m2,
            cfg=c,
        )

    single = run(None)
    url = Settings.model_fields["mapbiomas_url"].default.format(year=2025)
    mb = read_on_grid(url, grid)
    compared = (mb > 0) & (single.classes > LandClass.MASKED_QUALITY)
    coffee = (mb == COFFEE) & compared
    px_ha = grid.pixel_area_m2 / 1e4
    half = grid.width // 2

    def iou(a, b):
        return (a & b).sum() / max((a | b).sum(), 1)

    def report(name, cand):
        c = cand & compared
        inter = (c & coffee).sum()
        west = iou(c[:, :half], coffee[:, :half])
        east = iou(c[:, half:], coffee[:, half:])
        p = c.sum() / compared.sum()
        chance = p * coffee.sum() / (c.sum() + coffee.sum() - p * coffee.sum())
        print(
            f"{name:44s} {c.sum() * px_ha:7.1f} ha  IoU {iou(c, coffee):.3f}"
            f"  (acaso {chance:.3f})  prec {inter / max(c.sum(), 1):.3f}"
            f"  rev {inter / coffee.sum():.3f}  oeste/leste {west:.3f}/{east:.3f}"
        )

    print(f"Café MapBiomas na área comparada: {coffee.sum() * px_ha:.1f} ha")
    print(f"Limiar de dossel fechado (Otsu): {single.dense_threshold:.3f}\n")
    report("Uma data (agosto)", single.classes == LandClass.CANDIDATE)
    report(
        "Δ bruto, |Δ| <= 0,25 (regra original)",
        run(other_ndvi, seasonal_normalization=False).classes == LandClass.CANDIDATE,
    )
    current = run(other_ndvi)
    report("|Δ − mediana da cena| <= 0,25 (app)", current.classes == LandClass.CANDIDATE)

    # Referência perene sem rótulos: núcleos de mata, válidos nas duas datas
    dense = single.classes == LandClass.DENSE_CANOPY
    core_labels, _ = remove_small(
        dense, _min_pixels(cfg.rules.dense_core_min_area_ha, grid.pixel_area_m2)
    )
    delta = other_ndvi - ndvi
    forest = ndimage.binary_erosion(core_labels > 0, EIGHT, 2) & np.isfinite(delta)
    p5, p50, p95 = np.percentile(delta[forest], [5, 50, 95])
    veg_shift = current.temporal_ndvi_shift
    print(
        f"\nΔ da mata: p5 {p5:+.3f}  mediana {p50:+.3f}  p95 {p95:+.3f}"
        f"  ({forest.sum()} px); mediana da vegetação: {veg_shift:+.3f}"
    )

    # Mesmo pré-filtro do app (intermediário, fora da faixa da mata) antes da regra
    pre = run(None)
    intermediate = (pre.classes == LandClass.CANDIDATE) | (pre.classes == LandClass.DISCARDED)
    near_core = ndimage.binary_dilation(core_labels > 0, EIGHT, cfg.rules.dense_buffer_px)
    base = intermediate & ~near_core
    unknown = ~np.isfinite(other_ndvi)
    green = other_ndvi >= cfg.temporal.ndvi_min_other
    min_px = _min_pixels(cfg.morphology.min_area_ha, grid.pixel_area_m2)

    def finish(mask):
        labels, _ = remove_small(_opening(mask, cfg.morphology.opening_iterations), min_px)
        return labels > 0

    report(
        "Δ dentro de p5–p95 da mata",
        finish(base & ((green & (delta >= p5) & (delta <= p95)) | unknown)),
    )
    report(
        "|Δ − mediana da mata| <= 0,075",
        finish(base & ((green & (np.abs(delta - p50) <= 0.075)) | unknown)),
    )

    # Textura: café (linhas, entrelinha) é mais rugoso que a mata na chuva
    rough = indices.local_std(other_ndvi, cfg.indices.texture_window)
    forest_rough = float(np.nanmedian(rough[forest]))
    land = quality & main_scene.valid & (ndwi <= cfg.rules.ndwi_max)
    textured = (
        land
        & (ndvi >= cfg.rules.ndvi_min)
        & (ndvi < 0.85)
        & green
        & (np.abs(delta - veg_shift) <= 0.15)
        & (rough > 2 * forest_rough)
    )
    report("Perene (±0,15) + rugoso (> 2× mata), sem Otsu", finish(textured))
    on_forest = (finish(textured) & compared & (mb == 3)).sum() / max(
        (finish(textured) & compared).sum(), 1
    )
    print(f"  ↳ fração sobre formação florestal do MapBiomas: {on_forest:.2f}")


if __name__ == "__main__":
    main()
