const GSI = "https://accounts.google.com/gsi/";
const TILES = "https://tiles.openfreemap.org";
const LOCAL = new Set(["localhost", "127.0.0.1", "[::1]"]);

/**
 * Origem (esquema + host + porta) da URL da API, ou erro. Falha fechada: sem
 * uma origem válida o build não gera CSP, em vez de gerar uma que quebra o
 * app em produção sem aviso. http só é aceito para a máquina local.
 */
export function apiOrigin(url: string): string {
  let u: URL;
  try {
    u = new URL(url);
  } catch {
    throw new Error(`VITE_API_URL inválida: "${url}"`);
  }
  const local = LOCAL.has(u.hostname);
  if (u.protocol !== "https:" && !(local && u.protocol === "http:")) {
    throw new Error(`VITE_API_URL precisa ser https (recebido ${u.protocol})`);
  }
  return u.origin;
}

export function buildCsp(apiUrl: string): string {
  const api = apiOrigin(apiUrl);
  const directives: Record<string, string[]> = {
    "default-src": ["'self'"],
    "script-src": ["'self'", `${GSI}client`],
    // GIS injeta estilos; MapLibre usa style inline em elementos
    "style-src": ["'self'", "'unsafe-inline'", `${GSI}style`],
    // data: ícones dos controles do MapLibre
    "img-src": ["'self'", "data:", TILES],
    "font-src": ["'self'"],
    "connect-src": ["'self'", api, GSI, TILES],
    "frame-src": [GSI],
    // worker do MapLibre servido pela própria origem (setWorkerUrl)
    "worker-src": ["'self'"],
    "object-src": ["'none'"],
    "base-uri": ["'self'"],
    "form-action": ["'self'"],
    "frame-ancestors": ["'none'"],
  };
  return Object.entries(directives)
    .map(([k, v]) => `${k} ${v.join(" ")}`)
    .join("; ");
}
