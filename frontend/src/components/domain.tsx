import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Check, ClipboardPaste, FileUp, PenLine, Plus, Trash2, Upload } from "lucide-react";
import { ReactNode, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, get, post, put, upload } from "@/api/client";
import type { Gap, NextActions, Recommendation, Requirement, RequirementsPayload } from "@/api/types";
import {
  AIProgress, Badge, Button, Card, CardBody, CardHeader, cx, EmptyState, ErrorState, GAP_TONE, LinkButton, Notice,
  Select, Skeleton, Textarea, useToast,
} from "@/components/ui";
import { useActiveTargetId } from "@/hooks/session";
import { errorMessage } from "@/lib/errors";
import { IMPORTANCE_LABEL } from "@/lib/format";

/* ------------------------------------------------------------------ guard */
export function NeedTarget({ children }: { children: (targetId: string) => ReactNode }) {
  const tid = useActiveTargetId();
  if (!tid) {
    return (
      <EmptyState title="Choose a target job first"
        action={<LinkButton to="/app/onboarding">Set up your target</LinkButton>}>
        Everything in RoleReady is measured against a specific role, so start by choosing one.
      </EmptyState>
    );
  }
  return <>{children(tid)}</>;
}

/* ------------------------------------------------------------------ requirements */
const ORIGIN: Record<string, [string, "brand" | "neutral" | "info"]> = {
  jd_extracted: ["From job description", "brand"], role_default: ["Role default", "neutral"],
  user_added: ["Added by you", "info"],
};

export function RequirementEditor({ targetId, onConfirmed, compact }: { targetId: string;
  onConfirmed?: () => void; compact?: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const reqs = useQuery({ queryKey: ["requirements", targetId],
    queryFn: () => get<RequirementsPayload>(`/targets/${targetId}/requirements`) });
  const skills = useQuery({ queryKey: ["skills"], queryFn: () => get<{ slug: string; name: string }[]>("/skills"),
    staleTime: Infinity });
  const [draft, setDraft] = useState<Requirement[] | null>(null);
  const [adding, setAdding] = useState("");
  const list = draft ?? reqs.data?.requirements ?? [];
  const scored = list.filter((r) => r.scored);
  const info = list.filter((r) => !r.scored);

  const save = useMutation({
    mutationFn: () => put<RequirementsPayload>(`/targets/${targetId}/requirements`, {
      expected_updated_at: reqs.data?.updated_at,
      requirements: list.map((r) => ({ id: r.id.startsWith("new-") ? undefined : r.id, skill_slug: r.skill?.slug,
        raw_phrase: r.raw_phrase, requirement_level: r.requirement_level, category: r.category })),
    }),
    onSuccess: (data) => {
      qc.setQueryData(["requirements", targetId], data);
      setDraft(null);
      ["target", "dashboard", "gaps", "readiness", "analysis", "plan"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
      toast("Requirements confirmed");
      onConfirmed?.();
    },
  });

  const update = (id: string, patchReq: Partial<Requirement>) =>
    setDraft(list.map((r) => (r.id === id ? { ...r, ...patchReq } : r)));
  const remove = (id: string) => setDraft(list.filter((r) => r.id !== id));
  const available = useMemo(() => (skills.data ?? []).filter((s) => !list.some((r) => r.skill?.slug === s.slug)),
    [skills.data, list]);
  const add = () => {
    const s = skills.data?.find((x) => x.slug === adding);
    if (!s) return;
    setDraft([...list, { id: `new-${s.slug}`, skill: s, raw_phrase: s.name, category: "skill", requirement_level: "required",
      importance: "required", origin: "user_added", evidence_snippet: null, is_inferred: false, scored: true }]);
    setAdding("");
  };

  if (reqs.isLoading) return <Skeleton className="h-48" />;
  if (reqs.isError) return <ErrorState error={reqs.error} onRetry={() => reqs.refetch()} />;
  const confirmed = !!reqs.data?.confirmed_at && !draft;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 justify-between">
        <p className="text-sm text-ink-muted">{scored.length} skill requirements are scored. Toggle required/preferred,
          remove anything that doesn't apply, or add a missing skill.</p>
        {confirmed && <Badge tone="ok" icon={<Check className="h-3 w-3" />}>Confirmed</Badge>}
      </div>
      <ul className="divide-y divide-line rounded-md border border-line bg-white">
        {scored.map((r) => {
          const [olabel, otone] = ORIGIN[r.origin];
          return (
            <li key={r.id} className="flex flex-col sm:flex-row sm:items-center gap-2 px-3 py-2.5">
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="font-medium text-sm">{r.skill?.name ?? r.raw_phrase}</span>
                  <Badge tone={otone}>{olabel}</Badge>
                  {r.importance === "core" && <Badge tone="navy">Core</Badge>}
                  {r.is_inferred && <Badge tone="warn" title="The AI suggested this but we couldn't find the exact wording in the job description.">Inferred — check</Badge>}
                  {!r.skill && <Badge tone="neutral" title="Not in the skill taxonomy, so it is shown in coverage but not assessed.">Unmapped</Badge>}
                </div>
                {!compact && r.evidence_snippet && <p className="text-xs text-ink-subtle mt-1 line-clamp-2">“{r.evidence_snippet}”</p>}
              </div>
              <div className="flex items-center gap-2">
                <Select aria-label={`Level for ${r.skill?.name ?? r.raw_phrase}`} value={r.requirement_level}
                  className="h-9 py-1 text-sm w-[130px]"
                  onChange={(e) => update(r.id, { requirement_level: e.target.value as Requirement["requirement_level"] })}>
                  <option value="required">Required</option>
                  <option value="preferred">Preferred</option>
                </Select>
                <button onClick={() => remove(r.id)} className="p-2 rounded hover:bg-slate-100 text-ink-muted"
                  aria-label={`Remove ${r.skill?.name ?? r.raw_phrase}`}><Trash2 className="h-4 w-4" /></button>
              </div>
            </li>
          );
        })}
      </ul>
      <div className="flex flex-col sm:flex-row gap-2">
        <Select aria-label="Add a skill" value={adding} onChange={(e) => setAdding(e.target.value)} className="sm:max-w-xs">
          <option value="">Add a skill…</option>
          {available.map((s) => <option key={s.slug} value={s.slug}>{s.name}</option>)}
        </Select>
        <Button variant="secondary" onClick={add} disabled={!adding} icon={<Plus className="h-4 w-4" />}>Add</Button>
      </div>
      {info.length > 0 && !compact && (
        <div className="rounded-md bg-slate-50 border border-line p-3">
          <div className="text-xs font-medium text-ink-muted mb-1.5">Also in the job description (shown for context, not scored)</div>
          <ul className="text-sm space-y-1">
            {info.map((r) => <li key={r.id} className="flex gap-2"><span className="text-ink-subtle capitalize w-20 shrink-0">{r.category}</span>{r.raw_phrase}</li>)}
          </ul>
        </div>
      )}
      {save.isError && <ErrorState error={save.error} compact />}
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => save.mutate()} loading={save.isPending} icon={<Check className="h-4 w-4" />}>
          {draft ? "Save and confirm requirements" : confirmed ? "Re-confirm requirements" : "Confirm requirements"}
        </Button>
        {draft && <Button variant="ghost" onClick={() => setDraft(null)}>Discard changes</Button>}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ JD submit */
export function JDForm({ targetId, onDone }: { targetId: string; onDone?: (result: any) => void }) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [short, setShort] = useState(false);
  const submit = useMutation({
    mutationFn: (force: boolean) => post(`/targets/${targetId}/job-description`, { text, force }, 120_000),
    onSuccess: (data) => {
      qc.setQueryData(["requirements", targetId], { requirements: data.requirements, confirmed_at: data.confirmed_at,
        updated_at: data.updated_at });
      qc.invalidateQueries({ queryKey: ["target"] });
      onDone?.(data);
      setShort(false);
    },
    onError: (e) => { if (e instanceof ApiError && e.code === "JD_TOO_SHORT") setShort(true); },
  });
  const n = text.trim().length;
  return (
    <div className="space-y-3">
      <Textarea rows={9} value={text} onChange={(e) => setText(e.target.value)} maxLength={15000}
        placeholder="Paste the full job description here (responsibilities, requirements, nice-to-haves)…"
        aria-label="Job description" aria-describedby="jd-count" />
      <div className="flex justify-between text-xs text-ink-subtle" id="jd-count">
        <span>Treated as data only — instructions inside a job description are ignored.</span>
        <span className={cx(n > 0 && n < 200 && "text-warn")}>{n.toLocaleString()} / 15,000</span>
      </div>
      {short && (
        <Notice tone="warn" title="This looks too short to be a job description"
          action={<Button size="sm" variant="secondary" onClick={() => submit.mutate(true)}>Use it anyway</Button>}>
          Job descriptions are usually at least 200 characters. You can still use it as notes.
        </Notice>
      )}
      {submit.isError && !short && <ErrorState error={submit.error} compact />}
      <AIProgress active={submit.isPending} stages={["Reading the job description…", "Extracting requirements…",
        "Matching them to the skill list…", "Merging with role defaults…"]} />
      <Button onClick={() => submit.mutate(false)} disabled={n === 0} loading={submit.isPending}
        icon={<ArrowRight className="h-4 w-4" />}>Analyse job description</Button>
    </div>
  );
}

/* ------------------------------------------------------------------ resume import */
export function ResumeImport({ onImported }: { onImported: (resumeId: string, result: any) => void }) {
  const [mode, setMode] = useState<"choose" | "paste">("choose");
  const [text, setText] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const nav = useNavigate();
  const qc = useQueryClient();
  const done = (data: any) => {
    qc.invalidateQueries({ queryKey: ["resumes"] });
    qc.invalidateQueries({ queryKey: ["dashboard"] });
    onImported(data.resume_id, data);
  };
  const up = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return upload("/resumes/upload", fd);
    },
    onSuccess: done, onError: setErr,
  });
  const paste = useMutation({ mutationFn: () => post("/resumes/from-text", { text }, 120_000), onSuccess: done, onError: setErr });
  const pick = (f: File | undefined) => {
    setErr(null);
    if (!f) return;
    if (!f.name.toLowerCase().endsWith(".pdf")) return setErr(new ApiError(415, "UNSUPPORTED_FILE_TYPE", "Upload a PDF file."));
    if (f.size > 5 * 1024 * 1024) return setErr(new ApiError(413, "FILE_TOO_LARGE", "The file is larger than 5 MB."));
    up.mutate(f);
  };
  const busy = up.isPending || paste.isPending;
  const noText = err instanceof ApiError && err.code === "PDF_NO_TEXT";

  return (
    <div className="space-y-3">
      {mode === "choose" && (
        <div className="grid gap-3 sm:grid-cols-3">
          <button disabled={busy} onClick={() => fileRef.current?.click()}
            onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); pick(e.dataTransfer.files[0]); }}
            className="card p-4 text-left hover:border-brand-600 transition-colors disabled:opacity-60">
            <FileUp className="h-5 w-5 text-brand-700" aria-hidden />
            <div className="font-medium mt-2 text-sm">Upload a PDF</div>
            <div className="text-xs text-ink-muted mt-1">Text-based PDF, up to 5 MB and 5 pages. Drag and drop works too.</div>
          </button>
          <button disabled={busy} onClick={() => setMode("paste")} className="card p-4 text-left hover:border-brand-600 transition-colors">
            <ClipboardPaste className="h-5 w-5 text-brand-700" aria-hidden />
            <div className="font-medium mt-2 text-sm">Paste resume text</div>
            <div className="text-xs text-ink-muted mt-1">Useful for scanned PDFs or Word documents.</div>
          </button>
          <button disabled={busy} onClick={() => nav("/app/resume?new=scratch")} className="card p-4 text-left hover:border-brand-600 transition-colors">
            <PenLine className="h-5 w-5 text-brand-700" aria-hidden />
            <div className="font-medium mt-2 text-sm">Build from scratch</div>
            <div className="text-xs text-ink-muted mt-1">A guided form with a live preview.</div>
          </button>
          <input ref={fileRef} type="file" accept="application/pdf,.pdf" className="hidden"
            onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ""; }} />
        </div>
      )}
      {mode === "paste" && (
        <div className="space-y-2">
          <Textarea rows={10} value={text} onChange={(e) => setText(e.target.value)} maxLength={30000}
            placeholder="Paste the full text of your resume…" aria-label="Resume text" />
          <div className="flex flex-wrap gap-2 items-center">
            <Button onClick={() => paste.mutate()} disabled={text.trim().length < 300} loading={paste.isPending}
              icon={<Upload className="h-4 w-4" />}>Structure my resume</Button>
            <Button variant="ghost" onClick={() => setMode("choose")}>Back</Button>
            <span className="text-xs text-ink-subtle">{text.trim().length < 300 ? "At least 300 characters" : `${text.length.toLocaleString()} characters`}</span>
          </div>
        </div>
      )}
      <AIProgress active={busy} stages={up.isPending ? ["Uploading…", "Reading text from your PDF…", "Structuring sections…",
        "Checking every bullet against your text…"] : ["Structuring sections…", "Checking every bullet against your text…"]} />
      {err != null && (
        noText ? (
          <Notice tone="warn" title="We couldn't read text from this PDF"
            action={<div className="flex gap-2"><Button size="sm" variant="secondary" onClick={() => { setErr(null); setMode("paste"); }}>Paste text</Button>
              <Button size="sm" variant="secondary" onClick={() => nav("/app/resume?new=scratch")}>Build from scratch</Button></div>}>
            It may be a scanned image. Scanned-PDF OCR isn't part of this version, so nothing was analysed.
          </Notice>
        ) : <ErrorState error={err} compact />
      )}
      <p className="text-xs text-ink-subtle">Your original PDF isn't stored. Contact details are removed before any text is sent to the AI provider.</p>
    </div>
  );
}

/* ------------------------------------------------------------------ gaps & actions */
export function GapCard({ gap, showInputs = true }: { gap: Gap; showInputs?: boolean }) {
  const [open, setOpen] = useState(false);
  const subject = gap.skill?.name ?? `Interview: ${gap.interview_dimension}`;
  return (
    <div className="rounded-md border border-line bg-white p-3.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs tabular-nums text-ink-subtle">#{gap.rank}</span>
            <span className="font-semibold text-[15px]">{subject}</span>
            <Badge tone={GAP_TONE[gap.type] ?? "neutral"}>{gap.label}</Badge>
            <Badge tone="neutral">{IMPORTANCE_LABEL[gap.importance] ?? gap.importance}</Badge>
          </div>
          <p className="text-sm text-ink-muted mt-1.5 leading-relaxed">{gap.explanation}</p>
        </div>
        <div className="text-right shrink-0">
          <div className="text-[11px] text-ink-subtle">Priority</div>
          <div className="text-xl font-semibold tabular-nums">{gap.priority}</div>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <LinkButton to={gap.next_action.deep_link} size="sm" icon={<ArrowRight className="h-3.5 w-3.5" />}>{gap.next_action.label}</LinkButton>
        {showInputs && <button className="text-xs text-brand-800 hover:underline" onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? "Hide" : "How was this ranked?"}</button>}
      </div>
      {open && (
        <div className="mt-2 rounded bg-slate-50 p-2.5 text-xs text-ink-muted space-y-1">
          <div className="font-mono">P = min(100, round(100 × I × S × C) + B)</div>
          <div>I (importance) = {gap.inputs.I} · S (severity) = {gap.inputs.S} · C (confidence) = {gap.inputs.C}
            {gap.inputs.B_prereq ? ` · B = +${gap.inputs.B_prereq}` : ""}</div>
          <div>Resume level R = {gap.inputs.R ?? "no resume"} · Demonstrated D = {gap.inputs.D === null || gap.inputs.D === undefined ? "not assessed" : `${Math.round(gap.inputs.D * 100)}%`} · Evidence n = {gap.inputs.n}</div>
          {gap.adjustments.map((a) => <div key={a}>{a}</div>)}
        </div>
      )}
    </div>
  );
}

export function NextActionCard({ data, loading }: { data?: NextActions; loading?: boolean }) {
  if (loading) return <Skeleton className="h-36" />;
  const p = data?.primary;
  if (!p) return null;
  const isExternal = p.deep_link.startsWith("http");
  return (
    <Card className="border-brand-200 bg-gradient-to-b from-brand-50/60 to-white">
      <CardBody>
        <div className="text-xs font-medium uppercase tracking-wide text-brand-800">Recommended next action</div>
        <div className="mt-1.5 flex flex-col md:flex-row md:items-start md:justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold">{p.title}</h2>
            <p className="text-sm text-ink-muted mt-1 max-w-prose">{p.why}</p>
            {p.based_on.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {p.based_on.map((b) => <Badge key={b} tone="neutral">{b}</Badge>)}
              </div>
            )}
          </div>
          <div className="flex flex-col items-start md:items-end gap-1 shrink-0">
            {isExternal ? <a className="inline-flex items-center gap-2 h-10 px-4 rounded-md bg-brand-700 text-white font-medium" href={p.deep_link} target="_blank" rel="noopener noreferrer">Start <ArrowRight className="h-4 w-4" /></a>
              : <LinkButton to={p.deep_link} icon={<ArrowRight className="h-4 w-4" />}>Start</LinkButton>}
            <span className="text-xs text-ink-subtle">~{p.minutes} min · rule {p.score_breakdown.rule}, score {p.score_breakdown.score}</span>
          </div>
        </div>
        {data!.alternatives.length > 0 && (
          <div className="mt-4 border-t border-line pt-3">
            <div className="text-xs text-ink-muted mb-1.5">Other good options</div>
            <ul className="grid gap-1.5 sm:grid-cols-3">
              {data!.alternatives.map((a: Recommendation) => (
                <li key={a.title}><Link to={a.deep_link} className="block rounded-md border border-line bg-white px-3 py-2 text-sm hover:border-brand-600">
                  <div className="font-medium leading-snug">{a.title}</div>
                  <div className="text-xs text-ink-subtle mt-0.5">~{a.minutes} min</div>
                </Link></li>
              ))}
            </ul>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

export function SectionCard({ title, subtitle, icon, action, children, className }: { title: string;
  subtitle?: ReactNode; icon?: ReactNode; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <Card className={className}>
      <CardHeader title={title} subtitle={subtitle} icon={icon} action={action} />
      <CardBody>{children}</CardBody>
    </Card>
  );
}

export function useInvalidateAll() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries();
}

export { errorMessage };
