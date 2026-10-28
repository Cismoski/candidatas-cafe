const ha = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const idx = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const pct = new Intl.NumberFormat("pt-BR", { style: "percent", maximumFractionDigits: 1 });
const int = new Intl.NumberFormat("pt-BR");

export const formatHa = (v: number) => `${ha.format(v)} ha`;
export const formatIndex = (v: number | null | undefined) => (v == null ? "—" : idx.format(v));
export const formatPct = (v: number) => pct.format(v);
export const formatInt = (v: number) => int.format(v);

const dateFmt = new Intl.DateTimeFormat("pt-BR", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});
const timeFmt = new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" });

/** Data de aquisição da cena (UTC, como no metadado do Sentinel-2). */
export function formatSceneDate(iso: string | null | undefined): string {
  if (!iso) return "data desconhecida";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "data desconhecida" : dateFmt.format(d);
}

export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : timeFmt.format(d);
}

/** "expira em 5 h", "expira em 40 min", "expirada". */
export function formatExpiry(iso: string, now = Date.now()): string {
  const ms = new Date(iso).getTime() - now;
  if (Number.isNaN(ms)) return "";
  if (ms <= 0) return "expirada";
  const min = Math.ceil(ms / 60_000);
  if (min < 60) return `expira em ${min} min`;
  return `expira em ${Math.floor(min / 60)} h`;
}

/** Coordenada em graus, minutos e hemisfério, como na margem de uma carta. */
export function formatDegrees(value: number, axis: "lat" | "lon"): string {
  const hemi = axis === "lat" ? (value < 0 ? "S" : "N") : value < 0 ? "O" : "L";
  const abs = Math.abs(value);
  let deg = Math.floor(abs);
  let min = Math.round((abs - deg) * 60 * 10) / 10;
  if (min >= 60) {
    deg += 1;
    min = 0;
  }
  return `${deg}°${min.toLocaleString("pt-BR", { minimumFractionDigits: 1 })}′ ${hemi}`;
}

/** Variação com sinal explícito; arredonda antes de decidir o sinal ("+0,00" nunca aparece). */
export const formatSigned = (v: number) => {
  const s = idx.format(Math.abs(v));
  return s === idx.format(0) ? s : `${v > 0 ? "+" : "−"}${s}`;
};
