import { useState } from "react";
import type { Summary } from "../api/types";
import { formatHa } from "../lib/format";
import { CLASS_STYLES, rgbaCss } from "./classes";
import type { Layers } from "./MapView";

interface Props {
  summary: Summary;
  layers: Layers;
  onToggle: (layer: keyof Layers) => void;
}

/** Legenda + controle de camadas: cada camada liga/desliga onde é explicada. */
export function Legend({ summary, layers, onToggle }: Props) {
  const areas = summary.results.class_areas;
  // No celular a legenda começa recolhida para não cobrir o mapa
  const [open] = useState(() => window.matchMedia?.("(min-width: 861px)").matches ?? true);
  return (
    <details className="legend" open={open}>
      <summary className="legend__summary">Legenda e camadas</summary>
      <label className="legend__layer">
        <input type="checkbox" checked={layers.polygons} onChange={() => onToggle("polygons")} />
        <span className="legend__swatch legend__swatch--outline" aria-hidden />
        <span className="legend__name">Polígonos candidatos</span>
        <span className="legend__value">{summary.results.candidate_polygons}</span>
      </label>

      <label className="legend__layer">
        <input type="checkbox" checked={layers.classes} onChange={() => onToggle("classes")} />
        <span className="legend__name legend__name--group">Classes do pixel</span>
      </label>
      <ul className="legend__classes" data-off={!layers.classes || undefined}>
        {CLASS_STYLES.map((c) => {
          const entry = areas[c.key];
          if (!entry) return null;
          return (
            <li key={c.key}>
              <span
                className="legend__swatch"
                data-transparent={c.transparent || undefined}
                style={c.transparent ? undefined : { background: rgbaCss(c.rgba) }}
                aria-hidden
              />
              <span className="legend__name">
                {entry.label}
                {c.transparent && <span className="legend__hint"> (sem cor)</span>}
              </span>
              <span className="legend__value">{formatHa(entry.area_ha)}</span>
            </li>
          );
        })}
      </ul>

      <label className="legend__layer">
        <input type="checkbox" checked={layers.rgb} onChange={() => onToggle("rgb")} />
        <span className="legend__name">Cor verdadeira (B04, B03, B02)</span>
      </label>
    </details>
  );
}
