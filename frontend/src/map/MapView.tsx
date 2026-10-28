import "maplibre-gl/dist/maplibre-gl.css";
import type { FeatureCollection } from "geojson";
import {
  type GeoJSONSource,
  type ImageSource,
  type ImageSourceSpecification,
  type LngLatBoundsLike,
  Map as MLMap,
  NavigationControl,
  Popup,
  ScaleControl,
  setWorkerUrl,
} from "maplibre-gl";
// O worker do MapLibre 6 é um arquivo à parte, resolvido por import.meta.url;
// empacotado pelo Vite esse caminho quebra, então o Vite emite o arquivo e
// informamos a URL final (mesma origem: cabe no worker-src 'self' da CSP).
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import { useEffect, useRef, useState } from "react";
import type { LngLat, PolygonStats } from "../api/types";
import { formatHa, formatIndex } from "../lib/format";

/**
 * Mapa MapLibre. Camadas, de baixo para cima:
 *   basemap OpenFreeMap (sem chave) -> cor verdadeira -> classes -> polígonos.
 * As sobreposições são PNGs já reprojetados para EPSG:3857 pelo backend, então
 * a image source só precisa dos 4 cantos; os polígonos chegam em EPSG:4326.
 * Os PNGs vêm de rotas autenticadas: chegam aqui como Blob e viram ImageBitmap
 * (o Bearer não iria numa URL comum).
 */

export const BASEMAP_STYLE = "https://tiles.openfreemap.org/styles/positron";
/** Guaxupé (MG): vista inicial antes de qualquer análise. */
export const DEFAULT_CENTER: LngLat = [-46.71, -21.305];

export interface Layers {
  rgb: boolean;
  classes: boolean;
  polygons: boolean;
}

export interface MapViewProps {
  analysisId: string | null;
  coordinates: [LngLat, LngLat, LngLat, LngLat] | null;
  rgb: Blob | null;
  classes: Blob | null;
  polygons: FeatureCollection | null;
  layers: Layers;
  focusPolygon: number | null;
  onSelectPolygon?: (id: number | null) => void;
  /** Limites da vista [oeste, sul, leste, norte], para a moldura. */
  onViewChange?: (bounds: ViewBounds) => void;
  interactive?: boolean;
}

export type ViewBounds = [number, number, number, number];

setWorkerUrl(workerUrl);

const EMPTY_FC: FeatureCollection = { type: "FeatureCollection", features: [] };
const IMAGE_LAYERS = { rgb: "overlay-rgb", classes: "overlay-classes" } as const;
const POLY = "candidates";

export function MapView(props: MapViewProps) {
  const { analysisId, coordinates, rgb, classes, polygons, layers, focusPolygon } = props;
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const popupRef = useRef<Popup | null>(null);
  const bitmapsRef = useRef<{ rgb?: ImageBitmap; classes?: ImageBitmap }>({});
  const onSelect = useRef(props.onSelectPolygon);
  onSelect.current = props.onSelectPolygon;
  const onView = useRef(props.onViewChange);
  onView.current = props.onViewChange;
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);

  // Criação única do mapa
  useEffect(() => {
    if (!container.current) return;
    let map: MLMap;
    try {
      map = new MLMap({
        container: container.current,
        style: BASEMAP_STYLE,
        center: DEFAULT_CENTER,
        zoom: 12,
        attributionControl: { compact: true },
        interactive: props.interactive ?? true,
        cooperativeGestures: false,
      });
    } catch {
      setFailed(true); // sem WebGL
      return;
    }
    mapRef.current = map;
    if (props.interactive !== false) {
      map.addControl(new NavigationControl({ showCompass: false }), "top-right");
      map.addControl(new ScaleControl({ unit: "metric", maxWidth: 120 }), "bottom-left");
    }
    const emitView = () => {
      const b = map.getBounds();
      onView.current?.([b.getWest(), b.getSouth(), b.getEast(), b.getNorth()]);
    };
    map.on("moveend", emitView);
    map.on("resize", emitView);
    map.on("load", () => {
      emitView();
      map.addSource(POLY, { type: "geojson", data: EMPTY_FC, promoteId: "id" });
      map.addLayer({
        id: `${POLY}-fill`,
        type: "fill",
        source: POLY,
        paint: { "fill-color": "#fabe14", "fill-opacity": 0.18 },
      });
      map.addLayer({
        id: `${POLY}-line`,
        type: "line",
        source: POLY,
        paint: { "line-color": "#ffdc00", "line-width": 1.6 },
      });
      map.addLayer({
        id: `${POLY}-focus`,
        type: "line",
        source: POLY,
        filter: ["==", ["get", "id"], -1],
        paint: { "line-color": "#1e3a2b", "line-width": 3 },
      });
      map.on("click", `${POLY}-fill`, (e) => {
        const f = e.features?.[0];
        if (f) onSelect.current?.(Number(f.properties?.id));
      });
      map.on("mouseenter", `${POLY}-fill`, () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", `${POLY}-fill`, () => {
        map.getCanvas().style.cursor = "";
      });
      setReady(true);
    });
    return () => {
      popupRef.current?.remove();
      map.remove();
      mapRef.current = null;
      bitmapsRef.current.rgb?.close();
      bitmapsRef.current.classes?.close();
      bitmapsRef.current = {};
    };
    // o mapa é criado uma única vez; props.interactive é lida só na montagem
  }, []);

  // Sobreposições raster
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    let cancelled = false;
    const sync = async (kind: keyof typeof IMAGE_LAYERS, blob: Blob | null) => {
      const id = IMAGE_LAYERS[kind];
      if (map.getLayer(id)) map.removeLayer(id);
      if (map.getSource(id)) map.removeSource(id);
      // o bitmap anterior só é liberado depois que nenhuma source o usa
      bitmapsRef.current[kind]?.close();
      bitmapsRef.current[kind] = undefined;
      if (!blob || !coordinates) return;
      const bitmap = await createImageBitmap(blob);
      if (cancelled) return bitmap.close();
      bitmapsRef.current[kind] = bitmap;
      map.addSource(id, { type: "image", coordinates } as ImageSourceSpecification);
      (map.getSource(id) as ImageSource).updateImage({ image: bitmap });
      map.addLayer(
        {
          id,
          type: "raster",
          source: id,
          paint: {
            "raster-opacity": kind === "rgb" ? 1 : 0.85,
            // classes são categóricas: sem interpolação entre cores
            "raster-resampling": kind === "classes" ? "nearest" : "linear",
            "raster-fade-duration": 0,
          },
        },
        `${POLY}-fill`,
      );
    };
    void (async () => {
      await sync("rgb", rgb);
      await sync("classes", classes);
      applyVisibility(map, layers);
    })().catch(() => setFailed(true));
    return () => {
      cancelled = true;
    };
    // a visibilidade tem efeito próprio; este só reage aos dados
  }, [ready, rgb, classes, coordinates]);

  // Polígonos
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    (map.getSource(POLY) as GeoJSONSource).setData(polygons ?? EMPTY_FC);
  }, [ready, polygons]);

  // Enquadra a cena quando muda a análise
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !coordinates) return;
    const lons = coordinates.map((c) => c[0]);
    const lats = coordinates.map((c) => c[1]);
    const bounds: LngLatBoundsLike = [
      [Math.min(...lons), Math.min(...lats)],
      [Math.max(...lons), Math.max(...lats)],
    ];
    map.resize(); // o container pode ter mudado de tamanho desde a criação
    // à esquerda, espaço para a legenda aberta (sobre o mapa), se couber
    const width = map.getContainer().clientWidth;
    const legend = width >= 900 ? 300 : 32;
    map.fitBounds(bounds, {
      padding: { top: 32, bottom: 32, right: 32, left: legend },
      duration: reducedMotion() ? 0 : 600,
    });
    // só ao trocar de análise: não "puxa" o mapa a cada refetch
  }, [ready, analysisId, coordinates !== null]);

  useEffect(() => {
    const map = mapRef.current;
    if (map && ready) applyVisibility(map, layers);
  }, [ready, layers]);

  // Polígono em foco: destaque + popup com os números do processamento
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    popupRef.current?.remove();
    map.setFilter(`${POLY}-focus`, ["==", ["get", "id"], focusPolygon ?? -1]);
    if (focusPolygon == null || !polygons) return;
    const feature = polygons.features.find((f: FeatureCollection["features"][number]) => f.properties?.id === focusPolygon);
    if (!feature) return;
    const p = feature.properties as PolygonStats;
    const popup = new Popup({ closeButton: true, maxWidth: "260px", focusAfterOpen: false })
      .setLngLat([p.point_lon, p.point_lat])
      .setDOMContent(popupContent(p))
      .addTo(map);
    popup.on("close", () => {
      if (popupRef.current === popup) onSelect.current?.(null);
    });
    popupRef.current = popup;
    if (!map.getBounds().contains([p.point_lon, p.point_lat])) {
      map.easeTo({ center: [p.point_lon, p.point_lat], duration: reducedMotion() ? 0 : 400 });
    }
  }, [ready, focusPolygon, polygons]);

  return (
    <div className="map-canvas">
      <div ref={container} className="map-canvas__gl" aria-label="Mapa da análise" role="region" />
      {failed && (
        <p className="map-canvas__fail">
          O mapa não pôde ser desenhado neste navegador (WebGL indisponível). Os números e downloads
          continuam valendo.
        </p>
      )}
    </div>
  );
}

function applyVisibility(map: MLMap, layers: Layers) {
  const set = (id: string, on: boolean) => {
    if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
  };
  set(IMAGE_LAYERS.rgb, layers.rgb);
  set(IMAGE_LAYERS.classes, layers.classes);
  for (const s of ["fill", "line", "focus"]) set(`${POLY}-${s}`, layers.polygons);
}

/** Conteúdo do popup montado com textContent (nada de HTML vindo de dados). */
function popupContent(p: PolygonStats): HTMLElement {
  const root = document.createElement("div");
  root.className = "poly-popup";
  const h = document.createElement("p");
  h.className = "poly-popup__title";
  h.textContent = `Candidata nº ${p.id}`;
  const area = document.createElement("p");
  area.className = "poly-popup__area";
  area.textContent = formatHa(p.area_ha);
  const dl = document.createElement("dl");
  const rows: [string, string][] = [
    ["NDVI médio", formatIndex(p.ndvi_mean)],
    ["NDWI médio", formatIndex(p.ndwi_mean)],
    ["SAVI médio", formatIndex(p.savi_mean)],
  ];
  if (p.ndvi_other_date_mean != null) rows.push(["NDVI 2ª data", formatIndex(p.ndvi_other_date_mean)]);
  for (const [k, v] of rows) {
    const dt = document.createElement("dt");
    dt.textContent = k;
    const dd = document.createElement("dd");
    dd.textContent = v;
    dl.append(dt, dd);
  }
  root.append(h, area, dl);
  return root;
}

function reducedMotion(): boolean {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}
