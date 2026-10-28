import type { Session, User } from "../api/types";

/**
 * Sessão guardada em sessionStorage: some ao fechar a aba e não é
 * compartilhada entre abas. O token também fica acessível a JavaScript (risco
 * de XSS), mitigado por CSP estrita sem scripts inline nem de terceiros além
 * do Google Identity Services. Em produção: cookie httpOnly (ver README).
 */

const KEY = "gw.session";
/** Margem para não usar um token que expira durante a requisição. */
const SKEW_MS = 30_000;

export interface StoredSession {
  token: string;
  expiresAt: number; // epoch ms
  user: User;
}

export function fromLogin(s: Session, now = Date.now()): StoredSession {
  return { token: s.access_token, expiresAt: now + s.expires_in * 1000, user: s.user };
}

export function isValid(s: StoredSession | null, now = Date.now()): s is StoredSession {
  return s !== null && s.expiresAt - SKEW_MS > now;
}

export function load(storage: Storage = sessionStorage, now = Date.now()): StoredSession | null {
  try {
    const raw = storage.getItem(KEY);
    if (!raw) return null;
    const s = JSON.parse(raw) as Partial<StoredSession>;
    const ok =
      typeof s.token === "string" &&
      typeof s.expiresAt === "number" &&
      typeof s.user?.id === "string" &&
      typeof s.user?.email === "string";
    if (!ok) {
      storage.removeItem(KEY);
      return null;
    }
    const session = s as StoredSession;
    if (!isValid(session, now)) {
      storage.removeItem(KEY);
      return null;
    }
    return session;
  } catch {
    return null; // storage bloqueado (modo privado) ou JSON corrompido
  }
}

export function save(s: StoredSession, storage: Storage = sessionStorage): void {
  try {
    storage.setItem(KEY, JSON.stringify(s));
  } catch {
    /* sem storage: a sessão vive só na memória desta aba */
  }
}

export function clear(storage: Storage = sessionStorage): void {
  try {
    storage.removeItem(KEY);
  } catch {
    /* idem */
  }
}
