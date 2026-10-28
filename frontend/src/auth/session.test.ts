import fc from "fast-check";
import { clear, fromLogin, isValid, load, save, type StoredSession } from "./session";

const user = { id: "u1", email: "a@b.c", name: "A" };
const at = (expiresAt: number): StoredSession => ({ token: "t", expiresAt, user });

describe("isValid: borda da margem de 30 s (BVA)", () => {
  const now = 1_000_000;
  it.each([
    [now + 30_000 - 1, false],
    [now + 30_000, false], // exatamente na margem: já não usa
    [now + 30_000 + 1, true],
  ])("expiresAt=%i -> %s", (exp, ok) => {
    expect(isValid(at(exp), now)).toBe(ok);
  });
  it("null é inválido", () => expect(isValid(null, now)).toBe(false));
});

describe("fromLogin", () => {
  it("converte expires_in (s) em instante absoluto (ms)", () => {
    const s = fromLogin({ access_token: "t", token_type: "bearer", expires_in: 3600, user }, 1000);
    expect(s).toEqual({ token: "t", expiresAt: 1000 + 3_600_000, user });
  });
});

describe("load/save", () => {
  it("ida e volta", () => {
    const s = at(Date.now() + 3_600_000);
    save(s);
    expect(load()).toEqual(s);
    clear();
    expect(load()).toBeNull();
  });

  it("sessão expirada é descartada do storage", () => {
    save(at(Date.now() - 1));
    expect(load()).toBeNull();
    expect(sessionStorage.getItem("gw.session")).toBeNull();
  });

  it.each([
    ["{não é json"],
    [JSON.stringify({ token: 1, expiresAt: 9e15, user })],
    [JSON.stringify({ token: "t", expiresAt: "amanhã", user })],
    [JSON.stringify({ token: "t", expiresAt: 9e15 })],
    [JSON.stringify({ token: "t", expiresAt: 9e15, user: { id: "u" } })],
  ])("conteúdo corrompido/adulterado vira 'sem sessão': %s", (raw) => {
    sessionStorage.setItem("gw.session", raw);
    expect(load()).toBeNull();
  });

  it("storage que lança (modo privado) não quebra", () => {
    const broken = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
      removeItem: () => {
        throw new Error("blocked");
      },
    } as unknown as Storage;
    expect(load(broken)).toBeNull();
    expect(() => save(at(9e15), broken)).not.toThrow();
    expect(() => clear(broken)).not.toThrow();
  });

  it("propriedade: qualquer JSON arbitrário no storage nunca lança e só aceita sessões bem formadas", () => {
    fc.assert(
      fc.property(fc.jsonValue(), (v) => {
        sessionStorage.setItem("gw.session", JSON.stringify(v));
        const s = load();
        return s === null || (typeof s.token === "string" && isValid(s));
      }),
    );
  });
});
