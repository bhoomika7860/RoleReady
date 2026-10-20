import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarCheck, CheckCircle2, ChevronDown, Gauge, ListChecks, RotateCcw, XCircle } from "lucide-react";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { get, post } from "@/api/client";
import type { AssessmentSummary, GapReport } from "@/api/types";
import { GapCard, NeedTarget, SectionCard } from "@/components/domain";
import {
  AITag, Badge, Button, cx, EmptyState, ErrorState, EvidenceChip, LinkButton, Notice, PageHeader, PageSkeleton,
  ProgressBar, RichText, ScoreTile,
} from "@/components/ui";
import { fmtDate, pct } from "@/lib/format";

const DIMS = ["RA", "TK", "PS", "PE", "IC"];

export default function ResultsPage() {
  return <NeedTarget>{(tid) => <Results tid={tid} />}</NeedTarget>;
}

function Results({ tid }: { tid: string }) {
  const [params] = useSearchParams();
  const list = useQuery({ queryKey: ["assessments", tid], queryFn: () => get<AssessmentSummary[]>(`/targets/${tid}/assessments`) });
  const latestScored = list.data?.find((a) => ["scored", "scored_partial", "abandoned"].includes(a.status));
  const aid = params.get("assessment") ?? latestScored?.id;
  const gaps = useQuery({ queryKey: ["gaps", tid], queryFn: () => get<GapReport>(`/targets/${tid}/gap-reports/latest`) });
  const nav = useNavigate();
  const qc = useQueryClient();
  const plan = useMutation({ mutationFn: () => post(`/targets/${tid}/plans`), onSuccess: () => { qc.invalidateQueries(); nav("/app/plan"); } });

  if (list.isLoading || gaps.isLoading) return <PageSkeleton />;
  return (
    <div className="space-y-5">
      <PageHeader title="Results & skill gaps" subtitle="What your answers showed, combined with your resume evidence, ranked by a transparent formula."
        action={<Button loading={plan.isPending} onClick={() => plan.mutate()} icon={<CalendarCheck className="h-4 w-4" />}>Build my plan</Button>} />
      {plan.isError && <ErrorState error={plan.error} compact />}
      {aid ? <AssessmentResult id={aid} /> : (
        <EmptyState title="No assessment results yet" action={<LinkButton to="/app/assessment">Take the diagnostic</LinkButton>}>
          Gaps below are based on your resume and requirements only until you've answered some questions.
        </EmptyState>
      )}
      {gaps.isError ? <ErrorState error={gaps.error} onRetry={() => gaps.refetch()} /> : gaps.data && <GapSection r={gaps.data} />}
    </div>
  );
}

function AssessmentResult({ id }: { id: string }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["result", id], queryFn: () => get(`/assessments/${id}/result`),
    refetchInterval: (query) => (query.state.data && (query.state.data as any).items ? false : 2000) });
  const retry = useMutation({ mutationFn: (position: number) => post(`/assessments/${id}/items/${position}/retry-evaluation`, {}, 90_000),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["result", id] }); qc.invalidateQueries({ queryKey: ["gaps"] }); qc.invalidateQueries({ queryKey: ["dashboard"] }); } });
  const [open, setOpen] = useState<number | null>(null);
  if (q.isLoading) return <PageSkeleton />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const r: any = q.data;
  if (!r.items) return <Notice tone="info">Scoring in progress…</Notice>;
  return (
    <SectionCard title={r.kind === "diagnostic" ? "Diagnostic results" : `${r.skill?.name} checkpoint results`} icon={<ListChecks className="h-4 w-4" />}
      subtitle={`${fmtDate(r.scored_at)} · ${r.items_scored} of ${r.items_total} questions scored${r.unanswered ? ` · ${r.unanswered} unanswered` : ""}`}
      action={r.score !== null && <div className="text-right"><div className="text-2xl font-semibold tabular-nums">{r.score}</div><div className="text-xs text-ink-subtle">/100 overall</div></div>}>
      <div className="space-y-4">
        {r.status === "scored_partial" && <Notice tone="warn" title="Some answers couldn't be evaluated yet">They are excluded from your score (not counted as zero). Retry them below.</Notice>}
        {r.includes_repeats && <Notice tone="info">This attempt includes questions you've seen before.</Notice>}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {r.skills.map((s: any) => (
            <div key={s.slug} className="rounded-md border border-line p-3">
              <div className="flex justify-between text-sm"><span className="font-medium">{s.name}</span><span className="tabular-nums">{s.score ?? "—"}</span></div>
              <ProgressBar value={s.score ?? 0} className="mt-2" label={s.name} />
              <div className="text-xs text-ink-subtle mt-1.5">Based on {s.items_scored} of {s.items_total} question{s.items_total === 1 ? "" : "s"}</div>
            </div>
          ))}
        </div>
        <p className="text-xs text-ink-subtle">{r.note}</p>
        <ul className="divide-y divide-line border border-line rounded-md bg-white">
          {r.items.map((it: any) => {
            const correct = it.score !== null && it.score >= 0.999;
            const isOpen = open === it.position;
            return (
              <li key={it.position}>
                <button className="w-full flex items-center gap-3 px-3 py-2.5 text-left hover:bg-slate-50" aria-expanded={isOpen}
                  onClick={() => setOpen(isOpen ? null : it.position)}>
                  {it.evaluation_status === "failed" ? <RotateCcw className="h-4 w-4 text-warn shrink-0" aria-label="Awaiting evaluation" />
                    : it.unanswered ? <XCircle className="h-4 w-4 text-ink-subtle shrink-0" aria-label="Unanswered" />
                      : correct ? <CheckCircle2 className="h-4 w-4 text-ok shrink-0" aria-label="Correct" />
                        : it.score > 0 ? <CheckCircle2 className="h-4 w-4 text-warn shrink-0" aria-label="Partly correct" />
                          : <XCircle className="h-4 w-4 text-bad shrink-0" aria-label="Incorrect" />}
                  <span className="text-sm flex-1 min-w-0 truncate">{it.position}. {it.topic} · {it.skill.name}</span>
                  <span className="text-xs tabular-nums text-ink-muted shrink-0">{it.evaluation_status === "failed" ? "pending" : it.unanswered ? "unanswered" : pct(it.score)}</span>
                  <ChevronDown className={cx("h-4 w-4 text-ink-subtle transition-transform", isOpen && "rotate-180")} />
                </button>
                {isOpen && (
                  <div className="px-3 pb-4 space-y-3">
                    <RichText text={it.prompt} />
                    {it.options ? (
                      <ul className="space-y-1 text-sm">
                        {it.options.map((o: any) => {
                          const right = it.correct_answer?.selected?.includes(o.id);
                          const picked = it.response?.selected?.includes(o.id);
                          return <li key={o.id} className={cx("rounded px-2 py-1.5 border", right ? "border-green-200 bg-ok-bg" : picked ? "border-red-200 bg-bad-bg" : "border-transparent")}>
                            {o.text}{right && <span className="text-ok text-xs ml-2">correct answer</span>}{picked && !right && <span className="text-bad text-xs ml-2">your answer</span>}</li>;
                        })}
                      </ul>
                    ) : (
                      <div className="space-y-2">
                        <div className="text-xs text-ink-muted">Your answer</div>
                        <p className="text-sm bg-slate-50 rounded p-2.5 whitespace-pre-wrap">{it.response?.text || "(no answer)"}</p>
                        {it.evaluation?.key_points && (
                          <div>
                            <div className="flex items-center gap-2 mb-1"><span className="text-xs text-ink-muted">Rubric key points</span>
                              {it.evaluation.method === "ai_rubric" && <AITag label="AI-judged, code-scored" />}</div>
                            <ul className="space-y-1.5 text-sm">
                              {it.evaluation.key_points.map((kp: any) => (
                                <li key={kp.id} className="flex gap-2">
                                  <Badge tone={kp.credit === "covered" ? "ok" : kp.credit === "partial" ? "warn" : "neutral"}>{kp.credit}</Badge>
                                  <span>{kp.text}{kp.quote && <span className="block text-xs text-ink-muted mt-0.5">Your words: “{kp.quote}”</span>}</span>
                                </li>
                              ))}
                            </ul>
                            {it.evaluation.feedback && <p className="text-sm text-ink-muted mt-2">{it.evaluation.feedback}</p>}
                          </div>
                        )}
                        {it.reference_answer && <details className="text-sm"><summary className="cursor-pointer text-brand-800">Reference answer</summary><p className="mt-1 text-ink-muted">{it.reference_answer}</p></details>}
                      </div>
                    )}
                    <p className="text-sm text-ink-muted"><span className="font-medium text-ink">Explanation: </span>{it.explanation}</p>
                    {it.evaluation_status === "failed" && (
                      <Button size="sm" variant="secondary" loading={retry.isPending && retry.variables === it.position}
                        onClick={() => retry.mutate(it.position)} icon={<RotateCcw className="h-4 w-4" />}>Retry evaluation</Button>
                    )}
                    {retry.isError && retry.variables === it.position && <ErrorState error={retry.error} compact />}
                    <p className="text-xs text-ink-subtle">{it.source_label}</p>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </div>
    </SectionCard>
  );
}

function GapSection({ r }: { r: GapReport }) {
  const [showAll, setShowAll] = useState(false);
  const gaps = showAll ? r.gaps : r.gaps.slice(0, 5);
  return (
    <>
      <SectionCard title="Readiness by dimension" icon={<Gauge className="h-4 w-4" />} subtitle={r.disclaimer}>
        <div className="grid gap-2.5 grid-cols-2 md:grid-cols-5">
          {DIMS.map((k) => r.dimension_scores[k] && <ScoreTile key={k} name={r.dimension_scores[k].name} score={r.dimension_scores[k].score}
            confidence={r.dimension_scores[k].confidence} basis={r.dimension_scores[k].basis} />)}
        </div>
        {r.readiness_index !== null && <p className="text-sm mt-3">Overall estimate: <span className="font-semibold">{r.readiness_index}</span> — a heuristic summary, not a hiring prediction.</p>}
      </SectionCard>

      <SectionCard title="Ranked skill gaps" icon={<ListChecks className="h-4 w-4" />} subtitle={`Priority ${r.formula} — I importance, S severity, C confidence, B prerequisite bonus.`}>
        {r.resolved.length > 0 && <Notice tone="ok" className="mb-3" title="Resolved since last time">{r.resolved.map((x) => x.text).join(" ")}</Notice>}
        {r.gaps.length ? (
          <div className="space-y-2.5">
            {gaps.map((g) => <GapCard key={g.id} gap={g} />)}
            {r.gaps.length > 5 && <Button variant="ghost" size="sm" onClick={() => setShowAll(!showAll)}>{showAll ? "Show top 5" : `Show all ${r.gaps.length}`}</Button>}
          </div>
        ) : <p className="text-sm text-ink-muted">No open gaps right now.</p>}
      </SectionCard>

      <SectionCard title="Evidence per skill" icon={<CheckCircle2 className="h-4 w-4" />}
        subtitle="Resume evidence and demonstrated ability are separate signals — absence from your resume is not proof you lack a skill.">
        <div className="overflow-x-auto -mx-1">
          <table className="w-full text-sm min-w-[560px]">
            <thead><tr className="text-left text-xs text-ink-muted border-b border-line">
              <th className="py-2 px-1 font-medium">Skill</th><th className="py-2 px-1 font-medium">Importance</th>
              <th className="py-2 px-1 font-medium">Resume</th><th className="py-2 px-1 font-medium">Demonstrated</th>
              <th className="py-2 px-1 font-medium text-right">Score (n)</th></tr></thead>
            <tbody>
              {r.skill_states.map((s) => (
                <tr key={s.skill_id} className="border-b border-line last:border-0">
                  <td className="py-2 px-1 font-medium">{s.name}</td>
                  <td className="py-2 px-1 capitalize">{s.importance}</td>
                  <td className="py-2 px-1"><EvidenceChip state={s.resume_state} /></td>
                  <td className="py-2 px-1"><EvidenceChip state={s.demonstrated_state} />
                    {s.demonstrated_source && <span className="text-xs text-ink-subtle ml-1">via {s.demonstrated_source}</span>}</td>
                  <td className="py-2 px-1 text-right tabular-nums">{s.D === null ? "—" : `${Math.round(s.D * 100)}%`} <span className="text-ink-subtle">({s.n})</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {r.unassessable_skills.length > 0 && <p className="text-xs text-ink-subtle mt-2">Not enough questions yet to assess: {r.unassessable_skills.join(", ")}.</p>}
      </SectionCard>
    </>
  );
}
