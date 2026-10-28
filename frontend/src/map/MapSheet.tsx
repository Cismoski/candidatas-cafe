import type { ReactNode } from "react";
import type { Summary } from "../api/types";
import { formatDegrees, formatSceneDate } from "../lib/format";
import type { ViewBounds } from "./MapView";

export const COPERNICUS_TERMS =
  "https://sentinel.esa.int/documents/247904/690755/Sentinel_Data_Legal_Notice";

/**
 * Moldura do mapa no estilo da margem de uma carta topográfica: coordenadas
 * das bordas da vista atual (como os graus nas margens de uma folha), data de
 * aquisição, identificador da cena e atribuição. É a parte da interface que
 * diz "de onde vem este dado" o tempo todo.
 */
export function MapSheet({
  summary,
  view,
  children,
}: {
  summary: Summary | null;
  view: ViewBounds | null;
  children: ReactNode;
}) {
  const c = view;
  const [west, south, east, north] = view ?? [0, 0, 0, 0];
  const primary = summary?.inputs.primary;

  return (
    <figure className="sheet">
      <div className="sheet__edge sheet__edge--top" aria-hidden={!c}>
        {c && (
          <>
            <span>{formatDegrees(west, "lon")}</span>
            <span>{formatDegrees(east, "lon")}</span>
          </>
        )}
      </div>
      <div className="sheet__edge sheet__edge--left" aria-hidden={!c}>
        {c && (
          <>
            <span>{formatDegrees(north, "lat")}</span>
            <span>{formatDegrees(south, "lat")}</span>
          </>
        )}
      </div>
      <div className="sheet__map">{children}</div>
      <figcaption className="sheet__caption">
        {primary ? (
          <>
            <span className="sheet__date">
              Sentinel-2, <time dateTime={primary.acquired_utc ?? undefined}>{formatSceneDate(primary.acquired_utc)}</time>
              {summary?.inputs.secondary && (
                <>
                  {" "}e{" "}
                  <time dateTime={summary.inputs.secondary.acquired_utc ?? undefined}>
                    {formatSceneDate(summary.inputs.secondary.acquired_utc)}
                  </time>
                </>
              )}
            </span>
            {primary.source_item && <span className="sheet__scene">{primary.source_item}</span>}
            <span className="sheet__crs">
              {primary.crs}, pixel {primary.pixel_size_m[0]} m
            </span>
          </>
        ) : (
          <span className="sheet__date">Nenhuma cena carregada. Região de Guaxupé (MG).</span>
        )}
        <span className="sheet__credit">
          {summary?.attribution ?? "Contains modified Copernicus Sentinel data (2025)"}.{" "}
          <a href={COPERNICUS_TERMS} target="_blank" rel="noreferrer noopener">
            Termos
          </a>
        </span>
      </figcaption>
    </figure>
  );
}
