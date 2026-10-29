import { act, screen, waitFor } from "@testing-library/react";
import { App } from "../App";
import { json, mockFetch, renderWithProviders } from "../test/utils";

let callback: ((r: { credential: string }) => void) | null = null;
const renderButton = vi.fn();
let fail = false;

vi.mock("../auth/google", () => ({
  loadGoogleIdentity: () =>
    fail
      ? Promise.reject(new Error("gsi"))
      : Promise.resolve({
          initialize: (cfg: { callback: (r: { credential: string }) => void; client_id: string }) => {
            callback = cfg.callback;
          },
          renderButton,
          disableAutoSelect: vi.fn(),
        }),
}));
vi.mock("../map/MapView", () => ({ MapView: () => <div data-testid="map" /> }));

beforeEach(() => {
  vi.stubEnv("VITE_GOOGLE_CLIENT_ID", "cliente.apps.googleusercontent.com");
  callback = null;
  fail = false;
  renderButton.mockClear();
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

it("o ID token do Google vai ao backend; a sessão do backend abre a área logada", async () => {
  const { calls } = mockFetch({
    "POST /auth/google": () =>
      json({
        access_token: "jwt-da-api",
        token_type: "bearer",
        expires_in: 3600,
        user: { id: "u1", email: "alice@example.com", name: "Alice" },
      }),
    "GET /analyses": () => json([]),
  });
  renderWithProviders(<App />);
  await waitFor(() => expect(renderButton).toHaveBeenCalled());
  await act(async () => callback?.({ credential: "id-token-do-google" }));
  expect(await screen.findByText("Alice")).toBeInTheDocument();
  const login = calls.find((c) => c.url.endsWith("/auth/google"));
  expect(JSON.parse(login?.body as string)).toEqual({ credential: "id-token-do-google" });
  expect(JSON.parse(sessionStorage.getItem("gw.session") as string).token).toBe("jwt-da-api");
  // chamadas seguintes usam o JWT da API, nunca o token do Google
  const list = calls.find((c) => c.url.endsWith("/analyses"));
  expect(list?.headers.get("Authorization")).toBe("Bearer jwt-da-api");
});

it("login recusado pelo backend mostra o motivo e continua na tela de login", async () => {
  mockFetch({ "POST /auth/google": () => json({ detail: "Login com Google inválido." }, 401) });
  renderWithProviders(<App />);
  await waitFor(() => expect(renderButton).toHaveBeenCalled());
  await act(async () => callback?.({ credential: "id-token-ruim" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Login com Google inválido.");
  expect(sessionStorage.getItem("gw.session")).toBeNull();
});

it("script do Google bloqueado: mensagem acionável", async () => {
  fail = true;
  renderWithProviders(<App />);
  expect(await screen.findByRole("alert")).toHaveTextContent(/bloqueadores/);
});

it("API dormindo (502 do proxy): a tela avisa que o servidor está acordando", async () => {
  mockFetch({ "GET /health": () => new Response("Bad Gateway", { status: 502 }) });
  renderWithProviders(<App />);
  expect(await screen.findByText(/servidor gratuito estava dormindo/)).toBeInTheDocument();
});

it("API acordada: nenhum aviso de servidor", async () => {
  const { calls } = mockFetch({ "GET /health": () => json({ status: "ok" }) });
  renderWithProviders(<App />);
  await waitFor(() => expect(calls.some((c) => c.url.endsWith("/health"))).toBe(true));
  await act(async () => {});
  expect(screen.queryByText(/servidor gratuito estava dormindo/)).toBeNull();
  expect(calls.find((c) => c.url.endsWith("/health"))?.headers.get("Authorization")).toBeNull();
});
