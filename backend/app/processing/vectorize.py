"""Raster de componentes -> polígonos com área (CRS projetado) e GeoJSON em EPSG:4326."""

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import shapely
from pyproj import Transformer
from rasterio import features
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from .reading import Grid

GEOJSON_DECIMALS = 6  # ~0,1 m: RFC 7946 recomenda não exceder a precisão útil


@dataclass
class CandidatePolygon:
    id: int
    geometry_projected: shapely.Geometry  # exata (bordas de pixel), CRS da cena
    geometry_display: shapely.Geometry  # simplificada, CRS da cena
    area_ha: float


def polygons_from_labels(
    labels: npt.NDArray[np.int32], grid: Grid, simplify_tolerance_m: float
) -> list[CandidatePolygon]:
    """Um polígono (ou multipolígono) por componente rotulado.

    A área vem da geometria exata em metros (CRS projetado da cena), que é
    igual a n_pixels * área do pixel. A simplificação serve só para exibição.
    """
    if labels.max(initial=0) == 0:
        return []
    parts: dict[int, list[shapely.Geometry]] = {}
    for geom, value in features.shapes(
        labels, mask=labels > 0, transform=grid.transform, connectivity=8
    ):
        parts.setdefault(int(value), []).append(shape(geom))
    out = []
    for label in sorted(parts):
        exact = unary_union(parts[label])
        display = exact.simplify(simplify_tolerance_m, preserve_topology=True)
        out.append(CandidatePolygon(label, exact, display, exact.area / 10_000))
    return out


def to_wgs84(geom: shapely.Geometry, grid: Grid) -> shapely.Geometry:
    tr = Transformer.from_crs(grid.crs, "EPSG:4326", always_xy=True)
    return shapely.transform(geom, lambda xy: np.column_stack(tr.transform(xy[:, 0], xy[:, 1])))


def _round_coords(obj):
    if isinstance(obj, (list, tuple)):
        if obj and isinstance(obj[0], float):
            return [round(c, GEOJSON_DECIMALS) for c in obj]
        return [_round_coords(o) for o in obj]
    return obj


def feature_collection(
    polygons: list[CandidatePolygon], properties: dict[int, dict], grid: Grid
) -> dict:
    """GeoJSON RFC 7946: WGS84 lon/lat, anel externo anti-horário."""
    feats = []
    for p in polygons:
        geom = shapely.orient_polygons(to_wgs84(p.geometry_display, grid))
        gj = mapping(geom)
        feats.append(
            {
                "type": "Feature",
                "id": p.id,
                "properties": properties[p.id],
                "geometry": {"type": gj["type"], "coordinates": _round_coords(gj["coordinates"])},
            }
        )
    return {"type": "FeatureCollection", "features": feats}
