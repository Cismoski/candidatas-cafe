"""Produtos visuais: sobreposições para o mapa (EPSG:3857), PNG para download e GeoTIFF."""

from pathlib import Path

import numpy as np
import numpy.typing as npt
from PIL import Image, ImageDraw, ImageFont
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.io import MemoryFile
from rasterio.shutil import copy as rio_copy
from rasterio.warp import calculate_default_transform, reproject

from .classify import CLASS_LABELS_PT, LandClass
from .reading import Grid, Scene
from .vectorize import CandidatePolygon

WEB_MERCATOR = "EPSG:3857"

# Cores RGBA por classe (sobreposição do mapa e GeoTIFF). Fundo transparente.
CLASS_COLORS: dict[LandClass, tuple[int, int, int, int]] = {
    LandClass.NODATA: (0, 0, 0, 0),
    LandClass.MASKED_QUALITY: (120, 120, 120, 140),
    LandClass.WATER: (40, 110, 220, 170),
    LandClass.LOW_VEGETATION: (0, 0, 0, 0),
    LandClass.DENSE_CANOPY: (20, 80, 40, 150),
    LandClass.DISCARDED: (200, 140, 60, 110),
    LandClass.CANDIDATE: (250, 190, 20, 200),
}
OUTLINE = (255, 220, 0)


def true_color(scene: Scene) -> npt.NDArray[np.uint8]:
    """RGB com realce linear 2-98% calculado só sobre pixels válidos."""
    out = np.zeros((*scene.red.shape, 3), dtype=np.uint8)
    if not scene.valid.any():
        return out
    for i, band in enumerate((scene.red, scene.green, scene.blue)):
        lo, hi = np.percentile(band[scene.valid], [2, 98])
        scaled = np.clip((band - lo) / max(hi - lo, 1e-6), 0, 1) * 255
        out[..., i] = np.where(scene.valid, scaled, 0).astype(np.uint8)
    return out


def _warp_to_mercator(
    rgba: npt.NDArray[np.uint8], grid: Grid
) -> tuple[npt.NDArray[np.uint8], list[list[float]]]:
    """Reprojeta RGBA para Web Mercator (nearest) e devolve os 4 cantos em lon/lat.

    O MapLibre desenha uma image source esticando-a linearmente entre os cantos
    em Web Mercator; por isso a imagem precisa estar em EPSG:3857.
    """
    h, w = grid.height, grid.width
    left, top = grid.transform @ (0, 0)
    right, bottom = grid.transform @ (w, h)
    dst_t, dw, dh = calculate_default_transform(
        grid.crs, WEB_MERCATOR, w, h, left, bottom, right, top
    )
    dst = np.zeros((4, dh, dw), dtype=np.uint8)
    for b in range(4):
        reproject(
            source=np.ascontiguousarray(rgba[..., b]),
            destination=dst[b],
            src_transform=grid.transform,
            src_crs=grid.crs,
            dst_transform=dst_t,
            dst_crs=WEB_MERCATOR,
            resampling=Resampling.nearest,
            src_nodata=None,
        )
    to_ll = Transformer.from_crs(WEB_MERCATOR, "EPSG:4326", always_xy=True)
    corners_px = [(0, 0), (dw, 0), (dw, dh), (0, dh)]  # TL, TR, BR, BL (ordem do MapLibre)
    coords = [list(to_ll.transform(*(dst_t @ c))) for c in corners_px]
    return np.moveaxis(dst, 0, -1), [[round(x, 7), round(y, 7)] for x, y in coords]


def write_map_overlays(scene: Scene, classes: npt.NDArray[np.uint8], out_dir: Path) -> dict:
    rgb = true_color(scene)
    rgba = np.dstack([rgb, np.where(scene.valid, 255, 0).astype(np.uint8)])
    img, corners = _warp_to_mercator(rgba, scene.grid)
    Image.fromarray(img, "RGBA").save(out_dir / "overlay_rgb.png", optimize=True)

    lut = np.array([CLASS_COLORS[LandClass(i)] for i in range(len(LandClass))], dtype=np.uint8)
    cls_img, _ = _warp_to_mercator(lut[classes], scene.grid)
    Image.fromarray(cls_img, "RGBA").save(out_dir / "overlay_classes.png", optimize=True)
    return {"coordinates": corners}


# Café do MapBiomas: roxo, distinto do âmbar das candidatas, do azul da água e do verde da mata
REFERENCE_COLOR = (150, 60, 190, 170)


def write_reference_overlay(mask: npt.NDArray[np.bool_], grid: Grid, out_dir: Path) -> None:
    rgba = np.zeros((*mask.shape, 4), dtype=np.uint8)
    rgba[mask] = REFERENCE_COLOR
    img, _ = _warp_to_mercator(rgba, grid)
    Image.fromarray(img, "RGBA").save(out_dir / "overlay_referencia.png", optimize=True)


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default(size)


def write_download_png(
    scene: Scene,
    polygons: list[CandidatePolygon],
    out_path: Path,
    *,
    title: str,
    footer: str,
) -> None:
    """Cor verdadeira + contornos dos polígonos + legenda, na grade original (norte acima)."""
    # Ampliação 2x só em imagens pequenas: o PNG é o maior consumidor de memória.
    upscale = 2 if max(scene.grid.width, scene.grid.height) <= 1024 else 1
    base = Image.fromarray(true_color(scene)).resize(
        (scene.grid.width * upscale, scene.grid.height * upscale), Image.Resampling.NEAREST
    )
    draw = ImageDraw.Draw(base)
    inv = ~scene.grid.transform
    for p in polygons:
        geoms = getattr(p.geometry, "geoms", [p.geometry])
        for g in geoms:
            for ring in [g.exterior, *g.interiors]:
                pts = [tuple(c * upscale for c in inv @ xy) for xy in ring.coords]
                draw.line(pts, fill=OUTLINE, width=2)

    font, small = _font(18), _font(14)
    pad, line_h = 12, 22
    legend = f"{CLASS_LABELS_PT[LandClass.CANDIDATE]} ({len(polygons)} polígonos)"
    panel_h = pad * 2 + line_h * 2 + 18
    canvas = Image.new("RGB", (base.width, base.height + panel_h), (250, 250, 247))
    canvas.paste(base, (0, 0))
    d = ImageDraw.Draw(canvas)
    y = base.height + pad
    d.text((pad, y), title, fill=(20, 20, 20), font=font)
    d.rectangle((pad, y + line_h + 3, pad + 14, y + line_h + 17), outline=OUTLINE, width=3)
    d.text((pad + 22, y + line_h), legend, fill=(20, 20, 20), font=font)
    d.text((pad, y + line_h * 2 + 6), footer, fill=(90, 90, 90), font=small)
    canvas.save(out_path, optimize=True)


def write_classes_geotiff(
    classes: npt.NDArray[np.uint8], grid: Grid, out_path: Path, tags: dict[str, str]
) -> None:
    """GeoTIFF classificado (Cloud Optimized), com paleta e descrição das classes."""
    profile = {
        "driver": "GTiff",
        "dtype": "uint8",
        "count": 1,
        "height": grid.height,
        "width": grid.width,
        "crs": grid.crs,
        "transform": grid.transform,
        "nodata": int(LandClass.NODATA),
    }
    legend = "; ".join(f"{int(c)}={CLASS_LABELS_PT[c]}" for c in LandClass)
    with MemoryFile() as mem:
        with mem.open(**profile) as ds:
            ds.write(classes, 1)
            ds.write_colormap(1, {int(c): CLASS_COLORS[c] for c in LandClass})
            ds.update_tags(CLASSES=legend, **tags)
            ds.set_band_description(1, "classe")
        with mem.open() as src:
            rio_copy(src, out_path, driver="COG", compress="DEFLATE")
