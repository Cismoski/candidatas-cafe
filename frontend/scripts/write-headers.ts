/**
 * Gera dist/_headers (Cloudflare Pages) com a CSP do build.
 * connect-src precisa da origem da API, que só se conhece no build
 * (VITE_API_URL); por isso o arquivo não é estático.
 *
 * Cada origem externa tem um motivo:
 * - accounts.google.com/gsi: botão e popup do Google Identity Services
 * - tiles.openfreemap.org: estilo, tiles e fontes do mapa base (sem chave)
 *
 * A URL vem do mesmo loadEnv do Vite (modo production, .env.production* e
 * variáveis do ambiente), para a CSP nunca divergir do que foi para o bundle.
 */
import { writeFileSync } from "node:fs";
import { loadEnv } from "vite";
import { buildCsp } from "./csp";

const api = loadEnv("production", process.cwd(), "VITE_").VITE_API_URL ?? "";
let csp: string;
try {
  csp = buildCsp(api);
} catch (e) {
  console.error(`Build sem CSP: ${(e as Error).message}. Defina VITE_API_URL.`);
  process.exit(1);
}
const headers = `/*
  Content-Security-Policy: ${csp}
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: camera=(), microphone=(), geolocation=()
  Cross-Origin-Opener-Policy: same-origin-allow-popups
  Strict-Transport-Security: max-age=31536000

/assets/*
  Cache-Control: public, max-age=31536000, immutable
`;
writeFileSync("dist/_headers", headers);
console.log(`dist/_headers gerado (API: ${api})`);
