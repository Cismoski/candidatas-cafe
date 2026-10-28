import { ApiClient, ApiError, kindOf, messageFrom } from "./client";

describe("kindOf (um ramo por status)", () => {
  it.each([
    [0, "network"],
    [401, "unauthorized"],
    [404, "not_found"],
    [409, "conflict"],
    [413, "too_large"],
    [400, "invalid"],
    [422, "invalid"],
    [429, "rate_limited"],
    [503, "busy"],
    [500, "server"],
    [403, "server"],
  ])("%i -> %s", (status, kind) => {
    expect(kindOf(status)).toBe(kind);
  });
});

describe("messageFrom", () => {
  it("usa detail string da API", () => {
    expect(messageFrom(429, { detail: "Limite de 10 análises por dia atingido." })).toBe(
      "Limite de 10 análises por dia atingido.",
    );
  });
  it("usa o primeiro erro de validação com o campo", () => {
    expect(messageFrom(422, { detail: [{ loc: ["body", "credential"], msg: "too short" }] })).toBe(
      "credential: too short",
    );
  });
  it("erro de validação sem loc", () => {
    expect(messageFrom(422, { detail: [{ msg: "ruim" }] })).toBe("ruim");
  });
  it.each([[null], [{}], [{ detail: "  " }], [{ detail: [] }], [{ detail: [{}] }], ["texto"]])(
    "cai no texto padrão do status para corpo %j",
    (body) => {
      expect(messageFrom(503, body)).toMatch(/fila/i);
    },
  );
});

function client(fetchImpl: typeof fetch, token: string | null = "tok") {
  const onUnauthorized = vi.fn();
  return { api: new ApiClient("http://api", () => token, onUnauthorized, fetchImpl), onUnauthorized };
}

describe("ApiClient", () => {
  it("envia Bearer quando há token", async () => {
    const f = vi.fn(async () => new Response("[]", { status: 200 }));
    await client(f as unknown as typeof fetch).api.listAnalyses();
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://api/analyses");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer tok");
  });

  it("não envia Authorization sem token", async () => {
    const f = vi.fn(async () => new Response("[]", { status: 200 }));
    await client(f as unknown as typeof fetch, null).api.listAnalyses();
    const [, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(new Headers(init.headers).has("Authorization")).toBe(false);
  });

  it("401 com token encerra a sessão", async () => {
    const f = async () => new Response('{"detail":"Token expirado."}', { status: 401 });
    const { api, onUnauthorized } = client(f as typeof fetch);
    await expect(api.listAnalyses()).rejects.toMatchObject({ status: 401, message: "Token expirado." });
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });

  it("401 sem token (login recusado) não dispara expiração", async () => {
    const f = async () => new Response('{"detail":"Login com Google inválido."}', { status: 401 });
    const { api, onUnauthorized } = client(f as typeof fetch, null);
    await expect(api.loginWithGoogle("x".repeat(20))).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it("falha de rede vira ApiError(0) com orientação", async () => {
    const f = async () => {
      throw new TypeError("Failed to fetch");
    };
    const err = await client(f as typeof fetch).api.listAnalyses().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.kind).toBe("network");
    expect(err.message).toMatch(/acordando/);
  });

  it("AbortError é repassado (cancelamento não é erro de rede)", async () => {
    const f = async () => {
      throw new DOMException("aborted", "AbortError");
    };
    await expect(client(f as typeof fetch).api.listAnalyses()).rejects.toMatchObject({ name: "AbortError" });
  });

  it("corpo de erro não-JSON usa a mensagem padrão", async () => {
    const f = async () => new Response("<html>502</html>", { status: 502 });
    await expect(client(f as typeof fetch).api.listAnalyses()).rejects.toMatchObject({
      kind: "server",
      status: 502,
    });
  });

  it("createAnalysis manda a Idempotency-Key e o multipart sem Content-Type manual", async () => {
    const f = vi.fn(async () => new Response("{}", { status: 202 }));
    const form = new FormData();
    form.append("primary", new Blob(["x"]), "a.tif");
    await client(f as unknown as typeof fetch).api.createAnalysis(form, "chave-123456");
    const [, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    const h = new Headers(init.headers);
    expect(h.get("Idempotency-Key")).toBe("chave-123456");
    expect(h.has("Content-Type")).toBe(false); // o navegador define o boundary
    expect(init.method).toBe("POST");
  });

  it("codifica o id na URL (sem path traversal vindo do cliente)", async () => {
    const f = vi.fn(async () => new Response("{}", { status: 200 }));
    await client(f as unknown as typeof fetch).api.getAnalysis("../x");
    expect((f.mock.calls[0] as unknown as [string])[0]).toBe("http://api/analyses/..%2Fx");
  });
});
