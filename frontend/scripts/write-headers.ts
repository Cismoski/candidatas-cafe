/**
 * Gera dist/_headers (Cloudflare Pages) com a CSP do build.
 * connect-src precisa da origem da API, que só se conhece no build
 * (VITE_API_URL); por isso o arquivo não é estático.
 *
 * Cada origem externa tem um motivo:
 * - accounts.google.com/gsi: botão e popup do Google Identity Services
 * - tiles.openfreemap.org: estilo, tiles e fontes do mapa base (sem chave)
 * - blob: workers do MapLibre e imagens das sobreposições
 */
import { writeFileSync } from "node:fs";
import { buildCsp } from "./csp";

const api = process.env.VITE_API_URL ?? "";
const headers = `/*
  Content-Security-Policy: ${buildCsp(api)}
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: camera=(), microphone=(), geolocation=()
  Cross-Origin-Opener-Policy: same-origin-allow-popups
  Strict-Transport-Security: max-age=31536000

/assets/*
  Cache-Control: public, max-age=31536000, immutable
`;
writeFileSync("dist/_headers", headers);
console.log(`dist/_headers gerado (API: ${api || "mesma origem"})`);
