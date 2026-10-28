/**
 * Checagens no navegador antes do envio. São só conveniência (feedback
 * imediato, sem gastar cota nem banda): o backend repete todas e é a
 * autoridade (assinatura TIFF, bandas, CRS, dimensões).
 */

export const MAX_UPLOAD_MB = Number(import.meta.env.VITE_MAX_UPLOAD_MB ?? 40);
const TIFF_MAGIC = ["49492a00", "4d4d002a", "49492b00", "4d4d002b"]; // II*, MM*, BigTIFF

export type Slot = "primary" | "scl" | "secondary";

export const SLOT_LABEL: Record<Slot, string> = {
  primary: "Imagem principal",
  scl: "Máscara de qualidade (SCL)",
  secondary: "Segunda data",
};

export function hasTiffExtension(name: string): boolean {
  return /\.tiff?$/i.test(name);
}

export async function hasTiffSignature(file: Blob): Promise<boolean> {
  if (file.size < 4) return false;
  const head = new Uint8Array(await file.slice(0, 4).arrayBuffer());
  const hex = Array.from(head, (b) => b.toString(16).padStart(2, "0")).join("");
  return TIFF_MAGIC.includes(hex);
}

/** Mensagem de erro do arquivo, ou null se passou nas checagens locais. */
export async function checkFile(slot: Slot, file: File): Promise<string | null> {
  const label = SLOT_LABEL[slot];
  if (file.size === 0) return `${label}: arquivo vazio.`;
  if (!hasTiffExtension(file.name)) return `${label}: envie um GeoTIFF (.tif ou .tiff).`;
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024)
    return `${label}: ${formatMb(file.size)} excede o máximo de ${MAX_UPLOAD_MB} MB.`;
  if (!(await hasTiffSignature(file))) return `${label}: o conteúdo não é um TIFF.`;
  return null;
}

/** O limite do backend vale para o corpo inteiro (todos os arquivos juntos). */
export function checkTotal(files: (File | null | undefined)[]): string | null {
  const total = files.reduce((s, f) => s + (f?.size ?? 0), 0);
  return total > MAX_UPLOAD_MB * 1024 * 1024
    ? `Os arquivos somam ${formatMb(total)}; o máximo por envio é ${MAX_UPLOAD_MB} MB.`
    : null;
}

export function formatMb(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} MB`;
}

/** Salva um Blob com nome de arquivo (o download autenticado não pode ser um <a href>). */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Revoga depois do clique ter sido processado pelo navegador
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
