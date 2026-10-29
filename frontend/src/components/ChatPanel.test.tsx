import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import type { ChatMessage } from "../api/types";
import { json, mockFetch, png, renderWithProviders, signIn } from "../test/utils";
import { ChatPanel } from "./ChatPanel";

const ID = "11111111-1111-4111-8111-111111111111";
const PATH = `/analyses/${ID}/chat`;

const msg = (over: Partial<ChatMessage>): ChatMessage => ({
  id: 1,
  role: "assistant",
  content: "",
  source: "automatica",
  notice: null,
  created_at: "2026-10-28T20:00:00+00:00",
  ...over,
});
const INTRO = msg({ id: 0, content: "Encontrei 90 polígonos candidatos somando 155,31 ha." });

beforeEach(() => signIn());
afterEach(() => vi.unstubAllGlobals());

function show(onFocusPolygon = vi.fn()) {
  renderWithProviders(<ChatPanel analysisId={ID} polygonIds={new Set([3, 40, 76])} onFocusPolygon={onFocusPolygon} />);
  return { onFocusPolygon, user: userEvent.setup() };
}

it("abre apresentando a classificação, com sugestões", async () => {
  mockFetch({ [`GET ${PATH}`]: () => json({ messages: [INTRO], remaining_today: null }) });
  show();
  expect(await screen.findByText(/90 polígonos candidatos/)).toBeInTheDocument();
  expect(screen.getByText("Resposta automática, sem IA")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Qual a acurácia?" })).toBeInTheDocument();
});

it("envia a pergunta, mostra 'respondendo' e a resposta com a origem", async () => {
  let release: (r: Response) => void = () => {};
  const { calls } = mockFetch({
    [`GET ${PATH}`]: () => json({ messages: [INTRO], remaining_today: null }),
    [`POST ${PATH}`]: () => new Promise<Response>((r) => (release = r)),
  });
  const { user } = show();
  await user.type(await screen.findByLabelText("Pergunte sobre esta análise"), "qual o maior?{Enter}");
  expect(await screen.findByText("Respondendo…")).toBeInTheDocument();
  // a pergunta aparece no histórico enquanto a resposta não chega
  expect(within(screen.getByRole("log")).getByText("qual o maior?")).toBeInTheDocument();
  release(
    json({
      messages: [
        msg({ id: 1, role: "user", content: "qual o maior?", source: null }),
        msg({ id: 2, content: "O maior é o nº 76, com 8,33 ha.", source: "gemini" }),
      ],
      remaining_today: 29,
    }),
  );
  expect(await screen.findByText("Gemini")).toBeInTheDocument();
  expect(screen.getByText(/29 perguntas restantes hoje/)).toBeInTheDocument();
  expect(screen.getByLabelText("Pergunte sobre esta análise")).toHaveValue("");
  const post = calls.find((c) => c.method === "POST");
  expect(JSON.parse(post?.body as string)).toEqual({ message: "qual o maior?" });
  expect(post?.headers.get("Authorization")).toBe("Bearer tok-alice");
});

it("Shift+Enter quebra linha sem enviar; vazio não envia", async () => {
  const { calls } = mockFetch({ [`GET ${PATH}`]: () => json({ messages: [INTRO], remaining_today: null }) });
  const { user } = show();
  const box = await screen.findByLabelText("Pergunte sobre esta análise");
  await user.type(box, "   {Enter}");
  await user.type(box, "linha{Shift>}{Enter}{/Shift}");
  expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  expect(box).toHaveValue("   linha\n");
});

it("o campo respeita o limite de 500 caracteres (BVA)", async () => {
  mockFetch({ [`GET ${PATH}`]: () => json({ messages: [INTRO], remaining_today: null }) });
  show();
  const box = await screen.findByLabelText("Pergunte sobre esta análise");
  expect(box).toHaveAttribute("maxlength", "500");
  expect(screen.getByText(/^0\/500/)).toBeInTheDocument();
});

it("resposta automática mostra o aviso do motivo", async () => {
  mockFetch({
    [`GET ${PATH}`]: () =>
      json({
        messages: [
          INTRO,
          msg({ id: 2, content: "Não há acurácia a informar.", notice: "O assistente de IA está instável." }),
        ],
        remaining_today: null,
      }),
  });
  show();
  expect(await screen.findByText(/O assistente de IA está instável/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Qual a acurácia?" })).not.toBeInTheDocument();
});

it("cota esgotada mostra a mensagem da API, mantém a conversa e relê a cota", async () => {
  let remaining = 1; // a outra aba gastou a última pergunta: o servidor sabe, a tela não
  mockFetch({
    [`GET ${PATH}`]: () => json({ messages: [INTRO], remaining_today: remaining }),
    [`POST ${PATH}`]: () => {
      remaining = 0;
      return json({ detail: "Limite de 30 perguntas por dia atingido." }, 429);
    },
  });
  const { user } = show();
  await user.click(await screen.findByRole("button", { name: "Qual é o maior polígono?" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("30 perguntas por dia");
  expect(screen.getByText(/90 polígonos candidatos/)).toBeInTheDocument();
  expect(await screen.findByText(/0 perguntas restantes hoje/)).toBeInTheDocument();
});

it("limite por minuto (429) não zera a cota do dia", async () => {
  mockFetch({
    [`GET ${PATH}`]: () => json({ messages: [INTRO], remaining_today: 12 }),
    [`POST ${PATH}`]: () => json({ detail: "Muitas requisições (10 per 1 minute). Aguarde e tente de novo." }, 429),
  });
  const { user } = show();
  await user.click(await screen.findByRole("button", { name: "Qual é o maior polígono?" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Aguarde");
  expect(screen.getByText(/12 perguntas restantes hoje/)).toBeInTheDocument();
  expect(screen.queryByText(/0 perguntas restantes hoje/)).toBeNull();
});

it("se a releitura após um 429 falhar, o histórico continua na tela", async () => {
  let gets = 0;
  mockFetch({
    [`GET ${PATH}`]: () => (gets++ === 0 ? json({ messages: [INTRO], remaining_today: 12 }) : json({ detail: "x" }, 429)),
    [`POST ${PATH}`]: () => json({ detail: "Muitas requisições. Aguarde e tente de novo." }, 429),
  });
  const { user } = show();
  await user.click(await screen.findByRole("button", { name: "Qual é o maior polígono?" }));
  await waitFor(() => expect(gets).toBe(2));
  expect(screen.getByText(/90 polígonos candidatos/)).toBeInTheDocument();
  expect(screen.getByLabelText("Pergunte sobre esta análise")).toBeInTheDocument();
});

it("contador de cota aparece antes da primeira pergunta; com cota zerada não envia", async () => {
  mockFetch({ [`GET ${PATH}`]: () => json({ messages: [INTRO], remaining_today: 0 }) });
  const { user } = show();
  const input = await screen.findByLabelText("Pergunte sobre esta análise");
  expect(screen.getByText(/0 perguntas restantes hoje/)).toBeInTheDocument();
  await user.type(input, "qual a área?");
  expect(screen.getByRole("button", { name: "Perguntar" })).toBeDisabled();
  expect(screen.queryByRole("button", { name: "Qual é o maior polígono?" })).toBeDisabled();
});

function WithTabs() {
  const [chat, setChat] = useState(true);
  return (
    <>
      <button type="button" onClick={() => setChat((v) => !v)}>
        trocar aba
      </button>
      {chat && <ChatPanel analysisId={ID} polygonIds={new Set()} onFocusPolygon={() => {}} />}
    </>
  );
}

it("pergunta em andamento sobrevive à troca de aba e não pode ser reenviada", async () => {
  let release: (r: Response) => void = () => {};
  const { calls } = mockFetch({
    [`GET ${PATH}`]: () => json({ messages: [INTRO], remaining_today: 5 }),
    [`POST ${PATH}`]: () => new Promise<Response>((r) => (release = r)),
  });
  renderWithProviders(<WithTabs />);
  const user = userEvent.setup();
  const input = await screen.findByLabelText("Pergunte sobre esta análise");
  await user.type(input, "qual a área?{Enter}");
  expect(input).toHaveFocus(); // readOnly, não disabled: o foco fica no campo
  expect(input).toHaveAttribute("aria-busy", "true");
  // sai e volta para a aba: o painel é desmontado e montado de novo
  await user.click(screen.getByRole("button", { name: "trocar aba" }));
  await user.click(screen.getByRole("button", { name: "trocar aba" }));
  expect(await screen.findByText("Respondendo…")).toBeInTheDocument();
  expect(within(screen.getByRole("log")).getByText("qual a área?")).toBeInTheDocument();
  await user.type(screen.getByLabelText("Pergunte sobre esta análise"), "de novo{Enter}");
  expect(calls.filter((c) => c.method === "POST")).toHaveLength(1);
  release(
    json({
      messages: [
        msg({ id: 1, role: "user", content: "qual a área?", source: null }),
        msg({ id: 2, content: "155,31 ha." }),
      ],
      remaining_today: 4,
    }),
  );
  expect(await screen.findByText(/4 perguntas restantes hoje/)).toBeInTheDocument();
  expect(screen.queryByText("Respondendo…")).toBeNull();
});

it("'nº 76' na resposta foca o polígono no mapa", async () => {
  mockFetch({
    [`GET ${PATH}`]: () => json({ messages: [msg({ content: "O maior é o nº 76 e depois o nº 3." })], remaining_today: null }),
  });
  const { onFocusPolygon, user } = show();
  await user.click(await screen.findByRole("button", { name: "Mostrar polígono 76 no mapa" }));
  expect(onFocusPolygon).toHaveBeenCalledWith(76);
  await user.click(screen.getByRole("button", { name: "Mostrar polígono 3 no mapa" }));
  expect(onFocusPolygon).toHaveBeenLastCalledWith(3);
});

it("variações de 'nº' viram link; id inexistente continua texto", async () => {
  mockFetch({
    [`GET ${PATH}`]: () =>
      json({ messages: [msg({ content: "Veja o n° 40 e o nº. 3; não existe nº 1000." })], remaining_today: null }),
  });
  show();
  expect(await screen.findByRole("button", { name: "Mostrar polígono 40 no mapa" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Mostrar polígono 3 no mapa" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Mostrar polígono 1000 no mapa" })).toBeNull();
});

it("conteúdo do modelo é texto, nunca HTML", async () => {
  mockFetch({
    [`GET ${PATH}`]: () => json({ messages: [msg({ content: '<img src=x onerror="alert(1)">' })], remaining_today: null }),
  });
  show();
  expect(await screen.findByText('<img src=x onerror="alert(1)">')).toBeInTheDocument();
  expect(document.querySelector("img")).toBeNull();
});

it("análise não concluída (409) explica", async () => {
  mockFetch({ [`GET ${PATH}`]: () => json({ detail: "O assistente fica disponível quando a análise terminar." }, 409) });
  show();
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("quando a análise terminar"));
});

it("mostra a imagem da classificação no topo da conversa e libera a URL ao sair", async () => {
  // jsdom não implementa createObjectURL; spies são restaurados no fim do teste
  URL.createObjectURL ??= () => "";
  URL.revokeObjectURL ??= () => {};
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:classificacao");
  const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  mockFetch({
    [`GET ${PATH}`]: () => json({ messages: [INTRO], remaining_today: null }),
    [`GET /analyses/${ID}/files/png`]: png,
  });
  const { unmount } = renderWithProviders(
    <ChatPanel analysisId={ID} polygonIds={new Set()} onFocusPolygon={vi.fn()} />,
  );
  expect(await screen.findByText("Carregando a imagem da classificação…")).toBeInTheDocument();
  const img = await screen.findByRole("img", { name: /polígonos candidatos a café/ });
  expect(img).toHaveAttribute("src", "blob:classificacao");
  // fora da região aria-live, para o leitor de tela não anunciar o carregamento
  expect(within(screen.getByRole("log")).queryByRole("img")).toBeNull();
  unmount();
  expect(revoke).toHaveBeenCalledWith("blob:classificacao");
});

it("sem a imagem, a conversa segue e avisa", async () => {
  mockFetch({
    [`GET ${PATH}`]: () => json({ messages: [INTRO], remaining_today: null }),
    [`GET /analyses/${ID}/files/png`]: () => json({ detail: "x" }, 404),
  });
  show();
  expect(await screen.findByText("Não foi possível carregar a imagem da classificação.")).toBeInTheDocument();
  expect(screen.getByText(/90 polígonos candidatos/)).toBeInTheDocument();
});
