import { useMutationState } from "@tanstack/react-query";
import { type FormEvent, type KeyboardEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { keys, useAsk, useChat } from "../api/queries";
import type { ChatMessage } from "../api/types";
import { ErrorNote } from "./ErrorNote";

const MAX = 500;
const SUGGESTIONS = [
  "Qual é o maior polígono?",
  "Qual o NDVI das candidatas?",
  "Como as candidatas foram definidas?",
  "Qual a acurácia?",
];

interface Props {
  analysisId: string;
  /** Ids que existem nesta análise: "nº 1000" numa resposta não vira botão que não leva a nada */
  polygonIds: ReadonlySet<number>;
  onFocusPolygon: (id: number) => void;
}

export function ChatPanel({ analysisId, polygonIds, onFocusPolygon }: Props) {
  const chat = useChat(analysisId);
  const ask = useAsk(analysisId);
  // Pergunta em andamento, inclusive a enviada antes de trocar de aba
  const inFlight = useMutationState({
    filters: { mutationKey: keys.ask(analysisId), status: "pending" },
    select: (m) => m.state.variables as string,
  });
  const pendingText = inFlight.at(-1);
  const pending = pendingText !== undefined;
  const [draft, setDraft] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const count = chat.data?.messages.length ?? 0;

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [count, pending]);

  const send = (text: string) => {
    const message = text.trim();
    if (!message || message.length > MAX || pending) return;
    ask.mutate(message, {
      onSuccess: () => {
        setDraft("");
        inputRef.current?.focus();
      },
    });
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    send(draft);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter envia; Shift+Enter quebra linha
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send(draft);
    }
  };

  if (chat.isPending) return <p className="note" role="status">Carregando a conversa…</p>;
  if (chat.error || !chat.data) return <ErrorNote error={chat.error} onRetry={() => void chat.refetch()} />;

  const messages = chat.data.messages;
  const onlyIntro = messages.length <= 1;
  const remaining = chat.data.remaining_today;

  return (
    <section className="chat" aria-label="Assistente da análise">
      <div className="chat__log" role="log" aria-live="polite" aria-relevant="additions">
        {messages.map((m) => (
          <Message key={m.id} m={m} polygonIds={polygonIds} onFocusPolygon={onFocusPolygon} />
        ))}
        {pending && (
          <>
            <div className="msg msg--user">
              <p className="msg__text">{pendingText}</p>
            </div>
            <p className="msg__pending" role="status">
              Respondendo…
            </p>
          </>
        )}
        <div ref={endRef} />
      </div>

      {onlyIntro && !pending && (
        <div className="chat__suggest" aria-label="Perguntas sugeridas">
          {SUGGESTIONS.map((s) => (
            <button key={s} type="button" className="chip" onClick={() => send(s)}>
              {s}
            </button>
          ))}
        </div>
      )}

      {ask.error && <ErrorNote error={ask.error} />}

      <form className="chat__form" onSubmit={onSubmit}>
        <label className="field__label" htmlFor="chat-input">
          Pergunte sobre esta análise
        </label>
        <textarea
          ref={inputRef}
          id="chat-input"
          className="chat__input"
          rows={2}
          value={draft}
          maxLength={MAX}
          // readOnly e não disabled: disabled tira o foco do teclado no meio da conversa
          readOnly={pending}
          aria-busy={pending}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Ex.: qual a área do polígono nº 3?"
          aria-describedby="chat-help"
        />
        <div className="chat__row">
          <span id="chat-help" className="chat__count">
            {draft.length}/{MAX}
            {remaining != null && `, ${remaining} ${remaining === 1 ? "pergunta restante" : "perguntas restantes"} hoje`}
          </span>
          <button type="submit" className="btn btn--primary" disabled={pending || !draft.trim() || remaining === 0}>
            Perguntar
          </button>
        </div>
      </form>
      <p className="chat__fine">
        As respostas usam só os números deste processamento. Quando o Gemini responde, vão para o Google a pergunta,
        as últimas mensagens desta conversa e o resumo numérico e de método da análise, sem seu nome ou e-mail (plano
        gratuito, que pode usá-los para melhorar produtos); não escreva dados pessoais.
      </p>
    </section>
  );
}

function Message({
  m,
  polygonIds,
  onFocusPolygon,
}: {
  m: ChatMessage;
  polygonIds: ReadonlySet<number>;
  onFocusPolygon: (id: number) => void;
}) {
  if (m.role === "user") {
    return (
      <div className="msg msg--user">
        <p className="msg__text">{m.content}</p>
      </div>
    );
  }
  return (
    <div className="msg msg--assistant">
      <p className="msg__text">{withPolygonLinks(m.content, polygonIds, onFocusPolygon)}</p>
      <p className="msg__meta">
        {m.source === "gemini" ? "Gemini" : "Resposta automática, sem IA"}
        {m.notice && <span className="msg__notice">. {m.notice}</span>}
      </p>
    </div>
  );
}

/**
 * "polígono nº 76" (ou "n° 76", "nº. 76") vira botão que mostra o polígono no mapa,
 * se o id existir. Texto continua texto (sem HTML).
 */
export function withPolygonLinks(
  text: string,
  ids: ReadonlySet<number>,
  onFocus: (id: number) => void,
): ReactNode[] {
  const parts = text.split(/(n[º°]\.?\s?\d{1,5}(?!\d))/g);
  return parts.map((part, i) => {
    const m = /^n[º°]\.?\s?(\d{1,5})$/.exec(part);
    if (!m || !ids.has(Number(m[1]))) return part;
    const id = Number(m[1]);
    return (
      <button key={i} type="button" className="btn btn--link" onClick={() => onFocus(id)} aria-label={`Mostrar polígono ${id} no mapa`}>
        {part}
      </button>
    );
  });
}
