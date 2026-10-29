import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { FeatureCollection } from "geojson";
import type { AnalysisItem } from "../api/types";
import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { ApiError } from "../api/client";
import { keys, shouldRetry, useAnalyses, useAnalysis, useAnalysisFile } from "../api/queries";
import { useAuth } from "../auth/AuthProvider";
import { Legend } from "../map/Legend";
import { MapSheet } from "../map/MapSheet";
import type { Layers, ViewBounds } from "../map/MapView";
import { AnalysisDetail } from "./AnalysisDetail";
import { AnalysisList } from "./AnalysisList";
import { ErrorNote } from "./ErrorNote";
import { UploadForm } from "./UploadForm";

// MapLibre (~800 kB) num chunk separado: o painel aparece antes do mapa
const MapView = lazy(() => import("../map/MapView").then((m) => ({ default: m.MapView })));

const HASH = /^#\/analise\/([0-9a-f-]{36})$/;
const readHash = () => HASH.exec(window.location.hash)?.[1] ?? null;

export function Workspace() {
  const { user, logout, api } = useAuth();
  const qc = useQueryClient();
  const list = useAnalyses();
  const [selectedId, setSelectedId] = useState<string | null>(readHash);
  const [uploading, setUploading] = useState(false);
  const [focusPolygon, setFocusPolygon] = useState<number | null>(null);
  const [layers, setLayers] = useState<Layers>({ rgb: true, classes: false, polygons: true, reference: false });
  const [sheetOpen, setSheetOpen] = useState(true);
  const [view, setView] = useState<ViewBounds | null>(null);

  const select = useCallback((id: string | null) => {
    setSelectedId(id);
    setFocusPolygon(null);
    setUploading(false);
    const hash = id ? `#/analise/${id}` : "";
    if (window.location.hash !== hash) history.replaceState(null, "", hash || window.location.pathname);
  }, []);

  useEffect(() => {
    const onHash = () => select(readHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [select]);

  // Sem seleção: abre a mais recente; sem nenhuma análise: convida a enviar
  const items = list.data;
  useEffect(() => {
    if (!items || selectedId) return;
    if (items[0]) select(items[0].id);
    else setUploading(true);
  }, [items, selectedId, select]);

  const detail = useAnalysis(selectedId);
  // Análise apagada (em outra aba), expirada ou de outro usuário (link antigo).
  // Tira a análise do cache da lista ANTES de desmarcar: senão a seleção
  // automática escolheria a mesma análise de novo, em loop.
  useEffect(() => {
    if (!(detail.error instanceof ApiError && detail.error.kind === "not_found") || !selectedId) return;
    const gone = selectedId;
    qc.setQueryData<AnalysisItem[]>(keys.list, (l) => l?.filter((x) => x.id !== gone));
    qc.removeQueries({ queryKey: keys.one(gone) });
    void qc.invalidateQueries({ queryKey: keys.list, exact: true });
    select(null);
  }, [detail.error, selectedId, select, qc]);

  const analysis = detail.data;
  const done = analysis?.status === "done" && analysis.summary != null;
  const id = analysis?.id ?? "";
  const rgb = useAnalysisFile(id, "overlay-rgb", done);
  const classes = useAnalysisFile(id, "overlay-classes", done);
  // só quando a camada for ligada: é opcional e quase sempre fica desligada
  const reference = useAnalysisFile(
    id,
    "overlay-reference",
    done && !!detail.data?.summary?.map.reference_overlay && layers.reference,
  );
  const polygons = useQuery({
    queryKey: [...keys.file(id, "geojson"), "parsed"],
    queryFn: async ({ signal }) =>
      JSON.parse(await (await api.file(id, "geojson", signal)).text()) as FeatureCollection,
    enabled: done,
    staleTime: Number.POSITIVE_INFINITY,
    retry: shouldRetry,
  });
  const summary = done ? analysis.summary : null;
  const layerError = rgb.error ?? classes.error ?? polygons.error ?? reference.error;

  const toggle = (k: keyof Layers) => setLayers((l) => ({ ...l, [k]: !l[k] }));

  return (
    <div className="ws">
      <header className="bar">
        <p className="bar__brand">
          Candidatas a <span className="bar__product">café</span>
        </p>
        <p className="bar__user" title={user?.email}>
          {user?.name ?? user?.email}
        </p>
        <button type="button" className="btn btn--quiet" onClick={() => void logout()}>
          Sair
        </button>
      </header>

      <aside className="panel" data-open={sheetOpen || undefined} aria-label="Análises">
        <button
          type="button"
          className="panel__handle"
          aria-expanded={sheetOpen}
          onClick={() => setSheetOpen((o) => !o)}
        >
          <span className="panel__grip" aria-hidden />
          <span className="panel__peek">
            {summary
              ? `${analysis?.title}: ${summary.results.candidate_area_ha.toLocaleString("pt-BR", { minimumFractionDigits: 2 })} ha candidatos`
              : sheetOpen
                ? "Recolher painel"
                : "Abrir painel"}
          </span>
        </button>

        <div className="panel__scroll">
          {uploading ? (
            <UploadForm
              onCreated={(a) => select(a.id)}
              onCancel={items && items.length > 0 ? () => setUploading(false) : undefined}
            />
          ) : (
            <button type="button" className="btn btn--primary panel__new" onClick={() => setUploading(true)}>
              Nova análise
            </button>
          )}

          {list.isPending && <p className="note" role="status">Carregando suas análises…</p>}
          {list.error != null && <ErrorNote error={list.error} onRetry={() => void list.refetch()} />}

          {analysis && !uploading && (
            <AnalysisDetail
              key={analysis.id}
              analysis={analysis}
              focusPolygon={focusPolygon}
              onFocusPolygon={(pid) => {
                setFocusPolygon(pid);
                // no celular o painel cobre o mapa: recolhe para mostrar o polígono
                if (pid !== null && !window.matchMedia?.("(min-width: 861px)").matches) setSheetOpen(false);
              }}
              onDeleted={() => select(null)}
              onNew={() => setUploading(true)}
            />
          )}
          {selectedId && detail.isPending && <p className="note" role="status">Carregando a análise…</p>}
          {detail.error != null && !(detail.error instanceof ApiError && detail.error.kind === "not_found") && (
            <ErrorNote error={detail.error} onRetry={() => void detail.refetch()} />
          )}

          {items && items.length > 0 && (
            <section className="block">
              <h2 className="block__title">Suas análises</h2>
              <AnalysisList items={items} selectedId={selectedId} onSelect={select} />
            </section>
          )}
        </div>
      </aside>

      <main className="stage">
        <MapSheet summary={summary} view={view}>
          <Suspense fallback={<p className="map-canvas__fail">Carregando o mapa…</p>}>
            <MapView
              analysisId={summary ? id : null}
              coordinates={summary?.map.coordinates ?? null}
              rgb={rgb.data ?? null}
              classes={classes.data ?? null}
              reference={reference.data ?? null}
              polygons={polygons.data ?? null}
              layers={layers}
              focusPolygon={focusPolygon}
              onSelectPolygon={setFocusPolygon}
              onViewChange={setView}
            />
          </Suspense>
          {summary && <Legend summary={summary} layers={layers} onToggle={toggle} />}
          {layerError != null && (
            <div className="stage__alert">
              <ErrorNote error={layerError} />
            </div>
          )}
        </MapSheet>
      </main>
    </div>
  );
}
