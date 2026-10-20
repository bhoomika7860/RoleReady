import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check, CheckCircle2, Eye, FileText, History, Pencil, Plus, Printer, RefreshCw, Save, ShieldCheck, Sparkles, Trash2,
  Wand2, X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, del, get, patch, post } from "@/api/client";
import type { Analysis, Resume, ResumeContent, ResumeVersion, Suggestion } from "@/api/types";
import { ResumeImport, SectionCard } from "@/components/domain";
import {
  AIProgress, AITag, Badge, Button, Card, CardBody, cx, Dialog, EmptyState, ErrorState, EvidenceChip, Field, Input,
  Notice, PageHeader, PageSkeleton, ProgressBar, Select, Tabs, useToast,
} from "@/components/ui";
import { useActiveTargetId, useSession } from "@/hooks/session";
import { wordDiff } from "@/lib/diff";
import { fmtDateTime } from "@/lib/format";
import { cleanContent, emptyContent, ResumeEditor, ResumePreview, validateContent } from "./resume/ResumeEditor";

type Tab = "edit" | "match" | "improve" | "history";

export default function ResumePage() {
  const [params, setParams] = useSearchParams();
  const resumes = useQuery({ queryKey: ["resumes"], queryFn: () => get<Resume[]>("/resumes") });
  const isNew = params.get("new");
  const selectedId = params.get("id") ?? resumes.data?.[0]?.id;

  if (resumes.isLoading) return <PageSkeleton />;
  if (resumes.isError) return <ErrorState error={resumes.error} onRetry={() => resumes.refetch()} />;
  if (isNew === "scratch") return <ScratchCreate onCreated={(id) => setParams({ id, tab: "edit" })} />;
  if (!resumes.data!.length || isNew === "import") {
    return (
      <div className="max-w-3xl space-y-5">
        <PageHeader title="Resume Studio" subtitle="Bring in your resume to see which job requirements it evidences." />
        <Card><CardBody><ResumeImport onImported={(id) => setParams({ id, tab: "edit" })} /></CardBody></Card>
      </div>
    );
  }
  return <ResumeWorkspace resumeId={selectedId!} all={resumes.data!} />;
}

function ScratchCreate({ onCreated }: { onCreated: (id: string) => void }) {
  const { data: me } = useSession();
  const qc = useQueryClient();
  const [content, setContent] = useState<ResumeContent>(() => {
    try {
      const saved = localStorage.getItem(`rr-draft-new-${me?.user.id}`);
      if (saved) return JSON.parse(saved);
    } catch { /* storage unavailable */ }
    return emptyContent(me?.user.preferred_name ?? "");
  });
  useEffect(() => {
    const t = setTimeout(() => { try { localStorage.setItem(`rr-draft-new-${me?.user.id}`, JSON.stringify(content)); } catch { /* ignore */ } }, 800);
    return () => clearTimeout(t);
  }, [content, me?.user.id]);
  const errors = validateContent(content);
  const create = useMutation({
    mutationFn: () => post("/resumes", { title: "My resume", content: cleanContent(content) }),
    onSuccess: (d) => {
      try { localStorage.removeItem(`rr-draft-new-${me?.user.id}`); } catch { /* ignore */ }
      qc.invalidateQueries();
      onCreated(d.resume_id);
    },
  });
  return (
    <div className="space-y-5">
      <PageHeader title="Build your resume" subtitle="Fill in what you have. A draft is kept in this browser until you save." />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <ResumeEditor value={content} onChange={setContent} />
        <div className="lg:sticky lg:top-6 h-fit space-y-3">
          <ResumePreview c={content} />
          {errors.length > 0 && <Notice tone="warn"><ul className="list-disc pl-4">{errors.map((e) => <li key={e}>{e}</li>)}</ul></Notice>}
          {create.isError && <ErrorState error={create.error} compact />}
          <Button onClick={() => create.mutate()} disabled={errors.length > 0} loading={create.isPending} icon={<Save className="h-4 w-4" />}>Save resume</Button>
        </div>
      </div>
    </div>
  );
}

function ResumeWorkspace({ resumeId, all }: { resumeId: string; all: Resume[] }) {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "edit";
  const setTab = (t: Tab) => setParams({ id: resumeId, tab: t });
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["resume", resumeId], queryFn: () => get<Resume>(`/resumes/${resumeId}`) });
  const [confirmDelete, setConfirmDelete] = useState(false);
  const remove = useMutation({ mutationFn: () => del(`/resumes/${resumeId}`),
    onSuccess: () => { qc.invalidateQueries(); setConfirmDelete(false); toast("Resume deleted"); nav("/app/resume", { replace: true }); } });

  if (q.isLoading) return <PageSkeleton />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const r = q.data!;
  return (
    <div className="space-y-4">
      <PageHeader title="Resume Studio"
        subtitle={<span>{r.title} · version {r.current_version?.version_number} · {r.reviewed_at ? "reviewed" : "not reviewed yet"}</span>}
        action={<>
          {all.length > 1 && <Select aria-label="Choose resume" className="h-9 py-1 text-sm w-48" value={resumeId}
            onChange={(e) => setParams({ id: e.target.value, tab })}>{all.map((x) => <option key={x.id} value={x.id}>{x.title}</option>)}</Select>}
          <Button size="sm" variant="secondary" icon={<Plus className="h-4 w-4" />} onClick={() => setParams({ new: "import" })}>New</Button>
          <Button size="sm" variant="ghost" icon={<Trash2 className="h-4 w-4" />} onClick={() => setConfirmDelete(true)}>Delete</Button>
        </>} />
      {!r.reviewed_at && (
        <Notice tone="warn" title="Review your parsed resume">Nothing is treated as fact until you've checked the extracted
          sections. Correct anything that's wrong, then press “Looks right — save”.</Notice>
      )}
      <Tabs<Tab> label="Resume sections" value={tab} onChange={setTab} tabs={[
        { id: "edit", label: "Edit & review" }, { id: "match", label: "Requirement match" },
        { id: "improve", label: "Improve bullets" }, { id: "history", label: "History" }]} />
      {tab === "edit" && r.current_version && <EditTab resume={r} version={r.current_version} />}
      {tab === "match" && <MatchTab resume={r} />}
      {tab === "improve" && r.current_version && <ImproveTab resume={r} version={r.current_version} />}
      {tab === "history" && <HistoryTab resumeId={r.id} />}
      <Dialog open={confirmDelete} onClose={() => setConfirmDelete(false)} title="Delete this resume?"
        footer={<><Button variant="secondary" onClick={() => setConfirmDelete(false)}>Cancel</Button>
          <Button variant="danger" loading={remove.isPending} onClick={() => remove.mutate()}>Delete permanently</Button></>}>
        This removes the resume, all its versions, analyses and rewrite suggestions, and the resume evidence used in your
        gaps. Assessment and interview results are kept.
      </Dialog>
    </div>
  );
}

function EditTab({ resume, version }: { resume: Resume; version: ResumeVersion }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [content, setContent] = useState<ResumeContent>(version.content);
  const [view, setView] = useState<"preview" | "raw">("preview");
  const [stale, setStale] = useState(false);
  useEffect(() => { setContent(version.content); setStale(false); }, [version.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const dirty = useMemo(() => JSON.stringify(content) !== JSON.stringify(version.content), [content, version.content]);
  useEffect(() => {
    if (!dirty) return;
    const h = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [dirty]);
  const errors = validateContent(content);
  const save = useMutation({
    mutationFn: (markReviewed: boolean) => post<ResumeVersion>(`/resumes/${resume.id}/versions`, {
      content: cleanContent(content), base_version_id: version.id, mark_reviewed: markReviewed,
      change_summary: markReviewed && !resume.reviewed_at ? "Reviewed after import" : "Edited" }, 120_000),
    onSuccess: () => {
      ["resume", "resumes", "analysis", "dashboard", "gaps", "plan"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
      toast("Saved as a new version");
    },
    onError: (e) => { if (e instanceof ApiError && e.code === "STALE_VERSION") setStale(true); },
  });
  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
      <div className="space-y-3">
        <ResumeEditor value={content} onChange={setContent} />
        {errors.length > 0 && <Notice tone="warn"><ul className="list-disc pl-4">{errors.map((e) => <li key={e}>{e}</li>)}</ul></Notice>}
        {stale && <Notice tone="warn" title="A newer version exists" action={<Button size="sm" variant="secondary"
          onClick={() => qc.invalidateQueries({ queryKey: ["resume", resume.id] })}>Load latest</Button>}>
          This resume was changed elsewhere. Load the latest version, then reapply your edits.</Notice>}
        {save.isError && !stale && <ErrorState error={save.error} compact />}
        <div className="flex flex-wrap gap-2 sticky bottom-20 lg:bottom-4 bg-canvas/95 py-2 z-10">
          {!resume.reviewed_at ? (
            <Button onClick={() => save.mutate(true)} disabled={errors.length > 0} loading={save.isPending} icon={<Check className="h-4 w-4" />}>Looks right — save</Button>
          ) : (
            <Button onClick={() => save.mutate(false)} disabled={!dirty || errors.length > 0} loading={save.isPending} icon={<Save className="h-4 w-4" />}>Save new version</Button>
          )}
          {dirty && <Button variant="ghost" onClick={() => setContent(version.content)}>Discard changes</Button>}
          <span className="text-xs text-ink-subtle self-center">{dirty ? "Unsaved changes" : "All changes saved"}</span>
        </div>
      </div>
      <div className="lg:sticky lg:top-6 h-fit space-y-2">
        <div className="flex gap-2">
          <Button size="sm" variant={view === "preview" ? "subtle" : "ghost"} icon={<Eye className="h-4 w-4" />} onClick={() => setView("preview")}>Preview</Button>
          {resume.raw_text && <Button size="sm" variant={view === "raw" ? "subtle" : "ghost"} icon={<FileText className="h-4 w-4" />} onClick={() => setView("raw")}>Extracted text</Button>}
          <Button size="sm" variant="ghost" icon={<Printer className="h-4 w-4" />} onClick={() => window.print()}>Print / PDF</Button>
        </div>
        {view === "preview" ? <ResumePreview c={content} /> : (
          <pre className="bg-white border border-line rounded-md p-4 text-xs whitespace-pre-wrap max-h-[70vh] overflow-y-auto">{resume.raw_text}</pre>
        )}
      </div>
    </div>
  );
}

function MatchTab({ resume }: { resume: Resume }) {
  const tid = useActiveTargetId();
  const qc = useQueryClient();
  const [filter, setFilter] = useState<"all" | "evidenced" | "weak" | "not_shown">("all");
  const q = useQuery({
    queryKey: ["analysis", resume.id, tid], enabled: !!tid, retry: false,
    queryFn: () => get<Analysis>(`/resumes/${resume.id}/analyses/latest?target_id=${tid}`),
  });
  const run = useMutation({ mutationFn: () => post<Analysis>(`/resumes/${resume.id}/analyses`, { target_id: tid }),
    onSuccess: (a) => { qc.setQueryData(["analysis", resume.id, tid], a); qc.invalidateQueries({ queryKey: ["dashboard"] }); qc.invalidateQueries({ queryKey: ["gaps"] }); } });
  if (!tid) return <EmptyState title="Choose a target job first">Coverage is measured against a target's requirements.</EmptyState>;
  if (q.isLoading) return <PageSkeleton />;
  const noAnalysis = q.error instanceof ApiError && q.error.code === "NO_ANALYSIS";
  if (q.isError && !noAnalysis) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  if (noAnalysis || !q.data) {
    return <EmptyState title="Not analysed yet" action={<Button loading={run.isPending} onClick={() => run.mutate()}>Run analysis</Button>}>
      Compare this resume with your confirmed requirements.</EmptyState>;
  }
  const a = q.data;
  const rows = a.requirements.filter((r) => filter === "all" || r.state === filter);
  return (
    <div className="space-y-4">
      <Card><CardBody>
        <div className="flex flex-col sm:flex-row sm:items-center gap-4 justify-between">
          <div>
            <div className="text-xs text-ink-muted">Requirement coverage</div>
            <div className="flex items-baseline gap-1"><span className="text-3xl font-semibold tabular-nums">{a.coverage_score}</span><span className="text-sm text-ink-subtle">/100</span></div>
            <ProgressBar value={a.coverage_score} className="w-48 mt-1" label="Coverage" />
          </div>
          <div className="flex flex-wrap gap-1.5">
            <Badge tone="ok">{a.counts.evidenced} evidenced</Badge><Badge tone="warn">{a.counts.weak} weak</Badge><Badge>{a.counts.not_shown} not shown</Badge>
          </div>
          <Button size="sm" variant="secondary" loading={run.isPending} icon={<RefreshCw className="h-4 w-4" />} onClick={() => run.mutate()}>Re-run</Button>
        </div>
        <p className="text-xs text-ink-subtle mt-3">{a.disclaimer}</p>
        <details className="text-xs text-ink-muted mt-1"><summary className="cursor-pointer">How is this calculated?</summary><p className="mt-1">{a.formula}</p></details>
        {(a.stale || a.requirements_changed) && <Notice tone="warn" className="mt-3">{a.stale ? "Your resume changed since this analysis." : "Your requirements changed since this analysis."} Re-run to update.</Notice>}
      </CardBody></Card>
      <div className="flex flex-wrap gap-2" role="group" aria-label="Filter requirements">
        {(["all", "evidenced", "weak", "not_shown"] as const).map((f) => (
          <Button key={f} size="sm" variant={filter === f ? "subtle" : "ghost"} onClick={() => setFilter(f)}>
            {{ all: "All", evidenced: "Evidenced", weak: "Weak", not_shown: "Not shown" }[f]}</Button>
        ))}
      </div>
      <div className="space-y-2.5">
        {rows.map((r) => (
          <div key={r.requirement_id} className="rounded-md border border-line bg-white p-3.5">
            <div className="flex flex-wrap items-center gap-1.5 justify-between">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="font-medium">{r.skill?.name ?? r.raw_phrase}</span>
                <Badge>{r.importance}</Badge>
              </div>
              <EvidenceChip state={r.state} />
            </div>
            <p className="text-sm text-ink-muted mt-1.5">{r.explanation}</p>
            {r.locations.length > 0 && (
              <ul className="mt-2 space-y-1">
                {r.locations.slice(0, 3).map((l, i) => (
                  <li key={i} className="text-xs bg-slate-50 rounded px-2 py-1.5"><span className="text-ink-subtle capitalize">{l.entry_name ?? l.section}: </span>“{l.text}”</li>
                ))}
              </ul>
            )}
            {r.suggestion && <p className="mt-2 text-sm text-brand-800">{r.suggestion.text}</p>}
          </div>
        ))}
      </div>
    </div>
  );
}

function DiffView({ a, b }: { a: string; b: string }) {
  return (
    <p className="text-sm leading-relaxed">
      {wordDiff(a, b).map((p, i) => (
        <span key={i} className={cx(p.type === "add" && "bg-green-100 text-green-900 rounded-sm",
          p.type === "del" && "bg-red-50 text-red-800 line-through decoration-red-400")}>{p.text}</span>
      ))}
    </p>
  );
}

function ImproveTab({ resume, version }: { resume: Resume; version: ResumeVersion }) {
  const tid = useActiveTargetId();
  const qc = useQueryClient();
  const toast = useToast();
  const [bulletId, setBulletId] = useState<string>("");
  const [result, setResult] = useState<{ suggestions: Suggestion[]; questions: { id: string; text: string }[] } | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState<Record<string, string>>({});
  const bullets = [...version.content.experience.flatMap((e) => e.bullets.map((b) => ({ ...b, entry: e.title }))),
    ...version.content.projects.flatMap((p) => p.bullets.map((b) => ({ ...b, entry: p.name })))];
  const request = useMutation({
    mutationFn: () => post(`/resumes/${resume.id}/rewrite-suggestions`, { version_id: version.id, bullet_id: bulletId, target_id: tid }, 90_000),
    onSuccess: (d) => { setResult(d); setAnswers({}); setEditing({}); },
  });
  const regenerate = useMutation({
    mutationFn: async (s: Suggestion) => {
      await patch(`/rewrite-suggestions/${s.id}`, { action: "answer", answers: (result?.questions ?? []).filter((q) => answers[q.id]?.trim())
        .map((q) => ({ question_id: q.id, question: q.text, answer: answers[q.id].trim() })) });
      return post(`/rewrite-suggestions/${s.id}/regenerate`, {}, 90_000);
    },
    onSuccess: (d) => setResult(d),
  });
  const decide = useMutation({
    mutationFn: ({ s, action, text }: { s: Suggestion; action: "accept" | "reject"; text?: string }) =>
      patch(`/rewrite-suggestions/${s.id}`, { action, edited_text: text }),
    onSuccess: (_d, v) => {
      if (v.action === "accept") {
        toast("Applied as a new resume version");
        setResult(null); setBulletId("");
        ["resume", "analysis", "dashboard"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
      } else setResult((r) => r && { ...r, suggestions: r.suggestions.filter((x) => x.id !== v.s.id) });
    },
  });
  if (!bullets.length) return <EmptyState title="No bullets to improve">Add experience or project bullets in the editor first.</EmptyState>;
  const anyAnswered = Object.values(answers).some((a) => a.trim());
  return (
    <div className="space-y-4 max-w-3xl">
      <Notice tone="info" title="Fact-guarded rewriting">Suggestions may only reuse facts from the same entry and your
        answers. Any new number, technology, organisation or claim is caught by an automatic check and flagged — and nothing
        changes your resume until you accept it.</Notice>
      <Card><CardBody className="space-y-3">
        <Field label="Choose a bullet to improve" htmlFor="pick-bullet">
          <Select id="pick-bullet" value={bulletId} onChange={(e) => { setBulletId(e.target.value); setResult(null); }}>
            <option value="">Select…</option>
            {bullets.map((b) => <option key={b.id} value={b.id}>{b.entry}: {b.text.slice(0, 90)}{b.text.length > 90 ? "…" : ""}</option>)}
          </Select>
        </Field>
        <Button onClick={() => request.mutate()} disabled={!bulletId} loading={request.isPending} icon={<Wand2 className="h-4 w-4" />}>Suggest stronger wording</Button>
        <AIProgress active={request.isPending || regenerate.isPending} stages={["Drafting suggestions…", "Checking every fact against your resume…"]} />
        {request.isError && <ErrorState error={request.error} compact />}
        {regenerate.isError && <ErrorState error={regenerate.error} compact />}
      </CardBody></Card>

      {result && (
        <div className="space-y-3">
          {result.suggestions.filter((s) => s.suggested).length === 0 && (
            <Notice tone="warn" title="We couldn't improve this bullet without adding details you haven't provided">
              Answer the questions below (or skip them) and try again.</Notice>
          )}
          {result.suggestions.filter((s) => s.suggested).map((s) => (
            <Card key={s.id}><CardBody className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <AITag label="AI suggestion" />
                {s.status === "flagged" ? <Badge tone="bad">Couldn't be verified — needs manual correction</Badge>
                  : <Badge tone="ok" icon={<ShieldCheck className="h-3 w-3" />}>All facts found in your resume</Badge>}
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <div><div className="text-xs text-ink-muted mb-1">Original</div><p className="text-sm rounded bg-slate-50 p-2.5">{s.original}</p></div>
                <div><div className="text-xs text-ink-muted mb-1">Suggested (changes highlighted)</div><div className="rounded bg-slate-50 p-2.5"><DiffView a={s.original} b={s.suggested!} /></div></div>
              </div>
              {s.rationale && <p className="text-xs text-ink-muted">Why: {s.rationale}</p>}
              {s.guard_report.violations.length > 0 && (
                <Notice tone="bad" title="Unsupported details found">
                  {s.guard_report.violations.map((v) => v.replace(":", ": ")).join(" · ")}. Edit the text yourself before using it.
                </Notice>
              )}
              {editing[s.id] !== undefined ? (
                <div className="space-y-2">
                  <Input value={editing[s.id]} maxLength={300} aria-label="Edit suggestion" onChange={(e) => setEditing({ ...editing, [s.id]: e.target.value })} />
                  <div className="flex gap-2">
                    <Button size="sm" onClick={() => decide.mutate({ s, action: "accept", text: editing[s.id] })} loading={decide.isPending}>Use my edited version</Button>
                    <Button size="sm" variant="ghost" onClick={() => { const n = { ...editing }; delete n[s.id]; setEditing(n); }}>Cancel</Button>
                  </div>
                </div>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {s.status !== "flagged" && <Button size="sm" icon={<CheckCircle2 className="h-4 w-4" />} loading={decide.isPending}
                    onClick={() => decide.mutate({ s, action: "accept" })}>Accept</Button>}
                  <Button size="sm" variant="secondary" icon={<Pencil className="h-4 w-4" />} onClick={() => setEditing({ ...editing, [s.id]: s.suggested! })}>Edit, then use</Button>
                  <Button size="sm" variant="ghost" icon={<X className="h-4 w-4" />} onClick={() => decide.mutate({ s, action: "reject" })}>Reject</Button>
                </div>
              )}
              {decide.isError && <ErrorState error={decide.error} compact />}
            </CardBody></Card>
          ))}
          {result.questions.length > 0 && result.suggestions[0] && (
            <SectionCard title="Clarifying questions" icon={<Sparkles className="h-4 w-4" />}
              subtitle="Answer only what's true. Unanswered questions are fine — the bullet just stays qualitative.">
              <div className="space-y-3">
                {result.questions.map((qq) => (
                  <Field key={qq.id} label={qq.text} htmlFor={`q-${qq.id}`}>
                    <Input id={`q-${qq.id}`} maxLength={300} value={answers[qq.id] ?? ""} placeholder="Leave blank if you don't know"
                      onChange={(e) => setAnswers({ ...answers, [qq.id]: e.target.value })} />
                  </Field>
                ))}
                <Button variant="secondary" disabled={!anyAnswered} loading={regenerate.isPending}
                  onClick={() => regenerate.mutate(result.suggestions[0])} icon={<RefreshCw className="h-4 w-4" />}>Regenerate with my answers</Button>
              </div>
            </SectionCard>
          )}
        </div>
      )}
    </div>
  );
}

function HistoryTab({ resumeId }: { resumeId: string }) {
  const q = useQuery({ queryKey: ["resume", resumeId, "versions"],
    queryFn: () => get<Omit<ResumeVersion, "content">[]>(`/resumes/${resumeId}/versions`) });
  if (q.isLoading) return <PageSkeleton />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  return (
    <SectionCard title="Version history" icon={<History className="h-4 w-4" />} subtitle="Every save creates a new version; nothing is overwritten.">
      <ul className="divide-y divide-line">
        {q.data!.map((v) => (
          <li key={v.id} className="py-2.5 flex items-center justify-between gap-3 text-sm">
            <div><span className="font-medium">v{v.version_number}</span> · {v.change_summary ?? "Saved"}</div>
            <div className="flex items-center gap-2 shrink-0">
              <Badge tone={v.created_by === "ai_tailor" ? "info" : v.created_by === "import" ? "neutral" : "brand"}>
                {{ import: "Imported", user: "Edited by you", ai_tailor: "Accepted AI rewrite" }[v.created_by] ?? v.created_by}</Badge>
              <span className="text-xs text-ink-subtle">{fmtDateTime(v.created_at)}</span>
            </div>
          </li>
        ))}
      </ul>
    </SectionCard>
  );
}
