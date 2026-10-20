import { clsx } from "clsx";
import {
  AlertTriangle, CheckCircle2, ChevronRight, Info, Loader2, RotateCcw, Sparkles, X, XCircle,
} from "lucide-react";
import {
  ButtonHTMLAttributes, createContext, forwardRef, InputHTMLAttributes, ReactNode, SelectHTMLAttributes,
  TextareaHTMLAttributes, useCallback, useContext, useEffect, useId, useRef, useState,
} from "react";
import { Link, LinkProps } from "react-router-dom";
import { errorMessage } from "@/lib/errors";
import { ApiError } from "@/api/client";

export const cx = clsx;

/* ------------------------------------------------------------------ buttons */
type Variant = "primary" | "secondary" | "ghost" | "danger" | "subtle";
const VARIANT: Record<Variant, string> = {
  primary: "bg-brand-700 text-white hover:bg-brand-800 disabled:bg-brand-700/50",
  secondary: "bg-white text-ink border border-line hover:bg-slate-50 disabled:text-ink-subtle",
  ghost: "text-ink-muted hover:text-ink hover:bg-slate-100",
  danger: "bg-bad text-white hover:bg-red-800 disabled:opacity-50",
  subtle: "bg-brand-50 text-brand-800 hover:bg-brand-100",
};
const SIZE = { sm: "h-8 px-3 text-sm gap-1.5", md: "h-10 px-4 text-[15px] gap-2", lg: "h-12 px-5 text-base gap-2" };

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: keyof typeof SIZE;
  loading?: boolean; icon?: ReactNode };

export const Button = forwardRef<HTMLButtonElement, BtnProps>(function Button(
  { variant = "primary", size = "md", loading, icon, className, children, disabled, ...rest }, ref) {
  return (
    <button ref={ref} disabled={disabled || loading}
      className={cx("inline-flex items-center justify-center rounded-md font-medium transition-colors select-none",
        "disabled:cursor-not-allowed min-h-[40px] sm:min-h-0", VARIANT[variant], SIZE[size], className)} {...rest}>
      {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
});

export function LinkButton({ variant = "primary", size = "md", className, children, icon, ...rest }:
  LinkProps & { variant?: Variant; size?: keyof typeof SIZE; icon?: ReactNode }) {
  return (
    <Link className={cx("inline-flex items-center justify-center rounded-md font-medium transition-colors",
      VARIANT[variant], SIZE[size], className)} {...rest}>
      {icon}
      {children}
    </Link>
  );
}

/* ------------------------------------------------------------------ layout */
export function Card({ className, children, as: As = "section", ...rest }:
  { className?: string; children: ReactNode; as?: any } & Record<string, any>) {
  return <As className={cx("card", className)} {...rest}>{children}</As>;
}

export function CardHeader({ title, subtitle, action, icon }: { title: ReactNode; subtitle?: ReactNode;
  action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 px-4 sm:px-5 pt-4 sm:pt-5">
      <div className="flex items-start gap-2.5 min-w-0">
        {icon && <span className="mt-0.5 text-brand-700 shrink-0">{icon}</span>}
        <div className="min-w-0">
          <h2 className="text-[15px] font-semibold leading-snug">{title}</h2>
          {subtitle && <p className="text-sm text-ink-muted mt-0.5">{subtitle}</p>}
        </div>
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

export function CardBody({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cx("px-4 sm:px-5 py-4", className)}>{children}</div>;
}

export function PageHeader({ title, subtitle, action, eyebrow }: { title: string; subtitle?: ReactNode;
  action?: ReactNode; eyebrow?: ReactNode }) {
  return (
    <header className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3 mb-5">
      <div className="min-w-0">
        {eyebrow && <div className="text-xs font-medium uppercase tracking-wide text-brand-700 mb-1">{eyebrow}</div>}
        <h1 className="text-2xl font-semibold">{title}</h1>
        {subtitle && <p className="text-ink-muted mt-1 max-w-prose">{subtitle}</p>}
      </div>
      {action && <div className="flex flex-wrap gap-2">{action}</div>}
    </header>
  );
}

/* ------------------------------------------------------------------ feedback */
type Tone = "neutral" | "brand" | "ok" | "warn" | "bad" | "info" | "navy";
const TONE: Record<Tone, string> = {
  neutral: "bg-slate-100 text-slate-700 border-slate-200",
  brand: "bg-brand-50 text-brand-800 border-brand-200",
  ok: "bg-ok-bg text-ok border-green-200",
  warn: "bg-warn-bg text-warn border-amber-200",
  bad: "bg-bad-bg text-bad border-red-200",
  info: "bg-info-bg text-info border-blue-200",
  navy: "bg-navy-900 text-white border-navy-900",
};

export function Badge({ tone = "neutral", children, className, icon, title }: { tone?: Tone; children: ReactNode;
  className?: string; icon?: ReactNode; title?: string }) {
  return (
    <span title={title} className={cx("inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium border",
      "whitespace-nowrap", TONE[tone], className)}>
      {icon}
      {children}
    </span>
  );
}

export function AITag({ label = "AI-generated" }: { label?: string }) {
  return <Badge tone="info" icon={<Sparkles className="h-3 w-3" aria-hidden />}>{label}</Badge>;
}

export function Notice({ tone = "info", title, children, action, className }: { tone?: "info" | "warn" | "bad" | "ok";
  title?: ReactNode; children?: ReactNode; action?: ReactNode; className?: string }) {
  const Icon = { info: Info, warn: AlertTriangle, bad: XCircle, ok: CheckCircle2 }[tone];
  const styles = { info: "bg-info-bg border-blue-200 text-blue-900", warn: "bg-warn-bg border-amber-200 text-amber-900",
    bad: "bg-bad-bg border-red-200 text-red-900", ok: "bg-ok-bg border-green-200 text-green-900" }[tone];
  return (
    <div role={tone === "bad" ? "alert" : "status"} className={cx("flex gap-3 rounded-md border p-3 text-sm", styles, className)}>
      <Icon className="h-4 w-4 mt-0.5 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1">
        {title && <div className="font-medium">{title}</div>}
        {children && <div className={cx(title && "mt-0.5", "leading-relaxed")}>{children}</div>}
      </div>
      {action && <div className="shrink-0 self-center">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry, compact }: { error: unknown; onRetry?: () => void; compact?: boolean }) {
  const reqId = error instanceof ApiError ? error.requestId : undefined;
  return (
    <Notice tone="bad" title={compact ? undefined : "That didn't work"}
      action={onRetry && <Button size="sm" variant="secondary" icon={<RotateCcw className="h-3.5 w-3.5" />}
        onClick={onRetry}>Retry</Button>}>
      {errorMessage(error)}
      {reqId && <details className="mt-1 text-xs opacity-75"><summary>Details</summary>Request ID: {reqId}</details>}
    </Notice>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 text-ink-muted text-sm">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
      {label}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cx("animate-pulse rounded bg-slate-200/70", className)} />;
}

export function PageSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="Loading">
      <Skeleton className="h-8 w-64" />
      <Skeleton className="h-4 w-96 max-w-full" />
      <div className="grid gap-4 md:grid-cols-2"><Skeleton className="h-40" /><Skeleton className="h-40" /></div>
      <Skeleton className="h-56" />
    </div>
  );
}

export function EmptyState({ title, children, action, icon }: { title: string; children?: ReactNode;
  action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-2 rounded-lg border border-dashed border-line bg-white p-5">
      {icon && <div className="text-brand-700">{icon}</div>}
      <div className="font-medium">{title}</div>
      {children && <div className="text-sm text-ink-muted max-w-prose">{children}</div>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}

/** Staged progress for slow AI calls (SRS NFR-005). */
export function AIProgress({ stages, active }: { stages: string[]; active: boolean }) {
  const [i, setI] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!active) { setI(0); setElapsed(0); return; }
    const t1 = setInterval(() => setI((x) => Math.min(x + 1, stages.length - 1)), 3500);
    const t2 = setInterval(() => setElapsed((x) => x + 1), 1000);
    return () => { clearInterval(t1); clearInterval(t2); };
  }, [active, stages.length]);
  if (!active) return null;
  return (
    <div role="status" aria-live="polite" className="flex items-center gap-2 text-sm text-ink-muted">
      <Loader2 className="h-4 w-4 animate-spin text-brand-700" aria-hidden />
      <span>{stages[i]}</span>
      {elapsed >= 10 && <span className="text-ink-subtle">· {elapsed}s</span>}
      {elapsed >= 20 && <span className="text-ink-subtle">· still working — your input is saved</span>}
    </div>
  );
}

/* ------------------------------------------------------------------ scores */
export function ProgressBar({ value, max = 100, tone = "brand", label, className }: { value: number; max?: number;
  tone?: "brand" | "ok" | "warn" | "bad" | "navy"; label?: string; className?: string }) {
  const w = Math.max(0, Math.min(100, (value / max) * 100));
  const color = { brand: "bg-brand-600", ok: "bg-ok", warn: "bg-warn", bad: "bg-bad", navy: "bg-navy-700" }[tone];
  return (
    <div className={cx("h-2 w-full rounded-full bg-slate-100 overflow-hidden", className)} role="progressbar"
      aria-valuenow={Math.round(value)} aria-valuemin={0} aria-valuemax={max} aria-label={label}>
      <div className={cx("h-full rounded-full transition-[width]", color)} style={{ width: `${w}%` }} />
    </div>
  );
}

export function ConfidenceBadge({ level }: { level: string }) {
  const map: Record<string, [Tone, string]> = { high: ["ok", "High confidence"], medium: ["info", "Medium confidence"],
    low: ["warn", "Low confidence"], none: ["neutral", "No evidence yet"] };
  const [tone, text] = map[level] ?? map.none;
  return <Badge tone={tone} className="whitespace-normal text-left">{text}</Badge>;
}

export function ScoreTile({ name, score, confidence, basis }: { name: string; score: number | null;
  confidence: string; basis?: string }) {
  return (
    <div className={cx("rounded-md border border-line bg-white p-3 flex flex-col gap-2",
      confidence === "low" && "opacity-90")}>
      <div className="text-xs font-medium text-ink-muted leading-tight min-h-[2rem]">{name}</div>
      {score === null ? (
        <div className="text-sm text-ink-subtle leading-snug">Not enough evidence yet</div>
      ) : (
        <div className="flex items-baseline gap-1">
          <span className={cx("text-2xl font-semibold tabular-nums", confidence === "low" && "text-ink-muted")}>{score}</span>
          <span className="text-xs text-ink-subtle">/100</span>
        </div>
      )}
      {score !== null && <ProgressBar value={score} tone={confidence === "low" ? "navy" : "brand"} label={name} />}
      <div><ConfidenceBadge level={confidence} /></div>
      {basis && <div className="text-xs text-ink-subtle leading-snug">{basis}</div>}
    </div>
  );
}

export function EvidenceChip({ state }: { state: string }) {
  const map: Record<string, [Tone, string]> = {
    evidenced: ["ok", "Evidenced in resume"], weak: ["warn", "Weak evidence"], not_shown: ["neutral", "Not shown in resume"],
    no_resume: ["neutral", "No resume yet"], demonstrated: ["ok", "Demonstrated"], developing: ["info", "Developing"],
    not_assessed: ["neutral", "Not yet assessed"],
  };
  const [tone, text] = map[state] ?? ["neutral", state];
  return <Badge tone={tone}>{text}</Badge>;
}

export const GAP_TONE: Record<string, Tone> = { G1: "neutral", G2: "warn", G3: "bad", G4: "info", G5: "neutral", G6: "warn" };

/* ------------------------------------------------------------------ forms */
export function Field({ label, error, hint, children, htmlFor, required }: { label: string; error?: string;
  hint?: ReactNode; children: ReactNode; htmlFor?: string; required?: boolean }) {
  return (
    <div>
      <label className="label" htmlFor={htmlFor}>{label}{required && <span className="text-bad"> *</span>}</label>
      {children}
      {error ? <p className="mt-1 text-sm text-bad" role="alert" id={htmlFor ? `${htmlFor}-error` : undefined}>{error}</p>
        : hint ? <p className="hint">{hint}</p> : null}
    </div>
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean }>(
  function Input({ className, invalid, ...rest }, ref) {
    return <input ref={ref} aria-invalid={invalid || undefined}
      className={cx("input", invalid && "border-bad focus:ring-bad/30 focus:border-bad", className)} {...rest} />;
  });

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean }>(
  function Textarea({ className, invalid, ...rest }, ref) {
    return <textarea ref={ref} aria-invalid={invalid || undefined}
      className={cx("input min-h-[120px] leading-relaxed", invalid && "border-bad", className)} {...rest} />;
  });

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  function Select({ className, children, ...rest }, ref) {
    return <select ref={ref} className={cx("input pr-8", className)} {...rest}>{children}</select>;
  });

/* ------------------------------------------------------------------ tabs */
export function Tabs<T extends string>({ tabs, value, onChange, label }: { tabs: { id: T; label: string;
  badge?: ReactNode }[]; value: T; onChange: (v: T) => void; label: string }) {
  return (
    <div role="tablist" aria-label={label} className="flex gap-1 overflow-x-auto border-b border-line -mx-1 px-1">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)}
          className={cx("relative whitespace-nowrap px-3 py-2.5 text-sm font-medium transition-colors",
            value === t.id ? "text-brand-800" : "text-ink-muted hover:text-ink")}>
          <span className="inline-flex items-center gap-1.5">{t.label}{t.badge}</span>
          {value === t.id && <span className="absolute inset-x-2 -bottom-px h-0.5 rounded bg-brand-700" />}
        </button>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ dialog */
export function Dialog({ open, onClose, title, children, footer }: { open: boolean; onClose: () => void;
  title: string; children: ReactNode; footer?: ReactNode }) {
  const id = useId();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>("button, [href], input, textarea, select")?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); prev?.focus(); };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-0 sm:p-4">
      <div className="absolute inset-0 bg-navy-950/40" onClick={onClose} aria-hidden />
      <div ref={ref} role="dialog" aria-modal="true" aria-labelledby={id}
        className="relative w-full sm:max-w-lg bg-white rounded-t-xl sm:rounded-lg shadow-pop max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-5 pt-4">
          <h2 id={id} className="text-base font-semibold">{title}</h2>
          <button onClick={onClose} className="p-1 rounded hover:bg-slate-100" aria-label="Close"><X className="h-4 w-4" /></button>
        </div>
        <div className="px-5 py-3 text-sm text-ink-muted">{children}</div>
        {footer && <div className="flex flex-wrap justify-end gap-2 px-5 pb-4">{footer}</div>}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ toasts */
type ToastItem = { id: number; text: string; tone: "ok" | "bad" | "info" };
const ToastCtx = createContext<(text: string, tone?: ToastItem["tone"]) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const push = useCallback((text: string, tone: ToastItem["tone"] = "ok") => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x, { id, text, tone }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), 4000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div aria-live="polite" className="fixed bottom-20 sm:bottom-4 right-4 left-4 sm:left-auto z-50 flex flex-col gap-2 items-end">
        {items.map((t) => (
          <div key={t.id} className={cx("rounded-md px-3 py-2 text-sm shadow-pop text-white max-w-sm",
            t.tone === "ok" ? "bg-navy-900" : t.tone === "bad" ? "bg-bad" : "bg-info")}>{t.text}</div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);

/* ------------------------------------------------------------------ misc */
export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div>
      <div className="text-xs text-ink-muted">{label}</div>
      <div className="text-lg font-semibold tabular-nums">{value}</div>
      {sub && <div className="text-xs text-ink-subtle">{sub}</div>}
    </div>
  );
}

export function RowLink({ to, children, external }: { to: string; children: ReactNode; external?: boolean }) {
  const cls = "flex items-center justify-between gap-2 rounded-md px-3 py-2.5 hover:bg-slate-50 text-sm";
  if (external) {
    return <a href={to} target="_blank" rel="noopener noreferrer" className={cls}>{children}<ChevronRight className="h-4 w-4 text-ink-subtle" /></a>;
  }
  return <Link to={to} className={cls}>{children}<ChevronRight className="h-4 w-4 text-ink-subtle" /></Link>;
}

/** Renders question prompts: plain text with ``` code fences and `inline code` (no HTML). */
export function RichText({ text, className }: { text: string; className?: string }) {
  const parts = text.split(/```(?:\w+)?\n?/);
  return (
    <div className={cx("prose-rr space-y-2", className)}>
      {parts.map((part, i) =>
        i % 2 === 1 ? <pre key={i}><code>{part.replace(/\n$/, "")}</code></pre> : (
          part.trim() && <p key={i} className="whitespace-pre-wrap">
            {part.split(/(`[^`]+`)/).map((seg, j) => seg.startsWith("`") && seg.endsWith("`") && seg.length > 2
              ? <code key={j}>{seg.slice(1, -1)}</code> : <span key={j}>{seg}</span>)}
          </p>
        ))}
    </div>
  );
}
