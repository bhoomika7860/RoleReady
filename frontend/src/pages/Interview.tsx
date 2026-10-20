import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Flag, MessageSquare, RotateCcw, Send, Sparkles } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { get, post } from "@/api/client";
import type { InterviewSession, RequirementsPayload, Turn } from "@/api/types";
import { NeedTarget, SectionCard } from "@/components/domain";
import {
  AIProgress, AITag, Badge, Button, Card, CardBody, cx, EmptyState, ErrorState, Field, Notice, PageHeader,
  PageSkeleton, Select, Textarea,
} from "@/components/ui";
import { fmtDateTime, wordCount } from "@/lib/format";

const DIMS = ["relevance", "correctness", "completeness", "reasoning", "clarity"] as const;
const DIM_HELP: Record<string, string> = { relevance: "Answers the question asked", correctness: "Technically accurate",
  completeness: "Covers the expected points", reasoning: "Explains why/how and trade-offs", clarity: "Logical, concise, defines terms" };

export default function InterviewPage() {
  return <NeedTarget>{(tid) => <InterviewHome tid={tid} />}</NeedTarget>;
}

function InterviewHome({ tid }: { tid: string }) {
  const [params, setParams] = useSearchParams();
  const qc = useQueryClient();
  const sid = params.get("session");
  const focus = params.get("focus");
  const [type, setType] = useState<"technical" | "project">("technical");
  const [skill, setSkill] = useState(params.get("skill") ?? "");
  const reqs = useQuery({ queryKey: ["requirements", tid], queryFn: () => get<RequirementsPayload>(`/targets/${tid}/requirements`) });
  const history = useQuery({ queryKey: ["interviews", tid], queryFn: () => get<{ items: InterviewSession[] }>(`/targets/${tid}/interviews`) });
  const start = useMutation({
    mutationFn: () => post<InterviewSession>(`/targets/${tid}/interviews`, { type, skill_slug: type === "technical" && skill ? skill : undefined }),
    onSuccess: (s) => { qc.setQueryData(["interview", s.id], s); qc.invalidateQueries({ queryKey: ["interviews", tid] }); setParams({ session: s.id }); },
  });
  if (sid) return <SessionView sid={sid} tid={tid} onExit={() => setParams({})} />;
  const skills = (reqs.data?.requirements ?? []).filter((r) => r.skill && r.scored);
  const open = history.data?.items.find((s) => s.status === "open");
  return (
    <div className="space-y-5 max-w-3xl">
      <PageHeader title="Mock interview" subtitle="Typed answers, scored on a published five-part rubric. Up to 5 questions per session." />
      {focus && <Notice tone="info">Your recent answers were weakest on <span className="font-medium capitalize">{focus}</span>. Keep an eye on it in this session.</Notice>}
      {open && <Notice tone="info" title="You have an open session" action={<Button size="sm" onClick={() => setParams({ session: open.id })}>Continue</Button>}>
        {open.type === "technical" ? `Technical — ${open.skill?.name}` : "Project deep-dive"} · {open.questions_asked} question(s) so far</Notice>}
      <Card><CardBody className="space-y-4">
        <fieldset>
          <legend className="label">Interview type</legend>
          <div className="grid gap-2 sm:grid-cols-2">
            {([["technical", "Technical concept", "Curated questions on a skill from your requirements."],
              ["project", "Project deep-dive", "Questions built from a project or role on your resume."]] as const).map(([v, l, d]) => (
              <label key={v} className={cx("card p-3 cursor-pointer", type === v ? "border-brand-600 ring-2 ring-brand-600/20" : "hover:border-slate-300")}>
                <div className="flex gap-2"><input type="radio" name="itype" checked={type === v} onChange={() => setType(v)} className="mt-1 accent-brand-700" />
                  <div><div className="text-sm font-medium">{l}</div><div className="text-xs text-ink-muted">{d}</div></div></div>
              </label>
            ))}
          </div>
        </fieldset>
        {type === "technical" && (
          <Field label="Skill" htmlFor="iskill" hint="Leave on automatic to practise your highest-priority gap.">
            <Select id="iskill" value={skill} onChange={(e) => setSkill(e.target.value)}>
              <option value="">Automatic (highest-priority gap)</option>
              {skills.map((r) => <option key={r.skill!.slug} value={r.skill!.slug}>{r.skill!.name}</option>)}
            </Select>
          </Field>
        )}
        <Notice tone="info">AI feedback covers answer content only — it cannot judge tone, confidence, accent or body language.</Notice>
        {start.isError && <ErrorState error={start.error} compact />}
        <Button loading={start.isPending} onClick={() => start.mutate()} icon={<ArrowRight className="h-4 w-4" />}>Start interview</Button>
      </CardBody></Card>
      {history.data && history.data.items.length > 0 && (
        <SectionCard title="Past sessions" icon={<MessageSquare className="h-4 w-4" />}>
          <ul className="divide-y divide-line text-sm">
            {history.data.items.map((s) => (
              <li key={s.id} className="py-2.5 flex items-center justify-between gap-2">
                <div><span className="font-medium">{s.type === "technical" ? s.skill?.name : "Project deep-dive"}</span>
                  <span className="text-ink-subtle"> · {fmtDateTime(s.created_at)} · {s.questions_asked} question(s)</span></div>
                <div className="flex items-center gap-2">
                  {s.mean_overall !== null && <span className="tabular-nums">{s.mean_overall}/100</span>}
                  <Badge tone={s.status === "completed" ? "ok" : s.status === "open" ? "info" : "neutral"}>{s.status}</Badge>
                  <button className="text-brand-800 hover:underline" onClick={() => setParams({ session: s.id })}>Open</button>
                </div>
              </li>
            ))}
          </ul>
        </SectionCard>
      )}
    </div>
  );
}

function SessionView({ sid, tid, onExit }: { sid: string; tid: string; onExit: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["interview", sid], queryFn: () => get<InterviewSession>(`/interviews/${sid}`) });
  const [text, setText] = useState("");
  const refresh = () => { qc.invalidateQueries({ queryKey: ["interview", sid] }); qc.invalidateQueries({ queryKey: ["interviews", tid] }); qc.invalidateQueries({ queryKey: ["dashboard"] }); };
  const answer = useMutation({ mutationFn: (turnId: string) => post<Turn>(`/interviews/${sid}/turns/${turnId}/answer`, { answer_text: text, input_mode: "typed" }, 120_000),
    onSuccess: () => { setText(""); refresh(); }, onError: refresh });
  const evaluate = useMutation({ mutationFn: (turnId: string) => post(`/interviews/${sid}/turns/${turnId}/evaluate`, {}, 120_000), onSettled: refresh });
  const retry = useMutation({ mutationFn: (turnId: string) => post(`/interviews/${sid}/turns/${turnId}/retry`), onSuccess: refresh });
  const next = useMutation({ mutationFn: () => post(`/interviews/${sid}/next`), onSuccess: refresh });
  const end = useMutation({ mutationFn: () => post(`/interviews/${sid}/end`), onSuccess: refresh });

  if (q.isLoading) return <PageSkeleton />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const s = q.data!;
  const turns = s.turns ?? [];
  const current = turns[turns.length - 1];
  const attemptsFor = (t: Turn) => turns.filter((x) => (x.parent_turn_id ?? x.id) === (t.parent_turn_id ?? t.id)).length;
  const wc = wordCount(text);
  const closed = s.status === "completed";

  return (
    <div className="space-y-4 max-w-3xl">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div><div className="text-xs uppercase tracking-wide text-brand-800 font-medium">{s.type === "technical" ? `Technical · ${s.skill?.name}` : "Project deep-dive"}</div>
          <h1 className="text-xl font-semibold">Question {s.questions_asked} of {s.max_questions}</h1></div>
        <div className="flex gap-2">
          {!closed && <Button size="sm" variant="secondary" loading={end.isPending} onClick={() => end.mutate()} icon={<Flag className="h-4 w-4" />}>End session</Button>}
          <Button size="sm" variant="ghost" onClick={onExit}>Back</Button>
        </div>
      </div>
      {closed && s.summary && (
        <Notice tone="ok" title="Session complete">{s.summary.evaluated_answers} answer(s) evaluated{s.summary.best_overall !== null ? `, best score ${s.summary.best_overall}/100` : ""}.
          Your results now count as interview evidence.</Notice>
      )}
      {turns.slice(0, -1).map((t) => <TurnCard key={t.id} t={t} collapsed />)}
      {current && (
        current.answer_text === null && !closed ? (
          <Card><CardBody className="space-y-3">
            <QuestionHeader t={current} />
            <Textarea rows={9} value={text} onChange={(e) => setText(e.target.value)} maxLength={12000} aria-label="Your answer"
              placeholder="Type your answer as you would say it. Aim for 120–300 words." />
            <div className="flex justify-between text-xs text-ink-subtle">
              <span>{wc < 20 ? `At least 20 words for feedback (${20 - wc} to go)` : current.guidance}</span><span className="tabular-nums">{wc} words</span>
            </div>
            <AIProgress active={answer.isPending} stages={["Saving your answer…", "Evaluating against the rubric…", "Checking quotes against your answer…"]} />
            {answer.isError && <ErrorState error={answer.error} compact />}
            <Button disabled={wc < 20} loading={answer.isPending} onClick={() => answer.mutate(current.id)} icon={<Send className="h-4 w-4" />}>Submit answer</Button>
          </CardBody></Card>
        ) : (
          <>
            <TurnCard t={current} />
            {current.evaluation_status === "failed" && (
              <Notice tone="warn" title="Feedback unavailable right now" action={<Button size="sm" variant="secondary" loading={evaluate.isPending}
                onClick={() => evaluate.mutate(current.id)} icon={<RotateCcw className="h-4 w-4" />}>Retry evaluation</Button>}>
                Your answer is saved. No score was recorded, so nothing counts against you.</Notice>
            )}
            {!closed && (
              <div className="flex flex-wrap gap-2">
                {current.answer_text !== null && attemptsFor(current) < 3 && <Button variant="secondary" loading={retry.isPending}
                  onClick={() => retry.mutate(current.id)} icon={<RotateCcw className="h-4 w-4" />}>Retry this question</Button>}
                {s.questions_asked < s.max_questions && <Button loading={next.isPending} onClick={() => next.mutate()} icon={<ArrowRight className="h-4 w-4" />}>Next question</Button>}
                {s.questions_asked >= s.max_questions && <Button loading={end.isPending} onClick={() => end.mutate()} icon={<Flag className="h-4 w-4" />}>Finish session</Button>}
              </div>
            )}
            {(retry.isError || next.isError) && <ErrorState error={retry.error ?? next.error} compact />}
          </>
        )
      )}
      {!turns.length && <EmptyState title="No questions yet" />}
    </div>
  );
}

function QuestionHeader({ t }: { t: Turn }) {
  return (
    <div>
      <div className="flex flex-wrap gap-1.5 mb-2"><Badge tone="neutral">{t.source_label}</Badge>{t.attempt_number > 1 && <Badge tone="info">Attempt {t.attempt_number}</Badge>}</div>
      <p className="text-[15px] font-medium leading-relaxed">{t.question_text}</p>
    </div>
  );
}

function TurnCard({ t, collapsed }: { t: Turn; collapsed?: boolean }) {
  const [open, setOpen] = useState(!collapsed);
  return (
    <Card><CardBody className="space-y-3">
      <div className="flex items-start justify-between gap-3">
        <QuestionHeader t={t} />
        {t.overall_score !== null && <div className="text-right shrink-0"><div className="text-2xl font-semibold tabular-nums">{t.overall_score}</div><div className="text-xs text-ink-subtle">/100</div></div>}
      </div>
      {collapsed && <button className="text-xs text-brand-800 hover:underline" onClick={() => setOpen(!open)}>{open ? "Hide answer and feedback" : "Show answer and feedback"}</button>}
      {open && (
        <>
          {t.answer_text && <div><div className="text-xs text-ink-muted mb-1">Your answer</div><p className="text-sm bg-slate-50 rounded p-3 whitespace-pre-wrap">{t.answer_text}</p></div>}
          {t.evaluation_status === "too_short" && <Notice tone="warn">{t.feedback?.message}</Notice>}
          {t.evaluation_status === "pending" && <Notice tone="info">Evaluation in progress…</Notice>}
          {t.rubric_scores && <Rubric t={t} />}
        </>
      )}
    </CardBody></Card>
  );
}

function Rubric({ t }: { t: Turn }) {
  const fb = t.feedback ?? {};
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2"><AITag label="AI feedback" /><span className="text-xs text-ink-subtle">Overall = mean of the five scores × 20, computed by RoleReady</span></div>
      {t.delta && (
        <Notice tone={t.delta.overall > 0 ? "ok" : "info"} title={`Compared with your previous attempt: ${t.delta.previous_overall} → ${t.overall_score} (${t.delta.overall >= 0 ? "+" : ""}${t.delta.overall})`}>
          {t.delta.note}
        </Notice>
      )}
      <ul className="space-y-2.5">
        {DIMS.map((d) => {
          const r = t.rubric_scores![d];
          if (!r) return null;
          const delta = t.delta?.dimensions?.[d];
          return (
            <li key={d} className="rounded-md border border-line p-3">
              <div className="flex items-center justify-between gap-2">
                <div><span className="font-medium capitalize text-sm">{d}</span><span className="text-xs text-ink-subtle ml-2">{DIM_HELP[d]}</span></div>
                <div className="flex items-center gap-2">
                  {delta !== undefined && delta !== 0 && <Badge tone={delta > 0 ? "ok" : "bad"}>{delta > 0 ? "+" : ""}{delta}</Badge>}
                  <div className="flex gap-0.5" aria-label={`${r.score} out of 5`}>{[1, 2, 3, 4, 5].map((n) => <span key={n} className={cx("h-2.5 w-5 rounded-sm", n <= r.score ? "bg-brand-600" : "bg-slate-200")} />)}</div>
                  <span className="text-sm tabular-nums w-6 text-right">{r.score}/5</span>
                </div>
              </div>
              {r.quote && <p className="text-xs mt-2 border-l-2 border-brand-200 pl-2 text-ink-muted">Your words: “{r.quote}”</p>}
              {r.comment && <p className="text-sm text-ink-muted mt-1.5">{r.comment}</p>}
              {r.note && <p className="text-xs text-warn mt-1">{r.note}</p>}
            </li>
          );
        })}
      </ul>
      <div className="grid gap-3 sm:grid-cols-3 text-sm">
        <FbList title="Strengths" items={fb.strengths} />
        <FbList title="Missing concepts" items={fb.missing_concepts} />
        <FbList title="How to improve" items={fb.improvements} />
      </div>
      {fb.example_answer ? (
        <details className="rounded-md border border-line p-3">
          <summary className="cursor-pointer text-sm font-medium inline-flex items-center gap-2"><Sparkles className="h-4 w-4 text-info" />Stronger example answer</summary>
          <p className="text-xs text-warn mt-2">{fb.example_note}</p>
          <p className="text-sm mt-2 whitespace-pre-wrap text-ink-muted">{fb.example_answer}</p>
        </details>
      ) : fb.example_note && <p className="text-xs text-ink-subtle">{fb.example_note}</p>}
      <p className="text-xs text-ink-subtle">{t.disclaimer}</p>
    </div>
  );
}

function FbList({ title, items }: { title: string; items?: string[] }) {
  if (!items?.length) return null;
  return <div><div className="text-xs font-medium text-ink-muted mb-1">{title}</div><ul className="list-disc pl-4 space-y-1">{items.map((x) => <li key={x}>{x}</li>)}</ul></div>;
}
