"""Orquestra o processamento de uma análise e grava os produtos em out_dir.

Produtos (nomes fixos, gerados pelo servidor):
  summary.json          resumo usado pela UI e como ÚNICO contexto do chatbot
  candidatas.geojson    polígonos em EPSG:4326 (RFC 7946)
  classes.tif           GeoTIFF (COG) classificado, CRS original
  classificacao.png     cor verdadeira + polígonos + legenda (download)
  overlay_rgb.png       cor verdadeira em EPSG:3857 (mapa)
  overlay_classes.png   classes em EPSG:3857 (mapa)
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import numpy.typing as npt
from scipy import ndimage

from . import indices
from .classify import CLASS_LABELS_PT, Classification, LandClass, classify
from .config import ClassificationConfig
from .reading import Scene, read_scene, read_scene_on_grid, read_scl_on_grid
from .render import write_classes_geotiff, write_download_png, write_map_overlays
from .vectorize import feature_collection, polygons_from_labels, to_wgs84

SUMMARY_SCHEMA_VERSION = 1

LIMITATIONS = [
    "Resultado são ÁREAS CANDIDATAS, não uma classificação validada de café: "
    "não há verdade de campo nem amostras rotuladas, logo nenhuma acurácia é informada.",
    "Outras culturas perenes ou semiperenes com vigor intermediário (ex.: citros, "
    "pastagem bem manejada, cana em certos estágios) podem ser confundidas com café.",
    "Bordas de mata e mata ciliar geram pixels mistos de NDVI intermediário; "
    "um buffer em torno do dossel fechado reduz, mas não elimina, esse erro.",
    "Resolução de 10 m: talhões menores que a área mínima e linhas de plantio não são resolvidos.",
    "Limiares derivados desta região e época (estação seca, sul de MG); "
    "outras regiões ou datas podem exigir ajuste da configuração.",
]


def _stats(values: npt.NDArray[np.float32]) -> dict | None:
    v = values[np.isfinite(values)]
    if v.size == 0:
        return None
    p = np.percentile(v, [5, 25, 50, 75, 95])
    return {
        "n_pixels": int(v.size),
        "mean": round(float(v.mean()), 4),
        "p05": round(float(p[0]), 4),
        "p25": round(float(p[1]), 4),
        "median": round(float(p[2]), 4),
        "p75": round(float(p[3]), 4),
        "p95": round(float(p[4]), 4),
    }


def _per_label_mean(
    values: npt.NDArray[np.float32], labels: npt.NDArray[np.int32], ids: list[int]
) -> dict[int, float | None]:
    finite = np.isfinite(values)
    sums = ndimage.sum_labels(np.where(finite, values, 0), labels, ids)
    counts = ndimage.sum_labels(finite, labels, ids)
    return {
        i: (round(float(s / c), 4) if c else None)
        for i, s, c in zip(ids, np.atleast_1d(sums), np.atleast_1d(counts), strict=True)
    }


def _scene_info(scene: Scene) -> dict:
    g = scene.grid
    return {
        "acquired_utc": scene.acquired_utc,
        "source_item": scene.source_item,
        "crs": g.crs.to_string(),
        "width": g.width,
        "height": g.height,
        "pixel_size_m": round(abs(g.transform.a), 3),
        "radiometry": scene.radiometry_source,
    }


def run_analysis(
    primary_path: Path,
    out_dir: Path,
    cfg: ClassificationConfig,
    *,
    scl_path: Path | None = None,
    secondary_path: Path | None = None,
    acquired_utc_override: str | None = None,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    scene = read_scene(primary_path, cfg)
    if acquired_utc_override and not scene.acquired_utc:
        scene.acquired_utc = acquired_utc_override
    grid = scene.grid

    ndvi = indices.ndvi(scene.nir, scene.red)
    ndwi = indices.ndwi(scene.green, scene.nir)
    savi = indices.savi(scene.nir, scene.red, cfg.indices.savi_l)
    texture = indices.local_std(ndvi, cfg.indices.texture_window)

    quality_ok = None
    if scl_path is not None:
        scl = read_scl_on_grid(scl_path, grid)
        quality_ok = np.isin(scl, cfg.scl.keep_classes)

    other_scene, other_ndvi = None, None
    if secondary_path is not None:
        other_scene = read_scene_on_grid(secondary_path, grid, cfg)
        other_ndvi = indices.ndvi(other_scene.nir, other_scene.red)

    result: Classification = classify(
        ndvi=ndvi,
        ndwi=ndwi,
        valid=scene.valid,
        quality_ok=quality_ok,
        other_ndvi=other_ndvi,
        pixel_area_m2=grid.pixel_area_m2,
        cfg=cfg,
    )

    polygons = polygons_from_labels(result.labels, grid, cfg.vector.simplify_tolerance_m)
    ids = [p.id for p in polygons]
    means = {
        "ndvi_mean": _per_label_mean(ndvi, result.labels, ids),
        "ndwi_mean": _per_label_mean(ndwi, result.labels, ids),
        "savi_mean": _per_label_mean(savi, result.labels, ids),
        "texture_mean": _per_label_mean(texture, result.labels, ids),
    }
    if other_ndvi is not None:
        means["ndvi_other_date_mean"] = _per_label_mean(other_ndvi, result.labels, ids)

    props: dict[int, dict] = {}
    for p in polygons:
        c = to_wgs84(p.geometry_projected.centroid, grid)
        props[p.id] = {
            "id": p.id,
            "area_ha": round(p.area_ha, 4),
            **{k: v[p.id] for k, v in means.items()},
            "centroid_lon": round(c.x, 6),
            "centroid_lat": round(c.y, 6),
            "classe": "candidata_cafe",
        }

    pixel_ha = grid.pixel_area_m2 / 10_000
    counts = np.bincount(result.classes.ravel(), minlength=len(LandClass))
    class_areas = {
        c.name.lower(): {
            "label": CLASS_LABELS_PT[c],
            "area_ha": round(float(counts[c] * pixel_ha), 4),
        }
        for c in LandClass
    }
    total_ha = sum(p.area_ha for p in polygons)
    analysed_ha = float((result.classes != LandClass.NODATA).sum() * pixel_ha)
    candidate = result.classes == LandClass.CANDIDATE
    land = np.isin(
        result.classes,
        [
            LandClass.LOW_VEGETATION,
            LandClass.DENSE_CANOPY,
            LandClass.DISCARDED,
            LandClass.CANDIDATE,
        ],
    )

    year = (scene.acquired_utc or "")[:4] or str(datetime.now(UTC).year)
    attribution = f"Contains modified Copernicus Sentinel data ({year})"
    mode = "temporal" if other_scene is not None else "single_date"
    date_label = (scene.acquired_utc or "data desconhecida")[:10]

    fc = feature_collection(polygons, props, grid)
    (out_dir / "candidatas.geojson").write_text(json.dumps(fc, ensure_ascii=False), "utf-8")
    write_classes_geotiff(
        result.classes, grid, out_dir / "classes.tif", {"ATTRIBUTION": attribution, "MODE": mode}
    )
    write_download_png(
        scene,
        polygons,
        out_dir / "classificacao.png",
        title=f"Áreas candidatas a café — {date_label} — {total_ha:.2f} ha",
        footer=f"{attribution}. Áreas potenciais, sem validação de campo.",
    )
    overlay = write_map_overlays(scene, result.classes, out_dir)

    summary = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "generated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "inputs": {
            "primary": _scene_info(scene),
            "secondary": _scene_info(other_scene) if other_scene else None,
            "scl_used": scl_path is not None,
        },
        "method": {
            "mode": mode,
            "description": (
                "Regras espectrais explicáveis: reflectância (DN*scale+offset, uma vez) -> "
                "NDVI, NDWI (McFeeters) e SAVI -> máscara SCL -> exclusão de água, "
                "solo/vegetação rala e dossel fechado (limiar de Otsu) com buffer -> "
                + ("estabilidade do NDVI entre as duas datas -> " if other_scene else "")
                + "morfologia e área mínima -> polígonos (área em metros no CRS da cena)."
            ),
            "parameters": cfg.model_dump(),
            "dense_canopy_ndvi_threshold": round(result.dense_threshold, 4),
            "dense_canopy_threshold_source": result.dense_threshold_source,
        },
        "results": {
            "candidate_polygons": len(polygons),
            "candidate_area_ha": round(total_ha, 4),
            "analysed_area_ha": round(analysed_ha, 4),
            "candidate_fraction_of_analysed": round(total_ha / analysed_ha, 4)
            if analysed_ha
            else 0,
            "temporal_unverified_ha": round(result.temporal_unverified_px * pixel_ha, 4),
            "class_areas": class_areas,
            "index_stats": {
                name: {"analysed_land": _stats(arr[land]), "candidates": _stats(arr[candidate])}
                for name, arr in (
                    ("ndvi", ndvi),
                    ("ndwi", ndwi),
                    ("savi", savi),
                    ("texture", texture),
                )
            },
            "polygons": [props[i] for i in ids],
        },
        "map": {"overlay_crs": "EPSG:3857", **overlay},
        "limitations": LIMITATIONS
        + ([] if scl_path else ["Sem SCL: nuvens e sombras não foram mascaradas explicitamente."])
        + (
            [] if other_scene else ["Sem segunda data: a estabilidade temporal não foi verificada."]
        ),
        "attribution": attribution,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), "utf-8"
    )
    return summary
