const TZ = "Asia/Kolkata";

export function fmtDate(iso: string | null | undefined, tz = TZ): string {
  if (!iso) return "—";
  const d = iso.length === 10 ? new Date(iso + "T00:00:00") : new Date(iso);
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric",
    timeZone: iso.length === 10 ? undefined : tz });
}

export function fmtDay(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
}

export function fmtDateTime(iso: string | null | undefined, tz = TZ): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
    timeZone: tz });
}

export function pct(x: number | null | undefined): string {
  return x === null || x === undefined ? "—" : `${Math.round(x * 100)}%`;
}

export function plural(n: number, word: string, pluralWord?: string): string {
  return `${n} ${n === 1 ? word : pluralWord ?? word + "s"}`;
}

export function wordCount(s: string): number {
  return s.trim() ? s.trim().split(/\s+/).length : 0;
}

export const IMPORTANCE_LABEL: Record<string, string> = { core: "Core", required: "Required", preferred: "Preferred",
  interview: "Interview" };
