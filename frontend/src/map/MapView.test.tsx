import { act, render, screen } from "@testing-library/react";
import type { FeatureCollection } from "geojson";
import type { LngLat } from "../api/types";

/**
 * MapLibre falso: só o que o MapView usa, com o comportamento que importa
 * (Popup.remove() dispara "close", como no MapLibre 6; eventos load/error).
 */
type Handler = (...a: unknown[]) => void;
class Emitter {
  handlers: Record<string, Handler[]> = {};
  on(ev: string, a: unknown, b?: unknown) {
    const h = (typeof a === "function" ? a : b) as Handler;
    const key = typeof a === "string" ? `${ev}:${a}` : ev;
    (this.handlers[key] ??= []).push(h);
    return this;
  }
  once(ev: string, h: Handler) {
    return this.on(ev, h);
  }
  fire(ev: string, ...args: unknown[]) {
    for (const h of this.handlers[ev] ?? []) h(...args);
  }
}

const maps: FakeMap[] = [];
const popups: FakePopup[] = [];

class FakeMap extends Emitter {
  layers: string[] = [];
  sources = new Map<string, { image?: unknown; data?: unknown }>();
  style: unknown;
  transformStyle: unknown;
  visibility: Record<string, string> = {};
  constructor(opts: { style: unknown; transformStyle?: unknown }) {
    super();
    this.style = opts.style;
    this.transformStyle = opts.transformStyle;
    maps.push(this);
  }
  addControl() {}
  getBounds() {
    return { getWest: () => -1, getSouth: () => -2, getEast: () => 1, getNorth: () => 2, contains: () => true };
  }
  getContainer() {
    return { clientWidth: 1000 };
  }
  getCanvas() {
    return { style: {} };
  }
  addSource(id: string) {
    this.sources.set(id, {});
  }
  getSource(id: string) {
    const s = this.sources.get(id);
    return s && { setData: (d: unknown) => (s.data = d), updateImage: (o: { image: unknown }) => (s.image = o.image) };
  }
  removeSource(id: string) {
    this.sources.delete(id);
  }
  addLayer(l: { id: string }, before?: string) {
    const i = before ? this.layers.indexOf(before) : -1;
    if (i >= 0) this.layers.splice(i, 0, l.id);
    else this.layers.push(l.id);
  }
  getLayer(id: string) {
    return this.layers.includes(id) ? { id } : undefined;
  }
  removeLayer(id: string) {
    this.layers = this.layers.filter((x) => x !== id);
  }
  setLayoutProperty(id: string, _: string, v: string) {
    this.visibility[id] = v;
  }
  setFilter() {}
  setStyle(s: unknown) {
    this.style = s;
  }
  fitBounds() {}
  easeTo() {}
  resize() {}
  remove() {}
}

class FakePopup extends Emitter {
  open = false;
  content: HTMLElement | null = null;
  constructor() {
    super();
    popups.push(this);
  }
  setLngLat() {
    return this;
  }
  setDOMContent(el: HTMLElement) {
    this.content = el;
    return this;
  }
  addTo() {
    this.open = true;
    return this;
  }
  remove() {
    this.open = false;
    this.fire("close"); // como o MapLibre real
    return this;
  }
}

vi.mock("maplibre-gl", () => ({
  Map: FakeMap,
  Popup: FakePopup,
  NavigationControl: class {},
  ScaleControl: class {},
  setWorkerUrl: () => {},
}));
vi.mock("maplibre-gl/dist/maplibre-gl.css", () => ({}));
vi.mock("maplibre-gl/dist/maplibre-gl-worker.mjs?url", () => ({ default: "/worker.mjs" }));

const { MapView, fixBasemapStyle } = await import("./MapView");

const COORDS: [LngLat, LngLat, LngLat, LngLat] = [
  [-46.7, -21.3],
  [-46.6, -21.3],
  [-46.6, -21.4],
  [-46.7, -21.4],
];
const FC: FeatureCollection = {
  type: "FeatureCollection",
  features: [1, 2].map((id) => ({
    type: "Feature",
    geometry: { type: "Point", coordinates: [0, 0] },
    properties: { id, area_ha: id, ndvi_mean: 0.5, ndwi_mean: -0.5, savi_mean: 0.3, point_lon: 0, point_lat: 0 },
  })),
};
const LAYERS = { rgb: true, classes: true, polygons: true, reference: false };

// createImageBitmap controlável: cada chamada fica pendente até resolvermos
type Pending = { blob: Blob; resolve: (b: ImageBitmap) => void; reject: (e: Error) => void };
let decodes: Pending[] = [];
type FakeBitmap = ImageBitmap & { name: string; closed: boolean };
function bitmap(name: string): FakeBitmap {
  const b = { name, closed: false, close: () => (b.closed = true) };
  return b as unknown as FakeBitmap;
}

beforeEach(() => {
  maps.length = 0;
  popups.length = 0;
  decodes = [];
  vi.stubGlobal(
    "createImageBitmap",
    (blob: Blob) => new Promise<ImageBitmap>((resolve, reject) => decodes.push({ blob, resolve, reject })),
  );
});
afterEach(() => vi.unstubAllGlobals());

function setup(props: Partial<Parameters<typeof MapView>[0]> = {}) {
  const onSelectPolygon = vi.fn();
  const base = {
    analysisId: "a",
    coordinates: COORDS,
    rgb: null,
    classes: null,
    polygons: FC,
    layers: LAYERS,
    focusPolygon: null,
    onSelectPolygon,
    ...props,
  };
  const r = render(<MapView {...base} />);
  const map = maps.at(-1) as FakeMap;
  act(() => map.fire("load"));
  return { ...r, map, base, onSelectPolygon };
}

const flush = () => act(async () => {});

it("trocar o polígono em foco mantém o novo popup (remove() do antigo não desmarca)", () => {
  const { rerender, base, onSelectPolygon } = setup({ focusPolygon: 1 });
  expect(popups.at(-1)?.open).toBe(true);
  rerender(<MapView {...base} focusPolygon={2} />);
  expect(onSelectPolygon).not.toHaveBeenCalledWith(null);
  expect(popups.at(-1)?.open).toBe(true);
  expect(popups.at(-1)?.content?.textContent).toContain("Candidata nº 2");
});

it("fechar o popup pelo X desmarca o polígono", () => {
  const { onSelectPolygon } = setup({ focusPolygon: 1 });
  act(() => popups.at(-1)?.fire("close")); // clique no X
  expect(onSelectPolygon).toHaveBeenCalledWith(null);
});

it("popup monta texto com textContent (dado não vira HTML)", () => {
  const evil: FeatureCollection = {
    ...FC,
    features: [{ ...(FC.features[0] as FeatureCollection["features"][number]), properties: { ...FC.features[0]?.properties, id: "<img src=x onerror=alert(1)>" } }],
  };
  setup({ polygons: evil, focusPolygon: "<img src=x onerror=alert(1)>" as unknown as number });
  expect(popups.at(-1)?.content?.querySelector("img")).toBeNull();
});

it("execução cancelada de sobreposição não mexe no mapa nem fecha bitmaps da nova", async () => {
  const blobA = new Blob(["A"]);
  const blobB = new Blob(["B"]);
  const { rerender, base, map } = setup({ rgb: blobA, classes: blobA });
  // Análise A ainda decodificando; usuário troca para B
  rerender(<MapView {...base} rgb={blobB} classes={blobB} />);
  const [a1, a2, b1, b2] = decodes;
  const bmB1 = bitmap("B-rgb");
  const bmB2 = bitmap("B-classes");
  b1?.resolve(bmB1);
  b2?.resolve(bmB2);
  await flush();
  expect(map.layers).toEqual(["overlay-rgb", "overlay-classes", "candidates-fill", "candidates-line", "candidates-focus"]);
  // A termina depois: deve ser descartada
  const bmA1 = bitmap("A-rgb");
  const bmA2 = bitmap("A-classes");
  a1?.resolve(bmA1);
  a2?.resolve(bmA2);
  await flush();
  expect(map.sources.get("overlay-rgb")?.image).toBe(bmB1);
  expect(map.sources.get("overlay-classes")?.image).toBe(bmB2);
  expect(bmB1.closed || bmB2.closed).toBe(false);
  expect(bmA1.closed && bmA2.closed).toBe(true);
});

it("visibilidade alterada durante a decodificação é respeitada", async () => {
  const blob = new Blob(["x"]);
  const { rerender, base, map } = setup({ rgb: blob, classes: blob });
  rerender(<MapView {...base} rgb={blob} classes={blob} layers={{ ...LAYERS, classes: false }} />);
  decodes[0]?.resolve(bitmap("r"));
  decodes[1]?.resolve(bitmap("c"));
  await flush();
  expect(map.visibility["overlay-classes"]).toBe("none");
  expect(map.visibility["overlay-rgb"]).toBe("visible");
});

it("mapa base fora do ar: troca por estilo vazio, ainda desenha a análise e avisa", async () => {
  const onSelectPolygon = vi.fn();
  render(
    <MapView
      analysisId="a"
      coordinates={COORDS}
      rgb={null}
      classes={null}
      polygons={FC}
      layers={LAYERS}
      focusPolygon={null}
      onSelectPolygon={onSelectPolygon}
    />,
  );
  const map = maps.at(-1) as FakeMap;
  act(() => map.fire("error", new Error("style 503")));
  expect(map.style).toEqual({ version: 8, sources: {}, layers: [] });
  act(() => map.fire("style.load"));
  expect(map.getSource("candidates")).toBeDefined();
  expect(screen.getByRole("status")).toHaveTextContent("mapa de fundo está indisponível");
});

it("decodificação que falha mostra aviso específico (não 'WebGL')", async () => {
  vi.stubGlobal("createImageBitmap", () => Promise.reject(new Error("bad png")));
  setup({ rgb: new Blob(["y"]) });
  await flush();
  expect(screen.getAllByRole("status").at(-1)).toHaveTextContent("Não foi possível desenhar a imagem");
});

it("camada do MapBiomas entra abaixo dos polígonos e respeita o liga/desliga", async () => {
  const { map, rerender, base } = setup({ rgb: new Blob(["r"]), classes: new Blob(["c"]), reference: new Blob(["m"]) });
  const [r, c, m] = decodes;
  r?.resolve(bitmap("rgb"));
  c?.resolve(bitmap("classes"));
  m?.resolve(bitmap("ref"));
  await flush();
  expect(map.layers).toEqual([
    "overlay-rgb",
    "overlay-classes",
    "overlay-reference",
    "candidates-fill",
    "candidates-line",
    "candidates-focus",
  ]);
  expect(map.visibility["overlay-reference"]).toBe("none"); // LAYERS.reference = false
  rerender(<MapView {...base} reference={base.reference} layers={{ ...LAYERS, reference: true }} />);
  await flush();
  expect(map.visibility["overlay-reference"]).toBe("visible");
});

it("falha ao decodificar a referência não esconde as outras camadas", async () => {
  const { map } = setup({ rgb: new Blob(["r"]), classes: new Blob(["c"]), reference: new Blob(["m"]) });
  const [r, c, m] = decodes;
  m?.reject(new Error("png inválido"));
  r?.resolve(bitmap("rgb"));
  c?.resolve(bitmap("classes"));
  await flush();
  expect(map.layers).toEqual(["overlay-rgb", "overlay-classes", "candidates-fill", "candidates-line", "candidates-focus"]);
  expect(screen.getByText(/camada do MapBiomas/)).toBeInTheDocument();
  expect(screen.queryByText(/Não foi possível desenhar a imagem sobre o mapa/)).toBeNull();
});

it("referência que chega antes das outras ainda fica acima delas", async () => {
  const { map } = setup({ rgb: new Blob(["r"]), classes: new Blob(["c"]), reference: new Blob(["m"]) });
  const [r, c, m] = decodes;
  m?.resolve(bitmap("ref"));
  await flush();
  r?.resolve(bitmap("rgb"));
  c?.resolve(bitmap("classes"));
  await flush();
  expect(map.layers.slice(0, 3)).toEqual(["overlay-rgb", "overlay-classes", "overlay-reference"]);
});

it("estilo do mapa base: ref_length nulo vira 99 só nos filtros que o leem", () => {
  // Filtro copiado da camada highway-shield-non-us do positron (OpenFreeMap)
  const shield = [
    "all",
    ["<=", ["get", "ref_length"], 6],
    ["match", ["get", "network"], ["us-highway", "us-interstate", "us-state"], false, true],
  ];
  const other = ["==", ["get", "class"], "motorway"];
  const style = {
    version: 8 as const,
    sources: {},
    layers: [
      { id: "shield", type: "symbol" as const, source: "s", filter: shield },
      { id: "road", type: "line" as const, source: "s", filter: other },
      { id: "bg", type: "background" as const },
    ],
  };
  const out = fixBasemapStyle(undefined, style as never);
  expect((out.layers[0] as { filter: unknown }).filter).toEqual([
    "all",
    ["<=", ["coalesce", ["get", "ref_length"], 99], 6],
    shield[2],
  ]);
  expect(out.layers[1]).toEqual(style.layers[1]);
  expect(out.layers[2]).toEqual(style.layers[2]);
  expect(style.layers[0]?.filter?.[1]).toEqual(["<=", ["get", "ref_length"], 6]); // não muta a entrada
});

it("mapa é criado com o ajuste de estilo do mapa base", () => {
  const { map } = setup();
  expect(map.transformStyle).toBe(fixBasemapStyle);
});
