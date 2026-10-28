import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import type { Analysis, Summary } from "../api/types";
import { AuthProvider } from "../auth/AuthProvider";
import { save } from "../auth/session";

export const API = "http://api.test";

export function signIn(expiresInMs = 3_600_000) {
  save({
    token: "tok-alice",
    expiresAt: Date.now() + expiresInMs,
    user: { id: "u-alice", email: "alice@example.com", name: "Alice" },
  });
}

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

export interface Call {
  url: string;
  method: string;
  headers: Headers;
  body: BodyInit | null | undefined;
}

/** Instala um fetch falso roteado por "MÉTODO caminho". Guarda o corpo original
 * (o Request do Node não aceita o File do jsdom). */
export function mockFetch(routes: Record<string, (call: Call) => Response | Promise<Response>>) {
  const calls: Call[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), window.location.href).toString();
    const call = { url, method: init.method ?? "GET", headers: new Headers(init.headers), body: init.body };
    calls.push(call);
    const handler = routes[`${call.method} ${new URL(url).pathname}`];
    if (!handler) throw new TypeError("Failed to fetch");
    return handler(call);
  });
  vi.stubGlobal("fetch", fn);
  return { fn, calls };
}

export function renderWithProviders(ui: ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return {
    qc,
    ...render(
      <QueryClientProvider client={qc}>
        <AuthProvider baseUrl={API}>{ui}</AuthProvider>
      </QueryClientProvider>,
    ),
  };
}

export function makeSummary(over: Partial<Summary["results"]> = {}): Summary {
  return {
    schema_version: 1,
    generated_utc: "2026-10-28T20:00:00+00:00",
    inputs: {
      primary: {
        acquired_utc: "2025-08-16T13:28:10.823Z",
        source_item: "S2B_T23KLS_20250816T132502_L2A",
        crs: "EPSG:32723",
        width: 512,
        height: 512,
        pixel_size_m: [10, 10],
        radiometry: "metadados do GeoTIFF",
      },
      secondary: null,
      scl_used: true,
    },
    method: {
      mode: "single_date",
      description: "Regras espectrais explicáveis.",
      parameters: { morphology: { min_area_ha: 0.5 } },
      dense_canopy_ndvi_threshold: 0.6648,
      dense_canopy_threshold_source: "Otsu sobre o NDVI da vegetação",
      otsu_separability: 0.795,
    },
    results: {
      candidate_polygons: 2,
      candidate_area_ha: 155.31,
      analysed_area_ha: 2620.2,
      candidate_fraction_of_analysed: 0.0593,
      temporal_unverified_ha: 0,
      temporal_rejected_ha: 0,
      input_coverage: { scl: 1 },
      class_areas: {
        nodata: { label: "Sem dado", area_ha: 0 },
        masked_quality: { label: "Excluído pela máscara de qualidade (SCL)", area_ha: 1.24 },
        water: { label: "Água / alta umidade", area_ha: 2.97 },
        low_vegetation: { label: "Solo exposto ou vegetação rala", area_ha: 1021.52 },
        dense_canopy: { label: "Dossel fechado (mata/eucalipto)", area_ha: 1045.78 },
        discarded: { label: "Vegetação intermediária descartada", area_ha: 394.62 },
        candidate: { label: "Candidata a café", area_ha: 155.31 },
      },
      index_stats: {},
      polygons: [
        { id: 1, area_ha: 0.65, ndvi_mean: 0.5769, ndwi_mean: -0.5685, savi_mean: 0.3598, texture_mean: 0.1, point_lon: -46.69, point_lat: -21.3, classe: "candidata_cafe" },
        { id: 2, area_ha: 8.33, ndvi_mean: 0.55, ndwi_mean: -0.6, savi_mean: 0.36, texture_mean: 0.1, point_lon: -46.68, point_lat: -21.31, classe: "candidata_cafe" },
      ],
      ...over,
    },
    map: {
      overlay_crs: "EPSG:3857",
      coordinates: [
        [-46.705, -21.306],
        [-46.655, -21.306],
        [-46.655, -21.353],
        [-46.705, -21.353],
      ],
    },
    limitations: ["Resultado são ÁREAS CANDIDATAS.", "Sem segunda data."],
    attribution: "Contains modified Copernicus Sentinel data (2025)",
  };
}

export function makeAnalysis(over: Partial<Analysis> = {}): Analysis {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    status: "done",
    error: null,
    title: "Guaxupé",
    has_scl: true,
    has_secondary: false,
    created_at: "2026-10-28T20:00:00+00:00",
    updated_at: "2026-10-28T20:00:05+00:00",
    expires_at: new Date(Date.now() + 5 * 3_600_000).toISOString(),
    summary: makeSummary(),
    ...over,
  };
}
