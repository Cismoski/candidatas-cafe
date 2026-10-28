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

  it("URL inválida não injeta nada", () => {
    expect(apiOrigin("javascript:alert(1)")).toBe("null");
    expect(apiOrigin("não é url")).toBe("");
    expect(directive(buildCsp(""), "connect-src")).not.toContain("");
  });

  it("scripts só da própria origem e do Google Identity Services; nada de eval/inline", () => {
    const csp = buildCsp("https://api.exemplo.com");
    expect(directive(csp, "script-src")).toEqual(["'self'", "https://accounts.google.com/gsi/client"]);
    expect(csp).not.toContain("unsafe-eval");
    expect(directive(csp, "script-src")).not.toContain("'unsafe-inline'");
    expect(directive(csp, "frame-ancestors")).toEqual(["'none'"]);
    expect(directive(csp, "object-src")).toEqual(["'none'"]);
  });
});
