import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, CheckCircle2, ClipboardCheck, Clock, CloudOff, Loader2, Send } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, get, post, put } from "@/api/client";
import type { AssessmentItem, AssessmentState, AssessmentSummary } from "@/api/types";
import { NeedTarget } from "@/components/domain";
import {
  AIProgress, Badge, Button, Card, CardBody, cx, Dialog, ErrorState, Notice, PageHeader, PageSkeleton, ProgressBar,
  RichText, Textarea,
} from "@/components/ui";
import { fmtDateTime, wordCount } from "@/lib/format";

export default function AssessmentPage() {
  return <NeedTarget>{(tid) => <AssessmentHome tid={tid} />}</NeedTarget>;
}

function AssessmentHome({ tid }: { tid: string }) {
  const [params, setParams] = useSearchParams();
  const qc = useQueryClient();
  const checkpoint = params.get("checkpoint");
  const openId = params.get("id");
  const list = useQuery({ queryKey: ["assessments", tid], queryFn: () => get<AssessmentSummary[]>(`/targets/${tid}/assessments`) });
  const start = useMutation({
    mutationFn: (body: { kind: string; skill_slug?: string }) => post<AssessmentState>(`/targets/${tid}/assessments`, body),
    onSuccess: (a) => { qc.setQueryData(["assessment", a.id], a); setParams({ id: a.id }); qc.invalidateQueries({ queryKey: ["assessments", tid] }); },
  });
  if (openId) return <Runner id={openId} />;
  if (list.isLoading) return <PageSkeleton />;
  if (list.isError) return <ErrorState error={list.error} onRetry={() => list.refetch()} />;
  const inProgress = list.data!.find((a) => a.status === "in_progress");
  const diagDone = list.data!.some((a) => a.kind === "diagnostic" && a.status !== "in_progress");

  if (checkpoint) {
    return (
      <div className="max-w-2xl space-y-5">
        <PageHeader eyebrow="Checkpoint" title={`Re-measure ${checkpoint.replace(/-/g, " ")}`}
          subtitle="6 questions on one skill. Checkpoints keep the same difficulty mix so results can be compared honestly." />
        <Card><CardBody className="space-y-3">
          <ul className="text-sm text-ink-muted space-y-1 list-disc pl-5">
            <li>2 easy, 2 medium and 2 hard questions (matching your previous checkpoint on this skill).</li>
            <li>About 8 minutes. Answers save automatically.</li>
            <li>Change is reported only if it's bigger than one question's worth (17 points).</li>
          </ul>
          {start.isError && <ErrorState error={start.error} compact />}
          <div className="flex gap-2">
            <Button loading={start.isPending} onClick={() => start.mutate({ kind: "checkpoint", skill_slug: checkpoint })} icon={<ArrowRight className="h-4 w-4" />}>Start checkpoint</Button>
            <Button variant="ghost" onClick={() => setParams({})}>Back</Button>
          </div>
        </CardBody></Card>
      </div>
    );
  }

  return (
    <div className="max-w-3xl space-y-5">
      <PageHeader title="Assessments" subtitle="Measure what you can demonstrate — separate from what your resume shows." />
      {inProgress && (
        <Notice tone="info" title={`You have a ${inProgress.kind} in progress`}
          action={<Button size="sm" onClick={() => setParams({ id: inProgress.id })}>Resume</Button>}>
          Started {fmtDateTime(inProgress.created_at)}. Your answers are saved; it expires {fmtDateTime(inProgress.expires_at)}.
        </Notice>
      )}
      <Card><CardBody className="space-y-3">
        <div className="flex items-center gap-2"><ClipboardCheck className="h-5 w-5 text-brand-700" /><h2 className="font-semibold">Diagnostic assessment</h2>
          {diagDone && <Badge tone="ok">Completed</Badge>}</div>
        <ul className="text-sm text-ink-muted space-y-1 list-disc pl-5">
          <li>15 questions on your role's most important skills: multiple choice, code reading and 3 short written answers.</li>
          <li>About 20 minutes, untimed per question. You can pause — answers save as you go and you can resume within 48 hours.</li>
          <li>Objective questions are scored by code. Short answers are judged against a published rubric by AI, quoting your answer.</li>
          <li>Questions are curated for the role, not taken from any company's interviews.</li>
        </ul>
        {start.isError && <ErrorState error={start.error} compact />}
        <Button loading={start.isPending} onClick={() => start.mutate({ kind: "diagnostic" })} icon={<ArrowRight className="h-4 w-4" />}>
          {inProgress?.kind === "diagnostic" ? "Resume diagnostic" : diagDone ? "Take another diagnostic" : "Start diagnostic"}
        </Button>
      </CardBody></Card>
      {list.data!.length > 0 && (
        <Card><CardBody>
          <h2 className="font-semibold mb-2">Past attempts</h2>
          <ul className="divide-y divide-line text-sm">
            {list.data!.map((a) => (
              <li key={a.id} className="py-2.5 flex items-center justify-between gap-2">
                <div><span className="font-medium">{a.kind === "diagnostic" ? "Diagnostic" : `${a.skill?.name} checkpoint`}</span>
                  <span className="text-ink-subtle"> · {fmtDateTime(a.created_at)}</span></div>
                <div className="flex items-center gap-2">
                  {a.score !== null && <span className="tabular-nums font-medium">{a.score}/100</span>}
                  <Badge tone={a.status === "scored" ? "ok" : a.status === "in_progress" ? "info" : "warn"}>{a.status.replace("_", " ")}</Badge>
                  {a.status !== "in_progress" ? <a className="text-brand-800 hover:underline" href={`/app/results?assessment=${a.id}`}>Results</a>
                    : <button className="text-brand-800 hover:underline" onClick={() => setParams({ id: a.id })}>Open</button>}
                </div>
              </li>
            ))}
          </ul>
        </CardBody></Card>
      )}
    </div>
  );
}

type SaveState = "idle" | "saving" | "saved" | "offline";

function Runner({ id }: { id: string }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const q = useQuery({ queryKey: ["assessment", id], queryFn: () => get<AssessmentState>(`/assessments/${id}`) });
  const [pos, setPos] = useState<number | null>(null);
  const [responses, setResponses] = useState<Record<number, any>>({});
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [confirm, setConfirm] = useState(false);
  const timers = useRef<Record<number, ReturnType<typeof setTimeout>>>({});
  const pending = useRef<Record<number, any>>({});

  useEffect(() => {
    if (q.data && pos === null) {
      const init: Record<number, any> = {};
      q.data.items.forEach((it) => { if (it.response) init[it.position] = it.response; });
      setResponses(init);
      setPos(q.data.first_unanswered ?? 1);
    }
  }, [q.data, pos]);

  const flush = useCallback(async (p: number) => {
    const body = pending.current[p];
    if (body === undefined) return;
    setSaveState("saving");
    try {
      await put(`/assessments/${id}/items/${p}/response`, { response: body });
      if (pending.current[p] === body) delete pending.current[p];
      setSaveState(Object.keys(pending.current).length ? "saving" : "saved");
    } catch (e) {
      if (e instanceof ApiError && e.code === "ASSESSMENT_CLOSED") { qc.invalidateQueries({ queryKey: ["assessment", id] }); return; }
      setSaveState("offline");
      timers.current[p] = setTimeout(() => flush(p), 3000);
    }
  }, [id, qc]);

  const setAnswer = (p: number, resp: any) => {
    setResponses((r) => ({ ...r, [p]: resp }));
    pending.current[p] = resp;
    clearTimeout(timers.current[p]);
    timers.current[p] = setTimeout(() => flush(p), 800);
  };

  const flushAll = async () => {
    Object.keys(pending.current).forEach((k) => clearTimeout(timers.current[Number(k)]));
    await Promise.all(Object.keys(pending.current).map((k) => flush(Number(k))));
  };

  const submit = useMutation({
    mutationFn: async () => { await flushAll(); return post(`/assessments/${id}/submit`, {}, 150_000); },
    onSuccess: () => { qc.invalidateQueries(); nav(`/app/results?assessment=${id}`); },
    onError: (e) => { if (e instanceof ApiError && e.code === "ASSESSMENT_CLOSED") nav(`/app/results?assessment=${id}`); },
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!q.data || pos === null || (e.target as HTMLElement).tagName === "TEXTAREA") return;
      const item = q.data.items.find((i) => i.position === pos);
      if (e.key === "ArrowRight" && pos < q.data.items.length) setPos(pos + 1);
      if (e.key === "ArrowLeft" && pos > 1) setPos(pos - 1);
      const n = Number(e.key);
      if (item?.options && n >= 1 && n <= item.options.length && item.type !== "mcq_multi") {
        setAnswer(pos, { selected: [item.options[n - 1].id] });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (q.isLoading || pos === null) return <PageSkeleton />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const a = q.data!;
  if (a.status !== "in_progress") {
    return <Notice tone="info" title="This assessment is closed" action={<Button size="sm" onClick={() => nav(`/app/results?assessment=${id}`)}>See results</Button>}>
      It was {a.status.replace("_", " ")}.</Notice>;
  }
  const item = a.items.find((i) => i.position === pos)!;
  const answered = a.items.filter((i) => isAnswered(i, responses[i.position])).length;
  const unanswered = a.items.length - answered;

  return (
    <div className="max-w-3xl space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-xs uppercase tracking-wide text-brand-800 font-medium">{a.kind === "diagnostic" ? "Diagnostic" : `${a.skill?.name} checkpoint`}</div>
          <h1 className="text-xl font-semibold">Question {pos} of {a.items.length}</h1>
        </div>
        <SaveIndicator state={saveState} />
      </div>
      <ProgressBar value={answered} max={a.items.length} label="Answered" />
      <nav aria-label="Questions" className="flex flex-wrap gap-1.5">
        {a.items.map((i) => (
          <button key={i.position} onClick={() => setPos(i.position)} aria-current={i.position === pos ? "step" : undefined}
            aria-label={`Question ${i.position}${isAnswered(i, responses[i.position]) ? ", answered" : ""}`}
            className={cx("h-9 w-9 rounded-md text-sm font-medium border tabular-nums",
              i.position === pos ? "border-brand-700 bg-brand-700 text-white"
                : isAnswered(i, responses[i.position]) ? "border-brand-200 bg-brand-50 text-brand-800" : "border-line bg-white text-ink-muted")}>
            {i.position}</button>
        ))}
      </nav>
      <Card><CardBody className="space-y-4">
        <div className="flex flex-wrap gap-1.5">
          <Badge>{item.skill.name}</Badge><Badge tone="neutral">{item.difficulty}</Badge>
          <Badge tone="neutral">{typeLabel(item.type)}</Badge>
        </div>
        <RichText text={item.prompt} />
        <QuestionInput item={item} value={responses[item.position]} onChange={(v) => setAnswer(item.position, v)} />
        <p className="text-xs text-ink-subtle">{item.source_label}</p>
      </CardBody></Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Button variant="secondary" disabled={pos <= 1} onClick={() => setPos(pos - 1)} icon={<ArrowLeft className="h-4 w-4" />}>Previous</Button>
        <div className="flex gap-2">
          {pos < a.items.length && <Button variant="secondary" onClick={() => setPos(pos + 1)}>Next <ArrowRight className="h-4 w-4" /></Button>}
          <Button onClick={() => setConfirm(true)} icon={<Send className="h-4 w-4" />}>Submit</Button>
        </div>
      </div>
      <p className="text-xs text-ink-subtle">Tip: use ← → to move between questions and 1–6 to pick an option.</p>
      <Dialog open={confirm} onClose={() => !submit.isPending && setConfirm(false)} title="Submit your answers?"
        footer={<><Button variant="secondary" disabled={submit.isPending} onClick={() => setConfirm(false)}>Keep working</Button>
          <Button loading={submit.isPending} onClick={() => submit.mutate()}>Submit now</Button></>}>
        {unanswered > 0 ? <p><span className="font-medium text-ink">{unanswered} question{unanswered === 1 ? " is" : "s are"} unanswered</span> and will score 0
          (shown separately in your results).</p> : <p>All questions answered.</p>}
        <p className="mt-2">Short answers are evaluated by AI against a rubric — this can take up to a minute.</p>
        <div className="mt-3"><AIProgress active={submit.isPending} stages={["Scoring objective answers…", "Evaluating short answers against the rubric…",
          "Updating your skill evidence and gaps…"]} /></div>
        {submit.isError && <div className="mt-2"><ErrorState error={submit.error} compact /></div>}
      </Dialog>
    </div>
  );
}

function typeLabel(t: string) {
  return { mcq_single: "Multiple choice", mcq_multi: "Select all that apply", code_output: "Code reading",
    short_answer: "Short answer", approach: "Approach" }[t] ?? t;
}

function isAnswered(item: AssessmentItem, resp: any) {
  if (!resp) return false;
  if (item.options) return (resp.selected ?? []).length > 0;
  return (resp.text ?? "").trim().length > 0;
}

function QuestionInput({ item, value, onChange }: { item: AssessmentItem; value: any; onChange: (v: any) => void }) {
  if (item.options) {
    const selected: string[] = value?.selected ?? [];
    const multi = item.type === "mcq_multi";
    return (
      <fieldset className="space-y-2">
        <legend className="sr-only">Answer options</legend>
        {item.options.map((o, idx) => {
          const checked = selected.includes(o.id);
          return (
            <label key={o.id} className={cx("flex items-start gap-3 rounded-md border px-3 py-2.5 cursor-pointer transition-colors",
              checked ? "border-brand-600 bg-brand-50" : "border-line hover:border-slate-300 bg-white")}>
              <input type={multi ? "checkbox" : "radio"} name={`q-${item.position}`} checked={checked} className="mt-1 accent-brand-700"
                onChange={() => onChange({ selected: multi ? (checked ? selected.filter((s) => s !== o.id) : [...selected, o.id]) : [o.id] })} />
              <span className="text-sm"><span className="text-ink-subtle mr-1.5 tabular-nums">{idx + 1}.</span>
                <span className={cx(o.text.length < 60 && /[{}();=<>]/.test(o.text) && "font-mono")}>{o.text}</span></span>
            </label>
          );
        })}
      </fieldset>
    );
  }
  const text: string = value?.text ?? "";
  const wc = wordCount(text);
  return (
    <div>
      <Textarea rows={7} value={text} maxLength={4000} aria-label="Your answer" placeholder="Write your answer in a few sentences…"
        onChange={(e) => onChange({ text: e.target.value })} />
      <div className="flex justify-between text-xs text-ink-subtle mt-1">
        <span>{wc < 10 ? "At least 10 words are needed for an evaluation." : "Explain the idea and why — grammar isn't graded."}</span>
        <span className="tabular-nums">{wc} words</span>
      </div>
    </div>
  );
}

function SaveIndicator({ state }: { state: SaveState }) {
  if (state === "idle") return <span className="text-xs text-ink-subtle inline-flex items-center gap-1"><Clock className="h-3.5 w-3.5" />Answers save automatically</span>;
  if (state === "saving") return <span className="text-xs text-ink-muted inline-flex items-center gap-1" role="status"><Loader2 className="h-3.5 w-3.5 animate-spin" />Saving…</span>;
  if (state === "saved") return <span className="text-xs text-ok inline-flex items-center gap-1" role="status"><CheckCircle2 className="h-3.5 w-3.5" />Saved</span>;
  return <span className="text-xs text-warn inline-flex items-center gap-1" role="status"><CloudOff className="h-3.5 w-3.5" />Offline — will retry</span>;
}
