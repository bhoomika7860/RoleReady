import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, CheckCircle2, ClipboardCheck, RotateCcw, Trophy, XCircle } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { get, post } from "@/api/client";
import { NeedTarget, SectionCard } from "@/components/domain";
import {
  AIProgress, AITag, Badge, Button, Card, CardBody, cx, EmptyState, ErrorState, LinkButton, Notice, PageHeader,
  PageSkeleton, ProgressBar, RichText, Textarea,
} from "@/components/ui";
import { pct, wordCount } from "@/lib/format";

type PQ = { question_id: string; type: string; difficulty: string; topic: string; skill: { slug: string; name: string };
  prompt: string; options: { id: string; text: string }[] | null; source_label: string };

export default function PracticePage() {
  return <NeedTarget>{(tid) => <Practice tid={tid} />}</NeedTarget>;
}

function Practice({ tid }: { tid: string }) {
  const [params, setParams] = useSearchParams();
  const skill = params.get("skill");
  const task = params.get("task") ?? undefined;
  const summary = useQuery({ queryKey: ["practiceSummary", tid], queryFn: () => get(`/practice/summary?target_id=${tid}`) });
  if (skill) return <PracticeSet tid={tid} skill={skill} task={task} onExit={() => setParams({})} />;
  if (summary.isLoading) return <PageSkeleton />;
  if (summary.isError) return <ErrorState error={summary.error} onRetry={() => summary.refetch()} />;
  const skills: any[] = summary.data.skills;
  return (
    <div className="space-y-5">
      <PageHeader title="Practice lab" subtitle="Short sets of 5 questions with immediate feedback. Practice results count as evidence for your skills." />
      <Notice tone="info">Coding practice here is conceptual — output prediction, complexity and approach — so no code is executed.</Notice>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {skills.map((s) => (
          <Card key={s.skill.slug}><CardBody className="space-y-2">
            <div className="flex items-start justify-between gap-2">
              <div><div className="font-medium">{s.skill.name}</div><div className="text-xs text-ink-subtle capitalize">{s.importance} · {s.pool_size} questions</div></div>
              {s.D !== null ? <Badge tone={s.D >= 0.7 ? "ok" : s.D >= 0.5 ? "info" : "warn"}>{pct(s.D)} · n={s.n}</Badge> : <Badge>Not assessed</Badge>}
            </div>
            {s.since_last_assessment > 0 && <p className="text-xs text-ink-muted">{s.correct_since_last_assessment}/{s.since_last_assessment} correct since your last assessment</p>}
            <div className="flex flex-wrap gap-2">
              <Button size="sm" disabled={!s.pool_size} onClick={() => setParams({ skill: s.skill.slug })} icon={<Trophy className="h-3.5 w-3.5" />}>Practise</Button>
              {s.ready_for_checkpoint && <LinkButton size="sm" variant="subtle" to={`/app/assessment?checkpoint=${s.skill.slug}`} icon={<ClipboardCheck className="h-3.5 w-3.5" />}>Ready for a checkpoint?</LinkButton>}
            </div>
          </CardBody></Card>
        ))}
      </div>
    </div>
  );
}

function PracticeSet({ tid, skill, task, onExit }: { tid: string; skill: string; task?: string; onExit: () => void }) {
  const qc = useQueryClient();
  const set = useQuery({ queryKey: ["practiceSet", tid, skill], queryFn: () => get(`/practice/questions?target_id=${tid}&skill=${skill}&limit=5`),
    staleTime: Infinity, gcTime: 0 });
  const [i, setI] = useState(0);
  const [answers, setAnswers] = useState<Record<string, any>>({});
  const [results, setResults] = useState<Record<string, any>>({});
  const submit = useMutation({
    mutationFn: (q: PQ) => post("/practice/attempts", { question_id: q.question_id, target_id: tid, response: answers[q.question_id], task_id: task }, 90_000),
    onSuccess: (r, q) => setResults((x) => ({ ...x, [q.question_id]: r })),
  });
  const retry = useMutation({ mutationFn: (attemptId: string) => post(`/practice/attempts/${attemptId}/retry-evaluation`, {}, 90_000),
    onSuccess: (r) => setResults((x) => ({ ...x, [r.question_id]: r })) });
  const finish = useMutation({ mutationFn: () => post(`/targets/${tid}/gap-reports`),
    onSettled: () => { qc.invalidateQueries(); onExit(); } });

  if (set.isLoading) return <PageSkeleton />;
  if (set.isError) return <ErrorState error={set.error} onRetry={() => set.refetch()} />;
  const items: PQ[] = set.data.items;
  if (!items.length) return <EmptyState title="No more questions for this skill right now" action={<Button onClick={onExit}>Back</Button>}>Try a checkpoint or another skill.</EmptyState>;
  const done = i >= items.length;
  const scored = Object.values(results).filter((r: any) => r.score !== null);
  const correct = scored.filter((r: any) => r.correct).length;

  if (done) {
    return (
      <div className="max-w-2xl space-y-4">
        <PageHeader eyebrow="Practice set complete" title={`${set.data.skill.name}: ${correct}/${scored.length} correct`} />
        <Card><CardBody className="space-y-3">
          <ProgressBar value={scored.length ? (correct / scored.length) * 100 : 0} label="Set score" />
          <p className="text-sm text-ink-muted">These answers now count as practice evidence. After about 5 practice questions, a checkpoint shows whether your measured score has changed.</p>
          <div className="flex flex-wrap gap-2">
            <Button loading={finish.isPending} onClick={() => finish.mutate()}>Update my gaps and finish</Button>
            <LinkButton variant="secondary" to={`/app/assessment?checkpoint=${skill}`} icon={<ClipboardCheck className="h-4 w-4" />}>Take a checkpoint</LinkButton>
          </div>
        </CardBody></Card>
      </div>
    );
  }
  const q = items[i];
  const res = results[q.question_id];
  const ans = answers[q.question_id];
  const canSubmit = q.options ? (ans?.selected ?? []).length > 0 : wordCount(ans?.text ?? "") >= 1;
  return (
    <div className="max-w-3xl space-y-4">
      <div className="flex items-center justify-between gap-2">
        <div><div className="text-xs uppercase tracking-wide text-brand-800 font-medium">Practice · {set.data.skill.name}</div>
          <h1 className="text-xl font-semibold">Question {i + 1} of {items.length}</h1></div>
        <Button variant="ghost" size="sm" onClick={onExit}>Exit</Button>
      </div>
      <ProgressBar value={i} max={items.length} label="Set progress" />
      {set.data.hint === "REPEATS" && <Notice tone="info">You've seen these questions before — the pool for this skill is small.</Notice>}
      <Card><CardBody className="space-y-4">
        <div className="flex flex-wrap gap-1.5"><Badge>{q.topic}</Badge><Badge tone="neutral">{q.difficulty}</Badge></div>
        <RichText text={q.prompt} />
        {q.options ? (
          <fieldset className="space-y-2" disabled={!!res}>
            <legend className="sr-only">Options</legend>
            {q.options.map((o) => {
              const sel: string[] = ans?.selected ?? [];
              const checked = sel.includes(o.id);
              const multi = q.type === "mcq_multi";
              const right = res?.correct_answer?.selected?.includes(o.id);
              return (
                <label key={o.id} className={cx("flex items-start gap-3 rounded-md border px-3 py-2.5", !res && "cursor-pointer",
                  res ? (right ? "border-green-300 bg-ok-bg" : checked ? "border-red-200 bg-bad-bg" : "border-line")
                    : checked ? "border-brand-600 bg-brand-50" : "border-line hover:border-slate-300")}>
                  <input type={multi ? "checkbox" : "radio"} checked={checked} className="mt-1 accent-brand-700"
                    onChange={() => setAnswers({ ...answers, [q.question_id]: { selected: multi ? (checked ? sel.filter((s) => s !== o.id) : [...sel, o.id]) : [o.id] } })} />
                  <span className="text-sm">{o.text}</span>
                </label>
              );
            })}
          </fieldset>
        ) : (
          <div>
            <Textarea rows={6} value={ans?.text ?? ""} disabled={!!res} aria-label="Your answer"
              onChange={(e) => setAnswers({ ...answers, [q.question_id]: { text: e.target.value } })} />
            <div className="text-xs text-ink-subtle mt-1">{wordCount(ans?.text ?? "")} words · at least 10 needed for evaluation</div>
          </div>
        )}
        <p className="text-xs text-ink-subtle">{q.source_label}</p>
        {!res && (
          <>
            <Button disabled={!canSubmit} loading={submit.isPending} onClick={() => submit.mutate(q)}>Check answer</Button>
            <AIProgress active={submit.isPending && !q.options} stages={["Comparing your answer with the rubric…"]} />
            {submit.isError && <ErrorState error={submit.error} compact />}
          </>
        )}
      </CardBody></Card>
      {res && <Feedback r={res} onRetry={() => retry.mutate(res.attempt_id)} retrying={retry.isPending} />}
      {res && <Button onClick={() => setI(i + 1)} icon={<ArrowRight className="h-4 w-4" />}>{i + 1 < items.length ? "Next question" : "Finish set"}</Button>}
    </div>
  );
}

function Feedback({ r, onRetry, retrying }: { r: any; onRetry: () => void; retrying: boolean }) {
  if (r.evaluation_status === "failed") {
    return (
      <SectionCard title="Feedback unavailable right now" icon={<RotateCcw className="h-4 w-4" />}>
        <p className="text-sm text-ink-muted">Your answer is saved but the AI evaluation failed. It doesn't count against you.</p>
        <Button size="sm" variant="secondary" className="mt-2" loading={retrying} onClick={onRetry}>Retry evaluation</Button>
        {r.reference_answer && <p className="text-sm mt-3"><span className="font-medium">Reference answer: </span>{r.reference_answer}</p>}
        <p className="text-sm mt-2 text-ink-muted">{r.explanation}</p>
      </SectionCard>
    );
  }
  const good = r.correct;
  return (
    <SectionCard title={good ? "Correct" : r.score > 0 ? `Partly correct (${pct(r.score)})` : "Not quite"}
      icon={good ? <CheckCircle2 className="h-4 w-4 text-ok" /> : <XCircle className="h-4 w-4 text-bad" />}
      action={r.feedback_kind === "ai_rubric" ? <AITag label="AI-judged rubric" /> : <Badge tone="neutral">Scored by code</Badge>}>
      <div className="space-y-2 text-sm">
        {r.evaluation?.key_points && (
          <ul className="space-y-1.5">
            {r.evaluation.key_points.map((kp: any) => (
              <li key={kp.id} className="flex gap-2"><Badge tone={kp.credit === "covered" ? "ok" : kp.credit === "partial" ? "warn" : "neutral"}>{kp.credit}</Badge>
                <span>{kp.text}{kp.quote && <span className="block text-xs text-ink-muted">Your words: “{kp.quote}”</span>}</span></li>
            ))}
          </ul>
        )}
        {r.evaluation?.feedback && <p className="text-ink-muted">{r.evaluation.feedback}</p>}
        <p><span className="font-medium">Explanation: </span><span className="text-ink-muted">{r.explanation}</span></p>
        {r.reference_answer && r.feedback_kind === "ai_rubric" && <details><summary className="cursor-pointer text-brand-800">Reference answer</summary><p className="mt-1 text-ink-muted">{r.reference_answer}</p></details>}
      </div>
    </SectionCard>
  );
}
