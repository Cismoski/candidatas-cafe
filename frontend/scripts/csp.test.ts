import { apiOrigin, buildCsp } from "./csp";

const directive = (csp: string, name: string) =>
  csp
    .split("; ")
    .find((d) => d.startsWith(`${name} `))
    ?.split(" ")
    .slice(1) ?? [];

describe("CSP", () => {
  it("connect-src inclui só a ORIGEM da API (sem caminho)", () => {
    const csp = buildCsp("https://api.exemplo.com/v1/");
    expect(directive(csp, "connect-src")).toContain("https://api.exemplo.com");
    expect(csp).not.toContain("/v1");
  });

  it.each([[""], ["não é url"], ["javascript:alert(1)"], ["http://api.exemplo.com"], ["ftp://x.com"]])(
    "falha fechada para %j (o build para em vez de gerar CSP quebrada)",
    (url) => {
      expect(() => buildCsp(url)).toThrow(/VITE_API_URL/);
    },
  );

  it("blob: só em img-src (miniatura do chat), nunca em script-src/worker-src", () => {
    const csp = buildCsp("https://api.exemplo.com");
    expect(directive(csp, "img-src")).toContain("blob:");
    expect(directive(csp, "script-src")).not.toContain("blob:");
    expect(directive(csp, "worker-src")).not.toContain("blob:");
  });

  it.each([["http://localhost:8000"], ["http://127.0.0.1:8000"]])("http só para a máquina local: %s", (url) => {
    expect(apiOrigin(url)).toBe(url);
  });

  it("scripts só da própria origem e do Google Identity Services; nada de eval/inline/blob", () => {
    const csp = buildCsp("https://api.exemplo.com");
    expect(directive(csp, "script-src")).toEqual(["'self'", "https://accounts.google.com/gsi/client"]);
    expect(csp).not.toContain("unsafe-eval");
    for (const [name, values] of csp.split("; ").map((d) => [d.split(" ")[0], d.split(" ").slice(1)] as const)) {
      if (name !== "img-src") expect(values, name).not.toContain("blob:");
    }
    expect(directive(csp, "script-src")).not.toContain("'unsafe-inline'");
    expect(directive(csp, "frame-ancestors")).toEqual(["'none'"]);
    expect(directive(csp, "object-src")).toEqual(["'none'"]);
  });
});
