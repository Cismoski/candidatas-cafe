import type { ClassKey } from "../api/types";

/**
 * Cores das classes. DEVEM ser iguais a CLASS_COLORS em
 * backend/app/processing/render.py, pois a sobreposição de classes é um PNG
 * gerado lá (o teste classes.test.ts confere os dois arquivos).
 * A ordem segue a legenda: do que mais importa (candidata) ao contexto.
 */
export interface ClassStyle {
  key: ClassKey;
  rgba: [number, number, number, number];
  /** Classe sem cor na sobreposição: o usuário vê a imagem por baixo. */
  transparent?: boolean;
}

export const CLASS_STYLES: ClassStyle[] = [
  { key: "candidate", rgba: [250, 190, 20, 200] },
  { key: "discarded", rgba: [200, 140, 60, 110] },
  { key: "dense_canopy", rgba: [20, 80, 40, 150] },
  { key: "water", rgba: [40, 110, 220, 170] },
  { key: "low_vegetation", rgba: [0, 0, 0, 0], transparent: true },
  { key: "masked_quality", rgba: [120, 120, 120, 140] },
];

/** Café do MapBiomas (REFERENCE_COLOR em render.py). */
export const REFERENCE_RGBA: [number, number, number, number] = [150, 60, 190, 170];

/** Contorno dos polígonos no PNG de download (OUTLINE em render.py). */
export const OUTLINE_RGB: [number, number, number] = [255, 220, 0];

export const rgbaCss = ([r, g, b, a]: [number, number, number, number]) =>
  `rgba(${r}, ${g}, ${b}, ${(a / 255).toFixed(2)})`;
