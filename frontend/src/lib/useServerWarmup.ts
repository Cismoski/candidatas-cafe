import { useEffect, useState } from "react";
import type { ApiClient } from "../api/client";

/**
 * Acorda a API assim que a tela de login abre.
 *
 * O backend no plano gratuito dorme após 15 min sem uso e leva ~1 min para
 * voltar; nesse meio-tempo o proxy do host segura a conexão ou devolve 502.
 * Em vez de o primeiro clique "falhar", a tela avisa que o servidor está
 * acordando enquanto a pessoa ainda lê a página.
 *
 * - "checking": primeira tentativa em andamento (sem aviso: em geral é rápido)
 * - "waking": sem resposta em `slowAfterMs`, ou falha de rede/502: tentando de novo
 * - "ready": /health respondeu
 * - "down": nada em `giveUpAfterMs`; o aviso vira erro
 */
export type WarmupState = "checking" | "waking" | "ready" | "down";

export function useServerWarmup(
  api: ApiClient,
  { slowAfterMs = 4_000, retryEveryMs = 3_000, attemptTimeoutMs = 20_000, giveUpAfterMs = 90_000 } = {},
): WarmupState {
  const [state, setState] = useState<WarmupState>("checking");

  useEffect(() => {
    const stop = new AbortController();
    const started = Date.now();
    const slow = window.setTimeout(() => setState((s) => (s === "checking" ? "waking" : s)), slowAfterMs);
    const wait = (ms: number) =>
      new Promise<void>((resolve) => {
        const t = window.setTimeout(resolve, ms);
        stop.signal.addEventListener("abort", () => window.clearTimeout(t), { once: true });
      });

    (async () => {
      while (!stop.signal.aborted) {
        const attempt = new AbortController();
        const timer = window.setTimeout(() => attempt.abort(), attemptTimeoutMs);
        try {
          await api.health(AbortSignal.any([stop.signal, attempt.signal]));
          if (!stop.signal.aborted) setState("ready");
          return;
        } catch {
          if (stop.signal.aborted) return;
        } finally {
          window.clearTimeout(timer);
        }
        if (Date.now() - started >= giveUpAfterMs) {
          setState("down");
          return;
        }
        setState("waking");
        await wait(retryEveryMs);
      }
    })();

    return () => {
      window.clearTimeout(slow);
      stop.abort();
    };
  }, [api, slowAfterMs, retryEveryMs, attemptTimeoutMs, giveUpAfterMs]);

  return state;
}
