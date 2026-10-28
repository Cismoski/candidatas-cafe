import { type KeyboardEvent, useId, useMemo, useRef, useState } from "react";
import type { Analysis, DownloadName, Summary } from "../api/types";
import { useDeleteAnalysis } from "../api/queries";
import { useAuth } from "../auth/AuthProvider";
import { saveBlob } from "../lib/files";
import { formatExpiry, formatHa, formatIndex, formatInt, formatPct, formatSigned } from "../lib/format";
import { useNow } from "../lib/useNow";
import { STATUS_LABEL } from "./AnalysisList";
import { ChatPanel } from "./ChatPanel";
import { ErrorNote } from "./ErrorNote";

interface Props {
  analysis: Analysis;
  focusPolygon: number | null;
  onFocusPolygon: (id: number | null) => void;
  onDeleted: () => void;
  onNew: () => void;
}

export function AnalysisDetail({ analysis, focusPolygon, onFocusPolygon, onDeleted, onNew }: Props) {
  const [tab, setTab] = useState<Tab>("result");
  const now = useNow();
  const polygonIds = useMemo(
    () => new Set(analysis.summary?.results.polygons.map((p) => p.id) ?? []),
    [analysis.summary],
  );
  return (
    <article className="detail" aria-labelledby="detail-title">
      <header className="detail__head">
        <h2 id="detail-title" className="detail__title">
          {analysis.title}
        </h2>
        <p className="detail__meta">
          <span className="runs__status" data-status={analysis.status}>
            {STATUS_LABEL[analysis.status]}
          </span>{" "}
          {formatExpiry(analysis.expires_at, now)}
        </p>
      </header>

      {analysis.status === "pending" && (
        <Progress text="Aguardando a vez na fila de processamento." />
      )}
      {analysis.status === "processing" && (
        <Progress text="Calculando reflectância, NDVI, NDWI e SAVI, aplicando as regras e vetorizando os polígonos. Uma cena de 512 × 512 px leva poucos segundos; com a API acordando, até 1 minuto." />
      )}
      {analysis.status === "failed" && (
        <div className="detail__body">
          <ErrorNote message={analysis.error ?? "O processamento falhou."} />
          <button type="button" className="btn btn--primary" onClick={onNew}>
            Enviar outra imagem
          </button>
        </div>
      )}
      {analysis.status === "done" && analysis.summary && (
        <>
          <Tabs value={tab} onChange={setTab} />
          {tab === "result" ? (
            <div className="detail__body" role="tabpanel" id="panel-result" aria-labelledby="tab-result">
            <Result
              id={analysis.id}
              summary={analysis.summary}
              focusPolygon={focusPolygon}
              onFocusPolygon={onFocusPolygon}
            />
            </div>
          ) : (
            <div className="detail__body" role="tabpanel" id="panel-chat" aria-labelledby="tab-chat">
              <ChatPanel analysisId={analysis.id} polygonIds={polygonIds} onFocusPolygon={onFocusPolygon} />
            </div>
          )}
        </>
      )}

      <DeleteAnalysis id={analysis.id} onDeleted={onDeleted} />
    </article>
  );
}

type Tab = "result" | "chat";
const TABS: { id: Tab; label: string }[] = [
  { id: "result", label: "Resultado" },
  { id: "chat", label: "Assistente" },
];

/** Abas no padrão WAI-ARIA: Tab entra na aba ativa, setas/Home/End trocam. */
function Tabs({ value, onChange }: { value: Tab; onChange: (t: Tab) => void }) {
  const refs = useRef<Record<Tab, HTMLButtonElement | null>>({ result: null, chat: null });
  const label = useId();
  const onKey = (e: KeyboardEvent) => {
    const i = TABS.findIndex((t) => t.id === value);
    const next =
      e.key === "ArrowRight" ? (i + 1) % TABS.length
      : e.key === "ArrowLeft" ? (i - 1 + TABS.length) % TABS.length
      : e.key === "Home" ? 0
      : e.key === "End" ? TABS.length - 1
      : null;
    if (next === null) return;
    e.preventDefault();
    const t = (TABS[next] as (typeof TABS)[number]).id;
    onChange(t);
    refs.current[t]?.focus();
  };
  return (
    <div className="tabs" role="tablist" aria-labelledby={label} onKeyDown={onKey}>
      <span id={label} hidden>
        Resultado ou assistente
      </span>
      {TABS.map((t) => (
        <button
          key={t.id}
          ref={(el) => {
            refs.current[t.id] = el;
          }}
          type="button"
          role="tab"
          id={`tab-${t.id}`}
          aria-controls={`panel-${t.id}`}
          aria-selected={value === t.id}
          tabIndex={value === t.id ? 0 : -1}
          onClick={() => onChange(t.id)}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

function Progress({ text }: { text: string }) {
  return (
    <div className="detail__body" role="status">
      <div className="progress" aria-hidden>
        <span />
      </div>
      <p className="detail__progress-text">{text}</p>
    </div>
  );
}

function Result({
  id,
  summary,
  focusPolygon,
  onFocusPolygon,
}: {
  id: string;
  summary: Summary;
  focusPolygon: number | null;
  onFocusPolygon: (id: number | null) => void;
}) {
  const r = summary.results;
  const m = summary.method;
  const largest = [...r.polygons].sort((a, b) => b.area_ha - a.area_ha).slice(0, 8);
  const twoDates = m.mode === "two_dates";

  return (
    <>
      {r.candidate_polygons > 0 ? (
        <p className="figure">
          <span className="figure__value">{formatHa(r.candidate_area_ha)}</span>
          <span className="figure__text">
            candidatos a café em {formatInt(r.candidate_polygons)}{" "}
            {r.candidate_polygons === 1 ? "polígono" : "polígonos"}, {formatPct(r.candidate_fraction_of_analysed)} dos{" "}
            {formatHa(r.analysed_area_ha)} analisados.
          </span>
        </p>
      ) : (
        <div className="note">
          <p>Nenhuma área candidata a café nesta cena.</p>
          <p className="note__more">
            Nenhum conjunto de pixels passou em todas as regras com pelo menos{" "}
            {String((m.parameters.morphology as { min_area_ha?: number })?.min_area_ha ?? 0.5).replace(".", ",")} ha. A
            legenda no mapa mostra para onde foi cada pixel.
          </p>
        </div>
      )}

      <p className="caveat">
        São áreas potenciais, não talhões confirmados: não houve conferência em campo nem amostras de referência,
        então não há acurácia a informar.
      </p>

      <Downloads id={id} />

      {largest.length > 0 && (
        <section className="block">
          <h3 className="block__title">Maiores polígonos</h3>
          <table className="polys">
            <thead>
              <tr>
                <th scope="col">Nº</th>
                <th scope="col">Área</th>
                <th scope="col">NDVI</th>
                {twoDates && <th scope="col">NDVI 2ª data</th>}
              </tr>
            </thead>
            <tbody>
              {largest.map((p) => (
                <tr key={p.id} data-focused={p.id === focusPolygon || undefined}>
                  <td>
                    <button
                      type="button"
                      className="btn btn--link"
                      aria-pressed={p.id === focusPolygon}
                      onClick={() => onFocusPolygon(p.id === focusPolygon ? null : p.id)}
                      aria-label={`Mostrar polígono ${p.id} no mapa`}
                    >
                      {p.id}
                    </button>
                  </td>
                  <td>{formatHa(p.area_ha)}</td>
                  <td>{formatIndex(p.ndvi_mean)}</td>
                  {twoDates && <td>{formatIndex(p.ndvi_other_date_mean)}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <details className="block">
        <summary className="block__title">Como as candidatas foram definidas</summary>
        <p>{m.description}</p>
        <dl className="facts">
          <dt>Limiar de dossel fechado (NDVI)</dt>
          <dd>
            {formatIndex(m.dense_canopy_ndvi_threshold)}, {m.dense_canopy_threshold_source}
          </dd>
          {m.otsu_separability != null && (
            <>
              <dt>Separabilidade de Otsu (η)</dt>
              <dd>{formatIndex(m.otsu_separability)}</dd>
            </>
          )}
          <dt>Máscara de qualidade</dt>
          <dd>{summary.inputs.scl_used ? "SCL aplicada" : "sem SCL (nuvens não removidas)"}</dd>
          <dt>Segunda data</dt>
          <dd>
            {twoDates
              ? `${formatHa(r.temporal_rejected_ha)} rejeitados por mudança; ${formatHa(r.temporal_unverified_ha)} sem verificação (nuvem ou fora da cena)`
              : "não enviada"}
          </dd>
          {twoDates && m.temporal_ndvi_shift != null && (
            <>
              <dt>Variação sazonal descontada (NDVI)</dt>
              <dd>
                {formatSigned(m.temporal_ndvi_shift)}, mediana da vegetação da cena entre as duas datas
              </dd>
            </>
          )}
        </dl>
      </details>

      <details className="block">
        <summary className="block__title">Limitações ({summary.limitations.length})</summary>
        <ul className="limits">
          {summary.limitations.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      </details>
    </>
  );
}

const DOWNLOADS: { name: DownloadName; label: string; file: string }[] = [
  { name: "png", label: "Imagem com polígonos (PNG)", file: "classificacao.png" },
  { name: "geojson", label: "Polígonos (GeoJSON)", file: "candidatas.geojson" },
  { name: "geotiff", label: "Classes (GeoTIFF)", file: "classes.tif" },
];

function Downloads({ id }: { id: string }) {
  const { api } = useAuth();
  const [pending, setPending] = useState<DownloadName | null>(null);
  const [error, setError] = useState<unknown>(null);

  const download = async (d: (typeof DOWNLOADS)[number]) => {
    setPending(d.name);
    setError(null);
    try {
      saveBlob(await api.file(id, d.name), `cafe-${id.slice(0, 8)}-${d.file}`);
    } catch (e) {
      setError(e);
    } finally {
      setPending(null);
    }
  };

  return (
    <section className="block" aria-label="Downloads">
      <h3 className="block__title">Baixar</h3>
      <div className="downloads">
        {DOWNLOADS.map((d) => (
          <button
            key={d.name}
            type="button"
            className="btn btn--outline"
            disabled={pending !== null}
            onClick={() => void download(d)}
          >
            {pending === d.name ? "Baixando…" : d.label}
          </button>
        ))}
      </div>
      {error != null && <ErrorNote error={error} />}
    </section>
  );
}

function DeleteAnalysis({ id, onDeleted }: { id: string; onDeleted: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const del = useDeleteAnalysis();
  return (
    <footer className="detail__foot">
      {confirming ? (
        <p className="detail__confirm">
          Apagar a análise e todos os arquivos dela?{" "}
          <button
            type="button"
            className="btn btn--danger"
            disabled={del.isPending}
            onClick={() => del.mutate(id, { onSuccess: onDeleted })}
          >
            {del.isPending ? "Apagando…" : "Apagar"}
          </button>{" "}
          <button type="button" className="btn btn--quiet" onClick={() => setConfirming(false)}>
            Manter
          </button>
        </p>
      ) : (
        <button type="button" className="btn btn--quiet" onClick={() => setConfirming(true)}>
          Apagar análise
        </button>
      )}
      {del.error && <ErrorNote error={del.error} />}
    </footer>
  );
}
