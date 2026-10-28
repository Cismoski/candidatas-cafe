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

const SAMPLE = {
  primary: "/amostra/imagem_multiespectral.tif",
  scl: "/amostra/qualidade_scl.tif",
};

type Files = Record<Slot, File | null>;
const EMPTY: Files = { primary: null, scl: null, secondary: null };

export function UploadForm({ onCreated, onCancel }: { onCreated: (a: Analysis) => void; onCancel?: () => void }) {
  const [files, setFiles] = useState<Files>(EMPTY);
  const [title, setTitle] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const [loadingSample, setLoadingSample] = useState(false);
  // Uma chave por conjunto de arquivos: reenviar o MESMO formulário após uma
  // falha de rede reaproveita a chave e o backend não duplica a análise.
  const idemKey = useRef(crypto.randomUUID());
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

  const loadSample = async () => {
    setLoadingSample(true);
    setLocalError(null);
    create.reset();
    try {
      const [p, s] = await Promise.all(
        [SAMPLE.primary, SAMPLE.scl].map(async (url) => {
          const r = await fetch(url);
          if (!r.ok) throw new Error(url);
          return new File([await r.blob()], url.split("/").pop() as string, { type: "image/tiff" });
        }),
      );
      idemKey.current = crypto.randomUUID();
      setFiles({ primary: p as File, scl: s as File, secondary: null });
      setTitle("Guaxupé (MG), 16 ago 2025");
    } catch {
      setLocalError("Não foi possível carregar a cena de exemplo. Recarregue a página e tente de novo.");
    } finally {
      setLoadingSample(false);
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

  const busy = create.isPending;
  return (
    <form className="upload" onSubmit={submit} aria-busy={busy} noValidate>
      <div className="upload__head">
        <h2 className="upload__title">Nova análise</h2>
        {onCancel && (
          <button type="button" className="btn btn--quiet" onClick={onCancel}>
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
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Ex.: Fazenda Boa Vista, agosto"
        />
      </label>

      {localError && <ErrorNote message={localError} />}
      {create.error && <ErrorNote error={create.error} />}

      <div className="upload__actions">
        <button type="submit" className="btn btn--primary" disabled={busy || !files.primary}>
          {busy ? "Enviando…" : "Processar imagem"}
        </button>
        <button type="button" className="btn btn--quiet" onClick={() => void loadSample()} disabled={busy || loadingSample}>
          {loadingSample ? "Carregando exemplo…" : "Usar cena de exemplo (Guaxupé)"}
        </button>
      </div>
      <p className="upload__fine">
        Até {MAX_UPLOAD_MB} MB por envio e 1500 × 1500 px. O processamento roda no servidor a cada envio; os
        arquivos e resultados são apagados em 24 h.
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
        onChange={(e) => onChange(e.target.files?.[0] ?? null)}
      />
    </div>
  );
}
