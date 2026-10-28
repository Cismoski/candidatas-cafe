// Espelha os modelos do backend (app/main.py) e o summary.json do pipeline
// (app/processing/pipeline.py). schema_version permite detectar divergência.

export type AnalysisStatus = "pending" | "processing" | "done" | "failed";

export interface User {
  id: string;
  email: string;
  name: string | null;
}

export interface Session {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: User;
}

export interface AnalysisItem {
  id: string;
  status: AnalysisStatus;
  error: string | null;
  title: string;
  has_scl: boolean;
  has_secondary: boolean;
  created_at: string;
  updated_at: string;
  expires_at: string;
}

export interface Analysis extends AnalysisItem {
  summary: Summary | null;
}

export interface SceneInfo {
  acquired_utc: string | null;
  source_item: string | null;
  crs: string;
  width: number;
  height: number;
  pixel_size_m: [number, number];
  radiometry: string;
}

export interface Percentiles {
  n_pixels: number;
  mean: number | null;
  p05: number | null;
  p25: number | null;
  median: number | null;
  p75: number | null;
  p95: number | null;
}

export type ClassKey =
  | "nodata"
  | "masked_quality"
  | "water"
  | "low_vegetation"
  | "dense_canopy"
  | "discarded"
  | "candidate";

export interface PolygonStats {
  id: number;
  area_ha: number;
  ndvi_mean: number;
  ndwi_mean: number;
  savi_mean: number;
  texture_mean: number;
  ndvi_other_date_mean?: number | null;
  point_lon: number;
  point_lat: number;
  classe: string;
}

export type LngLat = [number, number];

export interface Summary {
  schema_version: number;
  generated_utc: string;
  inputs: {
    primary: SceneInfo;
    secondary: SceneInfo | null;
    scl_used: boolean;
  };
  method: {
    mode: "single_date" | "two_dates";
    description: string;
    parameters: Record<string, unknown>;
    dense_canopy_ndvi_threshold: number;
    dense_canopy_threshold_source: string;
    otsu_separability: number | null;
  };
  results: {
    candidate_polygons: number;
    candidate_area_ha: number;
    analysed_area_ha: number;
    candidate_fraction_of_analysed: number;
    temporal_unverified_ha: number;
    temporal_rejected_ha: number;
    input_coverage: Record<string, number>;
    class_areas: Record<ClassKey, { label: string; area_ha: number }>;
    index_stats: Record<string, { analysed_land: Percentiles; candidates: Percentiles }>;
    polygons: PolygonStats[];
  };
  map: {
    overlay_crs: string;
    /** Cantos TL, TR, BR, BL em lon/lat (ordem da image source do MapLibre). */
    coordinates: [LngLat, LngLat, LngLat, LngLat];
  };
  limitations: string[];
  attribution: string;
}

export type DownloadName = "geojson" | "png" | "geotiff" | "overlay-rgb" | "overlay-classes";

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  /** "gemini" = modelo de linguagem; "automatica" = resposta por regras, sem IA. */
  source: "gemini" | "automatica" | null;
  notice: string | null;
  created_at: string;
}

export interface ChatOut {
  messages: ChatMessage[];
  remaining_today: number | null;
}
