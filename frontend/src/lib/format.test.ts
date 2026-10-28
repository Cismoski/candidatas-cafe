import fc from "fast-check";
import { formatDegrees, formatExpiry, formatHa, formatSceneDate } from "./format";

describe("formatExpiry (BVA)", () => {
  const now = Date.parse("2026-10-28T12:00:00Z");
  const at = (ms: number) => new Date(now + ms).toISOString();
  it.each([
    [-1, "expirada"],
    [0, "expirada"],
    [1, "expira em 1 min"],
    [60_000, "expira em 1 min"],
    [60_001, "expira em 2 min"],
    [59 * 60_000, "expira em 59 min"],
    [59 * 60_000 + 1, "expira em 1 h"],
    [24 * 3_600_000, "expira em 24 h"],
  ])("%i ms -> %s", (ms, text) => {
    expect(formatExpiry(at(ms), now)).toBe(text);
  });
  it("data inválida não quebra", () => expect(formatExpiry("lixo", now)).toBe(""));
});

describe("formatDegrees", () => {
  it.each([
    [-21.3064531, "lat", "21°18,4′ S"],
    [-46.7050161, "lon", "46°42,3′ O"],
    [10.5, "lat", "10°30,0′ N"],
    [0, "lon", "0°0,0′ L"],
    [-46.99999, "lon", "47°0,0′ O"], // 59,9994′ arredonda para o grau seguinte
  ])("%f %s -> %s", (v, axis, out) => {
    expect(formatDegrees(v, axis as "lat" | "lon")).toBe(out);
  });

  it("propriedade: o texto reconverte para o valor com erro ≤ 0,05′", () => {
    fc.assert(
      fc.property(fc.double({ min: -180, max: 180, noNaN: true }), (v) => {
        const m = /^(\d+)°(\d+),(\d)′ ([NSLO])$/.exec(formatDegrees(v, "lon"));
        if (!m) return false;
        const minutes = Number(m[2]) + Number(m[3]) / 10;
        if (minutes >= 60) return false;
        const abs = Number(m[1]) + minutes / 60;
        const signed = m[4] === "O" ? -abs : abs;
        return Math.abs(signed - v) * 60 <= 0.05 + 1e-9 || (abs === 0 && Math.abs(v) * 60 <= 0.05);
      }),
    );
  });
});

describe("formatHa e datas", () => {
  it("duas casas no padrão brasileiro", () => {
    expect(formatHa(155.31)).toBe("155,31 ha");
    expect(formatHa(2620.2)).toBe("2.620,20 ha");
  });
  it("data da cena em UTC", () => {
    // 23:30 UTC não pode virar o dia seguinte nem o anterior por fuso
    expect(formatSceneDate("2025-08-16T23:30:00Z")).toMatch(/16 de ago/);
    expect(formatSceneDate(null)).toBe("data desconhecida");
    expect(formatSceneDate("x")).toBe("data desconhecida");
  });
});
