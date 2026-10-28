import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Analysis } from "../api/types";
import { API, makeAnalysis, makeSummary, mockFetch, renderWithProviders, signIn } from "../test/utils";
import { AnalysisDetail } from "./AnalysisDetail";

beforeEach(() => signIn());
afterEach(() => vi.unstubAllGlobals());

function show(a: Analysis, extra: Partial<Parameters<typeof AnalysisDetail>[0]> = {}) {
  const props = {
    analysis: a,
    focusPolygon: null,
    onFocusPolygon: vi.fn(),
    onDeleted: vi.fn(),
    onNew: vi.fn(),
    ...extra,
  };
  renderWithProviders(<AnalysisDetail {...props} />);
  return props;
}

it("na fila e processando mostram progresso, sem números", () => {
  show(makeAnalysis({ status: "pending", summary: null }));
  expect(screen.getByRole("status")).toHaveTextContent("fila");
  expect(screen.queryByText(/ha/)).not.toBeInTheDocument();
});

it("processando explica as etapas", () => {
  show(makeAnalysis({ status: "processing", summary: null }));
  expect(screen.getByRole("status")).toHaveTextContent("NDVI, NDWI e SAVI");
});

it("falha mostra o erro da API e convida a reenviar", async () => {
  const p = show(makeAnalysis({ status: "failed", error: "SCL: esperado GeoTIFF de 1 banda.", summary: null }));
  expect(screen.getByRole("alert")).toHaveTextContent("SCL: esperado GeoTIFF de 1 banda.");
  await userEvent.click(screen.getByRole("button", { name: "Enviar outra imagem" }));
  expect(p.onNew).toHaveBeenCalled();
});

it("concluída: área, número de polígonos, fração e a ressalva de não validação", () => {
  show(makeAnalysis());
  expect(screen.getByText("155,31 ha")).toBeInTheDocument();
  expect(screen.getByText(/em 2 polígonos, 5,9% dos 2.620,20 ha analisados/)).toBeInTheDocument();
  expect(screen.getByText(/não talhões confirmados/)).toBeInTheDocument();
  expect(screen.getByText(/não há acurácia/)).toBeInTheDocument();
});

it("singular para 1 polígono", () => {
  show(makeAnalysis({ summary: makeSummary({ candidate_polygons: 1 }) }));
  expect(screen.getByText(/em 1 polígono,/)).toBeInTheDocument();
});

it("sem candidatas: estado vazio explicado", () => {
  show(makeAnalysis({ summary: makeSummary({ candidate_polygons: 0, candidate_area_ha: 0, polygons: [] }) }));
  expect(screen.getByText("Nenhuma área candidata a café nesta cena.")).toBeInTheDocument();
  expect(screen.getByText(/pelo menos 0,5 ha/)).toBeInTheDocument();
  expect(screen.queryByText("Maiores polígonos")).not.toBeInTheDocument();
});

it("tabela ordena por área e foca o polígono no mapa", async () => {
  const p = show(makeAnalysis());
  const rows = screen.getAllByRole("row").slice(1);
  expect(rows[0]).toHaveTextContent("8,33 ha");
  await userEvent.click(screen.getByRole("button", { name: "Mostrar polígono 2 no mapa" }));
  expect(p.onFocusPolygon).toHaveBeenCalledWith(2);
});

it("duas datas: coluna de NDVI da 2ª data e números temporais", () => {
  const s = makeSummary({ temporal_rejected_ha: 3.5 });
  s.method.mode = "two_dates";
  show(makeAnalysis({ summary: s }));
  expect(screen.getByRole("columnheader", { name: "NDVI 2ª data" })).toBeInTheDocument();
  expect(screen.getByText(/3,50 ha rejeitados por mudança/)).toBeInTheDocument();
});

it("limitações do processamento aparecem (não escondidas)", () => {
  show(makeAnalysis());
  expect(screen.getByText("Limitações (2)")).toBeInTheDocument();
  expect(screen.getByText("Sem segunda data.")).toBeInTheDocument();
});

it("download autenticado salva o arquivo com nome", async () => {
  const { calls } = mockFetch({
    [`GET /analyses/${makeAnalysis().id}/files/geojson`]: () => new Response('{"type":"FeatureCollection"}'),
  });
  const createObjectURL = vi.fn(() => "blob:x");
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() }));
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  show(makeAnalysis());
  await userEvent.click(screen.getByRole("button", { name: "Polígonos (GeoJSON)" }));
  await waitFor(() => expect(click).toHaveBeenCalled());
  expect(calls[0]?.url).toBe(`${API}/analyses/${makeAnalysis().id}/files/geojson`);
  expect(calls[0]?.headers.get("Authorization")).toBe("Bearer tok-alice");
  expect((click.mock.contexts[0] as HTMLAnchorElement).download).toMatch(/^cafe-11111111-candidatas\.geojson$/);
});

it("apagar pede confirmação na própria tela", async () => {
  const { calls } = mockFetch({ [`DELETE /analyses/${makeAnalysis().id}`]: () => new Response(null, { status: 204 }) });
  const p = show(makeAnalysis());
  await userEvent.click(screen.getByRole("button", { name: "Apagar análise" }));
  await userEvent.click(screen.getByRole("button", { name: "Manter" }));
  expect(calls).toHaveLength(0);
  await userEvent.click(screen.getByRole("button", { name: "Apagar análise" }));
  await userEvent.click(screen.getByRole("button", { name: "Apagar" }));
  await waitFor(() => expect(p.onDeleted).toHaveBeenCalled());
  expect(calls[0]?.method).toBe("DELETE");
});
