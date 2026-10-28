import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { json, makeAnalysis, mockFetch, renderWithProviders, signIn } from "../test/utils";
import { SAMPLES, UploadForm } from "./UploadForm";

const tif = (name = "cena.tif") => new File([new Uint8Array([0x49, 0x49, 0x2a, 0x00, 1, 2])], name);

beforeEach(() => signIn());
afterEach(() => vi.unstubAllGlobals());

function setup() {
  const onCreated = vi.fn();
  renderWithProviders(<UploadForm onCreated={onCreated} />);
  return { onCreated, user: userEvent.setup({ applyAccept: false }) };
}

it("botão de enviar só habilita com a imagem principal", async () => {
  const { user } = setup();
  const submit = screen.getByRole("button", { name: "Processar imagem" });
  expect(submit).toBeDisabled();
  await user.upload(screen.getByLabelText("Imagem principal"), tif());
  expect(await screen.findByText("cena.tif")).toBeInTheDocument();
  expect(submit).toBeEnabled();
});

it("arquivo inválido mostra o erro e não entra no formulário", async () => {
  const { user } = setup();
  await user.upload(screen.getByLabelText("Imagem principal"), new File(["x"], "foto.png"));
  expect(await screen.findByRole("alert")).toHaveTextContent("envie um GeoTIFF");
  expect(screen.getByRole("button", { name: "Processar imagem" })).toBeDisabled();
});

it("envia multipart com Idempotency-Key e avisa quem chamou", async () => {
  const created = makeAnalysis({ status: "pending", summary: null });
  const { calls } = mockFetch({ "POST /analyses": () => json(created, 202) });
  const { user, onCreated } = setup();
  await user.upload(screen.getByLabelText("Imagem principal"), tif());
  await user.upload(screen.getByLabelText("Máscara de qualidade (SCL)"), tif("scl.tif"));
  await user.type(screen.getByLabelText("Nome da análise (opcional)"), "  Talhão A  ");
  await user.click(screen.getByRole("button", { name: "Processar imagem" }));
  await waitFor(() => expect(onCreated).toHaveBeenCalledWith(created));

  const req = calls[0] as (typeof calls)[number];
  expect(req.headers.get("Idempotency-Key")).toMatch(/^[0-9a-f-]{36}$/);
  expect(req.headers.get("Authorization")).toBe("Bearer tok-alice");
  const form = req.body as FormData;
  expect((form.get("primary") as File).name).toBe("cena.tif");
  expect((form.get("scl") as File).name).toBe("scl.tif");
  expect(form.get("secondary")).toBeNull();
  expect(form.get("title")).toBe("Talhão A");
});

it("reenvio após falha de rede reutiliza a MESMA chave (não duplica análise nem cota)", async () => {
  let n = 0;
  const { calls } = mockFetch({
    "POST /analyses": () => {
      n += 1;
      if (n === 1) throw new TypeError("Failed to fetch");
      return json(makeAnalysis({ status: "pending", summary: null }), 202);
    },
  });
  const { user, onCreated } = setup();
  await user.upload(screen.getByLabelText("Imagem principal"), tif());
  await user.click(screen.getByRole("button", { name: "Processar imagem" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/falar com a API/);
  await user.click(screen.getByRole("button", { name: "Processar imagem" }));
  await waitFor(() => expect(onCreated).toHaveBeenCalled());
  const keys = calls.map((r) => r.headers.get("Idempotency-Key"));
  expect(keys[0]).toBe(keys[1]);
});

it("trocar o arquivo gera chave nova", async () => {
  const { calls } = mockFetch({
    "POST /analyses": () => json({ detail: "Imagem principal: são necessárias de 4 a 13 bandas." }, 422),
  });
  const { user } = setup();
  await user.upload(screen.getByLabelText("Imagem principal"), tif("a.tif"));
  await user.click(screen.getByRole("button", { name: "Processar imagem" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("são necessárias de 4 a 13 bandas");
  await user.click(screen.getByRole("button", { name: "Remover" }));
  await user.upload(screen.getByLabelText("Imagem principal"), tif("b.tif"));
  await user.click(screen.getByRole("button", { name: "Processar imagem" }));
  await waitFor(() => expect(calls).toHaveLength(2));
  expect(calls[0]?.headers.get("Idempotency-Key")).not.toBe(calls[1]?.headers.get("Idempotency-Key"));
});

it.each([
  [429, { detail: "Limite de 10 análises por dia atingido." }, /10 análises por dia/, /volta a liberar/],
  [503, { detail: "Fila de processamento cheia. Tente em alguns minutos." }, /Fila/, /Outras análises/],
  [413, { detail: "Arquivo grande demais (máximo 40 MB no total)." }, /40 MB/, /Recorte/],
])("HTTP %i mostra a mensagem da API e o que fazer", async (status, body, msg, action) => {
  mockFetch({ "POST /analyses": () => json(body, status) });
  const { user } = setup();
  await user.upload(screen.getByLabelText("Imagem principal"), tif());
  await user.click(screen.getByRole("button", { name: "Processar imagem" }));
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent(msg);
  expect(alert).toHaveTextContent(action);
});

const TIFF = () => new Response(new Uint8Array([0x49, 0x49, 0x2a, 0x00]));

it("cena de exemplo preenche imagem principal e SCL", async () => {
  mockFetch({ "GET /amostra/imagem_multiespectral.tif": TIFF, "GET /amostra/qualidade_scl.tif": TIFF });
  const { user } = setup();
  await user.click(screen.getByRole("button", { name: "16 ago 2025 (seca)" }));
  expect(await screen.findByText("imagem_multiespectral.tif")).toBeInTheDocument();
  expect(screen.getByText("qualidade_scl.tif")).toBeInTheDocument();
  expect(screen.getByLabelText("Nome da análise (opcional)")).toHaveValue("Guaxupé (MG), 16 ago 2025");
});

it("exemplo de duas datas preenche a segunda data; trocar de exemplo limpa o que sobra", async () => {
  mockFetch({
    "GET /amostra/imagem_multiespectral.tif": TIFF,
    "GET /amostra/qualidade_scl.tif": TIFF,
    "GET /amostra/s2b_20250217_segunda_data.tif": TIFF,
    "GET /amostra/s2b_20250217_imagem.tif": TIFF,
    "GET /amostra/s2b_20250217_scl.tif": TIFF,
  });
  const { user } = setup();
  await user.click(screen.getByRole("button", { name: "Duas datas" }));
  expect(await screen.findByText("s2b_20250217_segunda_data.tif")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "17 fev 2025 (chuva)" }));
  expect(await screen.findByText("s2b_20250217_imagem.tif")).toBeInTheDocument();
  expect(screen.queryByText("s2b_20250217_segunda_data.tif")).toBeNull();
  expect(screen.getByLabelText("Nome da análise (opcional)")).toHaveValue("Guaxupé (MG), 17 fev 2025");
});

it("todo arquivo de exemplo existe em public/ e tem a atribuição ao lado", () => {
  for (const s of SAMPLES) {
    for (const url of Object.values(s.urls)) {
      expect(existsSync(resolve(__dirname, `../../public${url}`)), url).toBe(true);
    }
  }
  for (const f of ["ATRIBUICAO.txt", "s2b_20250217_ATRIBUICAO.txt"]) {
    expect(existsSync(resolve(__dirname, `../../public/amostra/${f}`)), f).toBe(true);
  }
});

it("enquanto o exemplo carrega, arquivos e envio ficam travados", async () => {
  let release: (r: Response) => void = () => {};
  mockFetch({
    "GET /amostra/imagem_multiespectral.tif": () => new Promise<Response>((r) => (release = r)),
    "GET /amostra/qualidade_scl.tif": TIFF,
  });
  const { user } = setup();
  await user.click(screen.getByRole("button", { name: "16 ago 2025 (seca)" }));
  expect(screen.getByLabelText("Imagem principal")).toBeDisabled();
  expect(screen.getByRole("status")).toHaveTextContent("Carregando a cena de exemplo 16 ago 2025 (seca)");
  release(TIFF());
  expect(await screen.findByText("imagem_multiespectral.tif")).toBeInTheDocument();
  expect(screen.getByLabelText("Imagem principal")).toBeEnabled();
});
