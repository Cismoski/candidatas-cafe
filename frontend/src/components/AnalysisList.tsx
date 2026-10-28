import type { AnalysisItem, AnalysisStatus } from "../api/types";
import { formatDateTime, formatExpiry } from "../lib/format";

export const STATUS_LABEL: Record<AnalysisStatus, string> = {
  pending: "Na fila",
  processing: "Processando",
  done: "Concluída",
  failed: "Falhou",
};

interface Props {
  items: AnalysisItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function AnalysisList({ items, selectedId, onSelect }: Props) {
  return (
    <ul className="runs" aria-label="Suas análises">
      {items.map((a) => (
        <li key={a.id}>
          <button
            type="button"
            className="runs__item"
            aria-current={a.id === selectedId || undefined}
            onClick={() => onSelect(a.id)}
          >
            <span className="runs__title">{a.title}</span>
            <span className="runs__status" data-status={a.status}>
              {STATUS_LABEL[a.status]}
            </span>
            <span className="runs__meta">
              {formatDateTime(a.created_at)}, {formatExpiry(a.expires_at)}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}
