import { act, renderHook } from "@testing-library/react";
import type { ApiClient } from "../api/client";
import { ApiError } from "../api/client";
import { useServerWarmup } from "./useServerWarmup";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

/** health() falso: cada chamada devolve a promessa que o teste controlar. */
function fakeApi() {
  const calls: { resolve: () => void; reject: (e: unknown) => void; signal?: AbortSignal }[] = [];
  const api = {
    health: (signal?: AbortSignal) =>
      new Promise<void>((resolve, reject) => {
        calls.push({ resolve, reject, signal });
        signal?.addEventListener("abort", () => reject(new DOMException("abort", "AbortError")));
      }),
  } as unknown as ApiClient;
  return { api, calls };
}

const OPTS = { slowAfterMs: 4_000, retryEveryMs: 3_000, attemptTimeoutMs: 20_000, giveUpAfterMs: 90_000 };
const tick = (ms: number) => act(async () => void (await vi.advanceTimersByTimeAsync(ms)));

it("resposta rápida: fica pronto sem nunca mostrar o aviso", async () => {
  const { api, calls } = fakeApi();
  const { result } = renderHook(() => useServerWarmup(api, OPTS));
  expect(result.current).toBe("checking");
  await act(async () => calls[0]?.resolve());
  expect(result.current).toBe("ready");
  await tick(10_000);
  expect(result.current).toBe("ready");
});

it("sem resposta em 4 s avisa que está acordando; 3,999 s ainda não (BVA)", async () => {
  const { api } = fakeApi();
  const { result } = renderHook(() => useServerWarmup(api, OPTS));
  await tick(3_999);
  expect(result.current).toBe("checking");
  await tick(1);
  expect(result.current).toBe("waking");
});

it("502 do proxy enquanto acorda: tenta de novo e fica pronto quando responde", async () => {
  const { api, calls } = fakeApi();
  const { result } = renderHook(() => useServerWarmup(api, OPTS));
  await act(async () => calls[0]?.reject(new ApiError(502, "x")));
  expect(result.current).toBe("waking");
  expect(calls).toHaveLength(1);
  await tick(3_000);
  expect(calls).toHaveLength(2);
  await act(async () => calls[1]?.resolve());
  expect(result.current).toBe("ready");
});

it("tentativa pendurada é abortada pelo timeout por tentativa e repetida", async () => {
  const { api, calls } = fakeApi();
  renderHook(() => useServerWarmup(api, OPTS));
  await tick(20_000);
  expect(calls[0]?.signal?.aborted).toBe(true);
  await tick(3_000);
  expect(calls).toHaveLength(2);
});

it("desiste depois de 90 s e mostra erro", async () => {
  const { api, calls } = fakeApi();
  const { result } = renderHook(() => useServerWarmup(api, OPTS));
  for (let i = 0; i < 40 && result.current !== "down"; i++) {
    await act(async () => calls.at(-1)?.reject(new ApiError(0, "rede")));
    await tick(3_000);
  }
  expect(result.current).toBe("down");
  const n = calls.length;
  await tick(30_000);
  expect(calls).toHaveLength(n); // parou de tentar
});

it("desmontar a tela cancela a tentativa e não agenda outras", async () => {
  const { api, calls } = fakeApi();
  const { unmount } = renderHook(() => useServerWarmup(api, OPTS));
  unmount();
  expect(calls[0]?.signal?.aborted).toBe(true);
  await tick(60_000);
  expect(calls).toHaveLength(1);
});
