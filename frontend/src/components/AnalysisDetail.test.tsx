import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Analysis } from "../api/types";
import { API, makeAnalysis, makeSummary, mockFetch, renderWithProviders, signIn } from "../test/utils";
import { AnalysisDetail } from "./AnalysisDetail";

beforeEach(() => signIn());
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

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

it("na fila mostra progresso, sem números nem downloads", () => {
  show(makeAnalysis({ status: "pending", summary: null }));
  expect(screen.getByRole("status")).toHaveTextContent("fila");
  expect(screen.queryByText(/\d ha/)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /GeoJSON/ })).not.toBeInTheDocument();
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

it("duas datas: mostra a variação sazonal descontada, com sinal", () => {
  const s = makeSummary();
  s.method.mode = "two_dates";
  s.method.temporal_ndvi_shift = 0.1461;
  show(makeAnalysis({ summary: s }));
  expect(screen.getByText("Variação sazonal descontada (NDVI)")).toBeInTheDocument();
  expect(screen.getByText(/\+0,15, mediana da vegetação/)).toBeInTheDocument();
});

it("uma data: não mostra variação sazonal", () => {
  const s = makeSummary();
  s.method.temporal_ndvi_shift = null;
  show(makeAnalysis({ summary: s }));
  expect(screen.queryByText("Variação sazonal descontada (NDVI)")).toBeNull();
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
  // jsdom não implementa createObjectURL; spies são restaurados no fim do teste
  URL.createObjectURL ??= () => "";
  URL.revokeObjectURL ??= () => {};
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:x");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
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

it("abas: setas trocam a aba e movem o foco (padrão WAI-ARIA)", async () => {
  show(makeAnalysis());
  const result = screen.getByRole("tab", { name: "Resultado" });
  const chat = screen.getByRole("tab", { name: "Assistente" });
  expect(result).toHaveAttribute("tabindex", "0");
  expect(chat).toHaveAttribute("tabindex", "-1");
  expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", "tab-result");
  result.focus();
  await userEvent.keyboard("{ArrowRight}");
  expect(chat).toHaveFocus();
  expect(chat).toHaveAttribute("aria-selected", "true");
  expect(screen.getByRole("tabpanel")).toHaveAttribute("id", "panel-chat");
  await userEvent.keyboard("{ArrowRight}"); // volta ao início
  expect(result).toHaveFocus();
  await userEvent.keyboard("{End}");
  expect(chat).toHaveFocus();
});

const REF_META = {
  source: "MapBiomas Coleção 11, cobertura e uso da terra (30 m)",
  year: 2025,
  license: "CC BY 4.0",
  info_url: "https://brasil.mapbiomas.org/downloads/mapas-para-download-geotiff/",
  citation: "Souza Jr. et al. (2020)",
  note: "não acurácia",
};

it("comparação com o MapBiomas: números, classes e a ressalva de que não é acurácia", () => {
  const s = makeSummary();
  s.reference = {
    ...REF_META,
    status: "ok",
    compared_area_ha: 2620,
    reference_coffee_ha: 43,
    candidate_ha: 155.31,
    intersection_ha: 7.28,
    iou: 0.0381,
    candidates_on_reference_coffee: 0.0469,
    reference_coffee_in_candidates: 0.1693,
    candidates_by_reference_class: { "Outras lavouras temporárias": 0.3658, Pastagem: 0.3442 },
    reference_coffee_by_our_class: {},
  };
  show(makeAnalysis({ summary: s }));
  const block = screen.getByRole("region", { name: "Comparação com o MapBiomas" });
  expect(block).toHaveTextContent("43,00 ha de café");
  expect(block).toHaveTextContent(/4,7\s?% das candidatas/);
  expect(block).toHaveTextContent("IoU 0,04");
  expect(block).toHaveTextContent(/Pastagem: 34,4\s?%/);
  expect(block).toHaveTextContent("não acurácia");
  expect(screen.getByRole("link", { name: /MapBiomas Coleção 11/ })).toHaveAttribute("href", REF_META.info_url);
});

it("MapBiomas indisponível: diz o motivo e que a análise não depende disso", () => {
  const s = makeSummary();
  s.reference = { ...REF_META, status: "unavailable", reason: "não foi possível ler o MapBiomas" };
  show(makeAnalysis({ summary: s }));
  expect(screen.getByText(/não foi possível ler o MapBiomas\. A análise não depende/)).toBeInTheDocument();
});

it("sem comparação configurada não mostra o bloco", () => {
  const s = makeSummary();
  s.reference = null;
  show(makeAnalysis({ summary: s }));
  expect(screen.queryByRole("region", { name: "Comparação com o MapBiomas" })).toBeNull();
});
