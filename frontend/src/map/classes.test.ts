import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { CLASS_STYLES, OUTLINE_RGB } from "./classes";

/**
 * A sobreposição de classes é um PNG pintado no backend. Se as cores daqui
 * divergirem de render.py, a legenda mente sobre o mapa.
 */
const render = readFileSync(resolve(__dirname, "../../../backend/app/processing/render.py"), "utf-8");

const BACKEND_NAME: Record<string, string> = {
  candidate: "CANDIDATE",
  discarded: "DISCARDED",
  dense_canopy: "DENSE_CANOPY",
  water: "WATER",
  low_vegetation: "LOW_VEGETATION",
  masked_quality: "MASKED_QUALITY",
};

describe("cores da legenda = cores do PNG do backend", () => {
  it.each(CLASS_STYLES.map((c) => [c.key, c.rgba] as const))("%s", (key, rgba) => {
    const m = new RegExp(`LandClass\\.${BACKEND_NAME[key]}: \\(([^)]*)\\)`).exec(render);
    expect(m, `classe ${key} ausente em render.py`).not.toBeNull();
    expect((m as RegExpExecArray)[1]?.split(",").map((v) => Number(v.trim()))).toEqual(rgba);
  });

  it("contorno", () => {
    const m = /OUTLINE = \(([^)]*)\)/.exec(render);
    expect(m?.[1]?.split(",").map((v) => Number(v.trim()))).toEqual(OUTLINE_RGB);
  });
});
