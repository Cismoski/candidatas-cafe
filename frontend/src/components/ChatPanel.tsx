import { type FormEvent, type KeyboardEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { useAsk, useChat } from "../api/queries";
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
  onFocusPolygon: (id: number) => void;
}

export function ChatPanel({ analysisId, onFocusPolygon }: Props) {
  const chat = useChat(analysisId);
  const ask = useAsk(analysisId);
  const [draft, setDraft] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const count = chat.data?.messages.length ?? 0;

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [count, ask.isPending]);

  const send = (text: string) => {
    const message = text.trim();
    if (!message || message.length > MAX || ask.isPending) return;
    ask.mutate(message, { onSuccess: () => setDraft("") });
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
          <Message key={m.id} m={m} onFocusPolygon={onFocusPolygon} />
        ))}
        {ask.isPending && (
          <>
            <div className="msg msg--user">
              <p className="msg__text">{ask.variables}</p>
            </div>
            <p className="msg__pending" role="status">
              Respondendo…
            </p>
          </>
        )}
        <div ref={endRef} />
      </div>

      {onlyIntro && !ask.isPending && (
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
          id="chat-input"
          className="chat__input"
          rows={2}
          value={draft}
          maxLength={MAX}
          disabled={ask.isPending}
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
          <button type="submit" className="btn btn--primary" disabled={ask.isPending || !draft.trim()}>
            Perguntar
          </button>
        </div>
      </form>
      <p className="chat__fine">
        As respostas usam só os números deste processamento. Quando o Gemini responde, a pergunta e esses números são
        enviados ao Google (plano gratuito, que pode usá-los para melhorar produtos); não escreva dados pessoais.
      </p>
    </section>
  );
}

function Message({ m, onFocusPolygon }: { m: ChatMessage; onFocusPolygon: (id: number) => void }) {
  if (m.role === "user") {
    return (
      <div className="msg msg--user">
        <p className="msg__text">{m.content}</p>
      </div>
    );
  }
  return (
    <div className="msg msg--assistant">
      <p className="msg__text">{withPolygonLinks(m.content, onFocusPolygon)}</p>
      <p className="msg__meta">
        {m.source === "gemini" ? "Gemini" : "Resposta automática, sem IA"}
        {m.notice && <span className="msg__notice">. {m.notice}</span>}
      </p>
    </div>
  );
}

/** "polígono nº 76" vira botão que mostra o polígono no mapa. Texto continua texto (sem HTML). */
export function withPolygonLinks(text: string, onFocus: (id: number) => void): ReactNode[] {
  const parts = text.split(/(nº\s?\d{1,5})/g);
  return parts.map((part, i) => {
    const m = /^nº\s?(\d{1,5})$/.exec(part);
    if (!m) return part;
    const id = Number(m[1]);
    return (
      <button key={i} type="button" className="btn btn--link" onClick={() => onFocus(id)} aria-label={`Mostrar polígono ${id} no mapa`}>
        {part}
      </button>
    );
  });
}
