import type { Analysis, AnalysisItem, ChatOut, DownloadName, Session } from "./types";

/**
 * Cliente HTTP da API.
 *
 * O token é JWT Bearer enviado no header Authorization. Decisão consciente
 * para este desafio (frontend e API em domínios diferentes de hospedagem
 * gratuita, sem domínio próprio para cookie first-party); em produção seria
 * cookie httpOnly + SameSite. Ver README > Segurança.
 */

export const API_URL = (import.meta.env.VITE_API_URL ?? "").replace(/\/+$/, "");

export type ErrorKind =
  | "unauthorized" // 401: sessão expirada ou revogada
  | "not_found"
  | "conflict"
  | "too_large" // 413
  | "invalid" // 400/422: arquivo ou formulário rejeitado
  | "rate_limited" // 429: cota ou limite de frequência
  | "busy" // 503: fila cheia
  | "network" // sem resposta (offline, CORS, API dormindo)
  | "server";

export class ApiError extends Error {
  readonly status: number;
  readonly kind: ErrorKind;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.kind = kindOf(status);
  }
}

export function kindOf(status: number): ErrorKind {
  // 0 = sem resposta; 502/504 = proxy do host enquanto a API acorda do sono
  if (status === 0 || status === 502 || status === 504) return "network";
  if (status === 401) return "unauthorized";
  if (status === 404) return "not_found";
  if (status === 409) return "conflict";
  if (status === 413) return "too_large";
  if (status === 400 || status === 422) return "invalid";
  if (status === 429) return "rate_limited";
  if (status === 503) return "busy";
  return "server";
}

const FALLBACK: Record<ErrorKind, string> = {
  unauthorized: "Sua sessão expirou. Entre de novo para continuar.",
  not_found: "Não encontrado.",
  conflict: "A análise ainda não terminou.",
  too_large: "Arquivo grande demais.",
  invalid: "O envio foi rejeitado. Confira os arquivos.",
  rate_limited: "Limite de uso atingido. Aguarde e tente de novo.",
  busy: "A fila de processamento está cheia. Tente em alguns minutos.",
  network:
    "Não foi possível falar com a API. Ela pode estar acordando (o plano gratuito dorme após 15 min sem uso); aguarde até 1 minuto e tente de novo.",
  server: "Erro inesperado na API. Tente de novo.",
};

/** Extrai a mensagem do corpo {"detail": ...} do FastAPI sem confiar no formato. */
export function messageFrom(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: unknown; loc?: unknown };
    if (typeof first?.msg === "string") {
      const field = Array.isArray(first.loc) ? first.loc.at(-1) : undefined;
      return field ? `${String(field)}: ${first.msg}` : first.msg;
    }
  }
  return FALLBACK[kindOf(status)];
}

type TokenGetter = () => string | null;
/** Recebe o token que levou o 401: só a sessão que fez a requisição é encerrada. */
type UnauthorizedHandler = (token: string) => void;
/** Sinal abortado no fim da sessão: nada iniciado por um usuário termina no cache do próximo. */
type SignalGetter = () => AbortSignal | undefined;

export class ApiClient {
  constructor(
    private readonly base: string,
    private readonly getToken: TokenGetter,
    private readonly onUnauthorized: UnauthorizedHandler,
    private readonly fetchImpl: typeof fetch = (...a) => fetch(...a),
    private readonly sessionSignal: SignalGetter = () => undefined,
  ) {}

  private async raw(path: string, init: RequestInit = {}): Promise<Response> {
    const headers = new Headers(init.headers);
    const token = this.getToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    const signals = [init.signal, this.sessionSignal()].filter((x): x is AbortSignal => !!x);
    const signal = signals.length > 1 ? AbortSignal.any(signals) : signals[0];
    let res: Response;
    try {
      res = await this.fetchImpl(`${this.base}${path}`, { ...init, headers, signal });
    } catch (e) {
      if ((e as Error)?.name === "AbortError") throw e;
      throw new ApiError(0, FALLBACK.network);
    }
    if (!res.ok) {
      let body: unknown = null;
      try {
        body = await res.json();
      } catch {
        /* corpo não-JSON (ex.: página de erro do proxy) */
      }
      // Só derruba a sessão se havia token: 401 no login é "credencial inválida"
      if (res.status === 401 && token) this.onUnauthorized(token);
      throw new ApiError(res.status, messageFrom(res.status, body));
    }
    return res;
  }

  private async json<T>(path: string, init?: RequestInit): Promise<T> {
    return (await this.raw(path, init)).json() as Promise<T>;
  }

  /** Público, sem token: usado para acordar a API do plano gratuito. */
  async health(signal?: AbortSignal): Promise<void> {
    await this.raw("/health", { signal });
  }

  loginWithGoogle(credential: string): Promise<Session> {
    return this.json("/auth/google", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ credential }),
    });
  }

  async logout(): Promise<void> {
    await this.raw("/auth/logout", { method: "POST" });
  }

  listAnalyses(signal?: AbortSignal): Promise<AnalysisItem[]> {
    return this.json("/analyses", { signal });
  }

  getAnalysis(id: string, signal?: AbortSignal): Promise<Analysis> {
    return this.json(`/analyses/${encodeURIComponent(id)}`, { signal });
  }

  /**
   * Envia a análise. A Idempotency-Key é gerada por quem chama e reutilizada
   * em retentativas da MESMA submissão: um retry após timeout não cria uma
   * segunda análise nem gasta cota de novo.
   */
  createAnalysis(form: FormData, idempotencyKey: string): Promise<Analysis> {
    return this.json("/analyses", {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: form,
    });
  }

  async deleteAnalysis(id: string): Promise<void> {
    await this.raw(`/analyses/${encodeURIComponent(id)}`, { method: "DELETE" });
  }

  getChat(id: string, signal?: AbortSignal): Promise<ChatOut> {
    return this.json(`/analyses/${encodeURIComponent(id)}/chat`, { signal });
  }

  ask(id: string, message: string): Promise<ChatOut> {
    return this.json(`/analyses/${encodeURIComponent(id)}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
  }

  async file(id: string, name: DownloadName, signal?: AbortSignal): Promise<Blob> {
    return (await this.raw(`/analyses/${encodeURIComponent(id)}/files/${name}`, { signal })).blob();
  }
}
