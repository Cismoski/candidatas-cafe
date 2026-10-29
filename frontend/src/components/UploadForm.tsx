import { type DragEvent, type FormEvent, useId, useRef, useState } from "react";
import type { Analysis } from "../api/types";
import { useCreateAnalysis } from "../api/queries";
import { checkFile, checkTotal, formatMb, MAX_UPLOAD_MB, SLOT_LABEL, type Slot } from "../lib/files";
import { ErrorNote } from "./ErrorNote";

const HINT: Record<Slot, string> = {
  primary: "GeoTIFF Sentinel-2 L2A com B02, B03, B04 e B08 nas 4 primeiras bandas (uint16, UTM).",
  scl: "Opcional. Classes de cena da L2A: nuvem, sombra e neve saem da análise.",
  secondary: "Opcional. Outra data da mesma área: confirma que a vegetação é perene.",
};

// Recortes de Guaxupé (MG) na mesma grade; procedência em /amostra/*ATRIBUICAO.txt
const KIT = "/amostra/imagem_multiespectral.tif";
const KIT_SCL = "/amostra/qualidade_scl.tif";
const FEV = "/amostra/s2b_20250217_imagem.tif";
const FEV_SCL = "/amostra/s2b_20250217_scl.tif";
const FEV_2ND = "/amostra/s2b_20250217_segunda_data.tif"; // máscara da SCL embutida (DN 0)

export const SAMPLES = [
  { label: "16 ago 2025 (seca)", title: "Guaxupé (MG), 16 ago 2025", urls: { primary: KIT, scl: KIT_SCL } },
  { label: "17 fev 2025 (chuva)", title: "Guaxupé (MG), 17 fev 2025", urls: { primary: FEV, scl: FEV_SCL } },
  {
    label: "Duas datas",
    title: "Guaxupé (MG), ago 2025 com fev 2025",
    urls: { primary: KIT, scl: KIT_SCL, secondary: FEV_2ND },
  },
] as const satisfies readonly { label: string; title: string; urls: Partial<Record<Slot, string>> }[];

type Files = Record<Slot, File | null>;
const EMPTY: Files = { primary: null, scl: null, secondary: null };

export function UploadForm({ onCreated, onCancel }: { onCreated: (a: Analysis) => void; onCancel?: () => void }) {
  const [files, setFiles] = useState<Files>(EMPTY);
  const [title, setTitle] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const [loadingSample, setLoadingSample] = useState<string | null>(null);
  // Uma chave por conjunto de arquivos: reenviar o MESMO formulário após uma
  // falha de rede reaproveita a chave e o backend não duplica a análise.
  // (título incluído: editar o nome é outra submissão)
  const idemKey = useRef("");
  if (!idemKey.current) idemKey.current = crypto.randomUUID();
  const create = useCreateAnalysis();

  const setSlot = async (slot: Slot, file: File | null) => {
    create.reset();
    setLocalError(null);
    if (file) {
      const err = await checkFile(slot, file);
      if (err) {
        setLocalError(err);
        return;
      }
    }
    idemKey.current = crypto.randomUUID();
    setFiles((f) => ({ ...f, [slot]: file }));
  };

  const loadSample = async (sample: (typeof SAMPLES)[number]) => {
    setLoadingSample(sample.label);
    setLocalError(null);
    create.reset();
    try {
      const entries = await Promise.all(
        Object.entries(sample.urls).map(async ([slot, url]) => {
          const r = await fetch(url);
          if (!r.ok) throw new Error(url);
          const file = new File([await r.blob()], url.split("/").pop() as string, { type: "image/tiff" });
          return [slot, file] as const;
        }),
      );
      idemKey.current = crypto.randomUUID();
      setFiles({ ...EMPTY, ...Object.fromEntries(entries) });
      setTitle(sample.title);
    } catch {
      setLocalError("Não foi possível carregar a cena de exemplo. Recarregue a página e tente de novo.");
    } finally {
      setLoadingSample(null);
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!files.primary) {
      setLocalError("Escolha a imagem principal.");
      return;
    }
    const total = checkTotal(Object.values(files));
    if (total) {
      setLocalError(total);
      return;
    }
    create.mutate(
      { ...files, primary: files.primary, title, idempotencyKey: idemKey.current },
      {
        onSuccess: (a) => {
          setFiles(EMPTY);
          setTitle("");
          idemKey.current = crypto.randomUUID();
          onCreated(a);
        },
      },
    );
  };

  // Carregando exemplo também trava o formulário: senão o exemplo, ao chegar,
  // sobrescreveria um arquivo escolhido ou um envio já disparado
  const busy = create.isPending || loadingSample !== null;
  return (
    <form className="upload" onSubmit={submit} aria-busy={busy} noValidate>
      <div className="upload__head">
        <h2 className="upload__title">Nova análise</h2>
        {onCancel && (
          <button type="button" className="btn btn--quiet" onClick={onCancel} disabled={busy}>
            Fechar
          </button>
        )}
      </div>

      {(["primary", "scl", "secondary"] as Slot[]).map((slot) => (
        <DropSlot key={slot} slot={slot} file={files[slot]} disabled={busy} onChange={(f) => void setSlot(slot, f)} />
      ))}

      <label className="field">
        <span className="field__label">Nome da análise (opcional)</span>
        <input
          className="field__input"
          value={title}
          maxLength={80}
          disabled={busy}
          onChange={(e) => {
            setTitle(e.target.value);
            idemKey.current = crypto.randomUUID();
          }}
          placeholder="Ex.: Fazenda Boa Vista, agosto"
        />
      </label>

      {localError && <ErrorNote message={localError} />}
      {create.error && <ErrorNote error={create.error} />}

      <div className="upload__actions">
        <button type="submit" className="btn btn--primary" disabled={busy || !files.primary}>
          {create.isPending ? "Enviando…" : "Processar imagem"}
        </button>
      </div>
      <div className="upload__samples" role="group" aria-labelledby="samples-label">
        <span id="samples-label" className="upload__samples-label">
          Cenas de exemplo (Guaxupé, MG):
        </span>
        {SAMPLES.map((s) => (
          <button
            key={s.label}
            type="button"
            className="chip"
            onClick={() => void loadSample(s)}
            disabled={busy}
            aria-busy={loadingSample === s.label}
          >
            {loadingSample === s.label ? "Carregando…" : s.label}
          </button>
        ))}
        <span className="sr-only" role="status">
          {loadingSample ? `Carregando a cena de exemplo ${loadingSample}` : ""}
        </span>
      </div>
      <p className="upload__fine">
        Até {MAX_UPLOAD_MB} MB por envio e 1500 × 1500 px. O processamento roda no servidor a cada envio; os
        arquivos e resultados são apagados em até 24 h (antes, se o servidor gratuito reiniciar).
      </p>
    </form>
  );
}

function DropSlot({
  slot,
  file,
  disabled,
  onChange,
}: {
  slot: Slot;
  file: File | null;
  disabled: boolean;
  onChange: (f: File | null) => void;
}) {
  const id = useId();
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    if (disabled) return;
    const f = e.dataTransfer.files[0];
    if (f) onChange(f);
  };

  return (
    <div
      className="slot"
      data-required={slot === "primary" || undefined}
      data-filled={file ? true : undefined}
      data-over={over || undefined}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
    >
      <label htmlFor={id} className="slot__label">
        {SLOT_LABEL[slot]}
      </label>
      {file ? (
        <p className="slot__file">
          <span className="slot__name">{file.name}</span>
          <span className="slot__size">{formatMb(file.size)}</span>
          <button
            type="button"
            className="btn btn--link"
            disabled={disabled}
            onClick={() => {
              if (input.current) input.current.value = "";
              onChange(null);
            }}
          >
            Remover
          </button>
        </p>
      ) : (
        <p className="slot__hint">
          {HINT[slot]} <span className="slot__cta">Arraste o arquivo ou clique para escolher.</span>
        </p>
      )}
      <input
        ref={input}
        id={id}
        className="slot__input"
        type="file"
        accept=".tif,.tiff,image/tiff"
        disabled={disabled}
        onChange={(e) => {
          const f = e.target.files?.[0] ?? null;
          // O arquivo fica no estado do React; limpar o input permite escolher
          // o mesmo arquivo de novo depois de uma rejeição.
          e.target.value = "";
          onChange(f);
        }}
      />
    </div>
  );
}
