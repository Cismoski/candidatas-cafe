import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "./App";
import { json, makeAnalysis, mockFetch, renderWithProviders, signIn } from "./test/utils";

vi.mock("./map/MapView", () => ({
  MapView: (p: { analysisId: string | null; polygons: unknown }) => (
    <div data-testid="map" data-analysis={p.analysisId ?? ""} data-polygons={p.polygons ? "sim" : "nao"} />
  ),
}));
vi.mock("./auth/google", () => ({ loadGoogleIdentity: () => new Promise(() => {}) }));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  window.location.hash = "";
});

const a = makeAnalysis();
const item = { ...a, summary: undefined };

it("sem sessão mostra o login", () => {
  renderWithProviders(<App />);
  expect(screen.getByRole("heading", { name: /Onde pode haver café/ })).toBeInTheDocument();
});

it("com sessão abre a análise mais recente com mapa, legenda e atribuição", async () => {
  signIn();
  mockFetch({
    "GET /analyses": () => json([item]),
    [`GET /analyses/${a.id}`]: () => json(a),
    [`GET /analyses/${a.id}/files/overlay-rgb`]: () => new Response(new Blob(["png"])),
    [`GET /analyses/${a.id}/files/overlay-classes`]: () => new Response(new Blob(["png"])),
    [`GET /analyses/${a.id}/files/geojson`]: () => json({ type: "FeatureCollection", features: [] }),
  });
  renderWithProviders(<App />);
  expect(await screen.findByText(/candidatos a café em/)).toBeInTheDocument();
  expect(window.location.hash).toBe(`#/analise/${a.id}`);
  await waitFor(() => expect(screen.getByTestId("map")).toHaveAttribute("data-polygons", "sim"));
  expect(screen.getByText("Legenda e camadas")).toBeInTheDocument();
  expect(screen.getByText(/16 de ago\. de 2025/)).toBeInTheDocument();
  expect(screen.getByText(/Contains modified Copernicus Sentinel data \(2025\)/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Termos" })).toHaveAttribute("href", expect.stringContaining("sentinel.esa.int"));
});

it("sem análises: convida a enviar", async () => {
  signIn();
  mockFetch({ "GET /analyses": () => json([]) });
  renderWithProviders(<App />);
  expect(await screen.findByRole("heading", { name: "Nova análise" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Fechar" })).not.toBeInTheDocument();
});

it("análise em processamento é consultada até concluir (polling)", async () => {
  signIn();
  let n = 0;
  mockFetch({
    "GET /analyses": () => json([{ ...item, status: "processing" }]),
    [`GET /analyses/${a.id}`]: () => {
      n += 1;
      return json(n < 2 ? { ...a, status: "processing", summary: null } : a);
    },
    [`GET /analyses/${a.id}/files/overlay-rgb`]: () => new Response(new Blob(["png"])),
    [`GET /analyses/${a.id}/files/overlay-classes`]: () => new Response(new Blob(["png"])),
    [`GET /analyses/${a.id}/files/geojson`]: () => json({ type: "FeatureCollection", features: [] }),
  });
  renderWithProviders(<App />);
  expect(await screen.findByText(/Calculando reflectância/)).toBeInTheDocument();
  expect(await screen.findByText(/candidatos a café em/, undefined, { timeout: 4000 })).toBeInTheDocument();
});

it("link para análise inexistente/de outro usuário (404) volta para a lista", async () => {
  signIn();
  window.location.hash = "#/analise/22222222-2222-4222-8222-222222222222";
  mockFetch({
    "GET /analyses": () => json([item]),
    "GET /analyses/22222222-2222-4222-8222-222222222222": () => json({ detail: "Análise não encontrada." }, 404),
    [`GET /analyses/${a.id}`]: () => json(a),
    [`GET /analyses/${a.id}/files/overlay-rgb`]: () => new Response(new Blob(["png"])),
    [`GET /analyses/${a.id}/files/overlay-classes`]: () => new Response(new Blob(["png"])),
    [`GET /analyses/${a.id}/files/geojson`]: () => json({ type: "FeatureCollection", features: [] }),
  });
  renderWithProviders(<App />);
  expect(await screen.findByText(/candidatos a café em/)).toBeInTheDocument();
  expect(window.location.hash).toBe(`#/analise/${a.id}`);
});

it("401 da API encerra a sessão e o login explica que expirou", async () => {
  signIn();
  mockFetch({ "GET /analyses": () => json({ detail: "Sessão expirada." }, 401) });
  renderWithProviders(<App />);
  expect(await screen.findByText(/Sua sessão expirou/)).toBeInTheDocument();
  expect(sessionStorage.getItem("gw.session")).toBeNull();
});

it("a sessão expira localmente no horário do token, sem esperar um 401", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  signIn(60_000); // vence em 60 s; a margem é 30 s
  mockFetch({ "GET /analyses": () => json([item]), [`GET /analyses/${a.id}`]: () => json(a) });
  renderWithProviders(<App />);
  expect(screen.getByRole("button", { name: "Sair" })).toBeInTheDocument();
  await act(async () => {
    vi.advanceTimersByTime(31_000);
  });
  expect(await screen.findByText(/Sua sessão expirou/)).toBeInTheDocument();
});

it("sair revoga o token no backend e limpa a sessão", async () => {
  signIn();
  const { calls } = mockFetch({
    "GET /analyses": () => json([]),
    "POST /auth/logout": () => new Response(null, { status: 204 }),
  });
  renderWithProviders(<App />);
  await userEvent.click(screen.getByRole("button", { name: "Sair" }));
  expect(await screen.findByRole("heading", { name: /Onde pode haver café/ })).toBeInTheDocument();
  expect(calls.some((r) => r.method === "POST" && r.url.endsWith("/auth/logout"))).toBe(true);
  expect(sessionStorage.getItem("gw.session")).toBeNull();
  expect(screen.queryByText(/Sua sessão expirou/)).not.toBeInTheDocument();
});
