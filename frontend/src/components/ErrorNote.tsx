import { ApiError } from "../api/client";

const ACTION: Partial<Record<ApiError["kind"], string>> = {
  rate_limited: "O limite volta a liberar com o tempo; as análises já feitas continuam disponíveis.",
  busy: "Outras análises estão sendo processadas agora.",
  too_large: "Recorte a cena ou envie menos bandas.",
};

/** Erro com o que aconteceu e o que fazer. A mensagem da API tem prioridade. */
export function ErrorNote({ error, message, onRetry }: { error?: unknown; message?: string; onRetry?: () => void }) {
  const text = message ?? (error instanceof Error ? error.message : "Algo deu errado. Tente de novo.");
  const action = error instanceof ApiError ? ACTION[error.kind] : undefined;
  return (
    <div className="note note--error" role="alert">
      <p>{text}</p>
      {action && <p className="note__more">{action}</p>}
      {onRetry && (
        <button type="button" className="btn btn--link" onClick={onRetry}>
          Tentar de novo
        </button>
      )}
    </div>
  );
}
