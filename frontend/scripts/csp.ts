const GSI = "https://accounts.google.com/gsi/";
const TILES = "https://tiles.openfreemap.org";

/** Origem (esquema + host + porta) da URL da API; vazio se inválida. */
export function apiOrigin(url: string): string {
  try {
    return new URL(url).origin;
  } catch {
    return "";
  }
}

export function buildCsp(apiUrl: string): string {
  const api = apiOrigin(apiUrl);
  const directives: Record<string, string[]> = {
    "default-src": ["'self'"],
    "script-src": ["'self'", `${GSI}client`],
    // GIS injeta estilos; MapLibre usa style inline em elementos
    "style-src": ["'self'", "'unsafe-inline'", `${GSI}style`],
    "img-src": ["'self'", "data:", "blob:", TILES],
    "font-src": ["'self'"],
    "connect-src": ["'self'", api, GSI, TILES].filter(Boolean),
    "frame-src": [GSI],
    "worker-src": ["'self'", "blob:"],
    "object-src": ["'none'"],
    "base-uri": ["'self'"],
    "form-action": ["'self'"],
    "frame-ancestors": ["'none'"],
  };
  return Object.entries(directives)
    .map(([k, v]) => `${k} ${v.join(" ")}`)
    .join("; ");
}
