import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity, AlertTriangle, CalendarCheck, CheckCircle2, Circle, ClipboardCheck, ExternalLink, FileText, Gauge,
  MessageSquare, Sparkles, Target as TargetIcon, TrendingUp,
} from "lucide-react";
import { Link } from "react-router-dom";
import { get, patch } from "@/api/client";
import type { Gap, NextActions, SkillState, Target, Task } from "@/api/types";
import { GapCard, NextActionCard, SectionCard } from "@/components/domain";
import {
  Badge, cx, EmptyState, ErrorState, LinkButton, Notice, PageHeader, PageSkeleton, ProgressBar, ScoreTile,
  Stat,
} from "@/components/ui";
import { useSession } from "@/hooks/session";
import { fmtDate, fmtDateTime } from "@/lib/format";

type Dash = {
  target: Target | null; onboarding?: boolean; next_action: NextActions;
  readiness: { dimensions: Record<string, { score: number | null; confidence: string; basis: string; name: string }>;
    index: { score: number; band: string } | null; note: string };
  top_gaps: Gap[]; gap_count: number; strengths: SkillState[]; not_assessed: SkillState[];
  coverage: any; plan: any; latest_assessment: any; interview: any; skill_progress: any; recent_activity: any;
  computed_at: string;
};

const DIM_ORDER = ["RA", "TK", "PS", "PE", "IC"];

export default function Dashboard() {
  const { data: me } = useSession();
  const tid = me?.active_target_id;
  const q = useQuery({ queryKey: ["dashboard", tid ?? "none"], queryFn: () => get<Dash>(tid ? `/targets/${tid}/dashboard` : "/dashboard"),
    staleTime: 0 });
  const name = me?.user.preferred_name || me?.user.identifier;

  if (q.isLoading) return <PageSkeleton />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const d = q.data!;

  if (!d.target) {
    return (
      <div className="max-w-3xl space-y-5">
        <PageHeader title={`Welcome, ${name}`} subtitle="Let's find out what stands between you and a specific job." />
        <NextActionCard data={d.next_action} />
      </div>
    );
  }
  const t = d.target;
  return (
    <div className="space-y-5">
      <PageHeader title={`Welcome back, ${name}`}
        subtitle={<span>Preparing for <span className="font-medium text-ink">{t.job_title}</span>{t.company_name ? ` · ${t.company_name}` : ""}</span>}
        action={<LinkButton to="/app/target" variant="secondary" size="sm" icon={<TargetIcon className="h-4 w-4" />}>Edit target</LinkButton>} />

      {d.plan?.banner && <Notice tone="info">{d.plan.banner}</Notice>}
      {t.deadline_passed && <Notice tone="warn" title="Your deadline has passed"
        action={<LinkButton to="/app/target" size="sm" variant="secondary">Set a new deadline</LinkButton>}>The plan has stopped scheduling new days.</Notice>}

      <NextActionCard data={d.next_action.primary ? d.next_action : undefined} />

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-5">
          <TodayCard plan={d.plan} />
          <SectionCard title="Priority skill gaps" icon={<Gauge className="h-4 w-4" />}
            subtitle={d.gap_count ? `${d.gap_count} open gap${d.gap_count === 1 ? "" : "s"}, ranked by a published formula` : undefined}
            action={d.gap_count > 0 && <Link to="/app/results" className="text-sm text-brand-800 hover:underline">All gaps</Link>}>
            {d.top_gaps.length ? (
              <div className="space-y-2.5">{d.top_gaps.map((g) => <GapCard key={g.id} gap={g} showInputs={false} />)}</div>
            ) : d.latest_assessment?.status === "empty" ? (
              <EmptyState title="Take the diagnostic to find your gaps" action={<LinkButton to="/app/assessment">Start diagnostic</LinkButton>}>
                15 questions, about 20 minutes. You can pause and resume.
              </EmptyState>
            ) : <p className="text-sm text-ink-muted">No open gaps right now. Keep your evidence fresh with a checkpoint.</p>}
          </SectionCard>

          <SectionCard title="Readiness by dimension" icon={<Activity className="h-4 w-4" />}
            subtitle={d.readiness.note} action={<Link to="/how-scores-work" className="text-sm text-brand-800 hover:underline">How scores work</Link>}>
            <div className="grid gap-2.5 grid-cols-2 md:grid-cols-5">
              {DIM_ORDER.map((k) => {
                const dim = d.readiness.dimensions[k];
                return dim ? <ScoreTile key={k} name={dim.name} score={dim.score} confidence={dim.confidence} /> : null;
              })}
            </div>
            <div className="mt-3 text-sm">
              {d.readiness.index ? (
                <span>Overall readiness estimate: <span className="font-semibold">{d.readiness.index.score}</span> ({d.readiness.index.band}) —
                  a heuristic summary, not a hiring prediction.</span>
              ) : <span className="text-ink-muted">An overall estimate appears once at least three dimensions, including technical knowledge, have medium confidence.</span>}
            </div>
          </SectionCard>

          <ProgressCard data={d.skill_progress} />
        </div>

        <div className="space-y-5">
          <SectionCard title="Target" icon={<TargetIcon className="h-4 w-4" />}>
            <div className="grid grid-cols-2 gap-3">
              <Stat label="Role" value={<span className="text-sm">{t.role.name}</span>} />
              <Stat label="Deadline" value={t.deadline_passed ? "Passed" : `${t.days_to_deadline} days`} sub={fmtDate(t.deadline_date)} />
              <Stat label="Daily study time" value={`${t.daily_minutes} min`} />
              <Stat label="Requirements" value={t.requirements_confirmed_at ? "Confirmed" : "Unconfirmed"} />
            </div>
            {t.company_notice && <p className="text-xs text-ink-subtle mt-3">{t.company_notice}</p>}
          </SectionCard>
          <CoverageCard data={d.coverage} />
          <AssessmentCard data={d.latest_assessment} />
          <InterviewCard data={d.interview} />
          <SkillsCard strengths={d.strengths} notAssessed={d.not_assessed} />
          <ActivityCard data={d.recent_activity} />
        </div>
      </div>
      <p className="text-xs text-ink-subtle">Computed {fmtDateTime(d.computed_at)} from your stored evidence.</p>
    </div>
  );
}

function TaskRow({ task }: { task: Task }) {
  const qc = useQueryClient();
  const mark = useMutation({ mutationFn: (status: string) => patch(`/plan-tasks/${task.id}`, { status }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["dashboard"] }); qc.invalidateQueries({ queryKey: ["plan"] }); } });
  const done = task.status === "done";
  return (
    <li className="flex items-start gap-3 py-2.5">
      {task.auto_completes ? (
        done ? <CheckCircle2 className="h-5 w-5 text-ok shrink-0 mt-0.5" aria-label="Done" /> : <Circle className="h-5 w-5 text-slate-300 shrink-0 mt-0.5" aria-hidden />
      ) : (
        <input type="checkbox" checked={done} disabled={mark.isPending} aria-label={`Mark ${task.title} done`}
          onChange={() => mark.mutate(done ? "pending" : "done")} className="h-5 w-5 mt-0.5 accent-brand-700 shrink-0" />
      )}
      <div className="flex-1 min-w-0">
        <div className={cx("text-sm font-medium", done && "line-through text-ink-subtle")}>{task.title}</div>
        <div className="text-xs text-ink-subtle mt-0.5">{task.minutes} min · {task.auto_completes ? "Completes automatically" : "Tick when done"}</div>
      </div>
      {!done && (task.external ? (
        <a href={task.link} target="_blank" rel="noopener noreferrer" className="text-sm text-brand-800 hover:underline inline-flex items-center gap-1 shrink-0">Open <ExternalLink className="h-3.5 w-3.5" /></a>
      ) : <Link to={task.link} className="text-sm text-brand-800 hover:underline shrink-0">Start</Link>)}
    </li>
  );
}

function TodayCard({ plan }: { plan: any }) {
  if (!plan || plan.status === "error") return null;
  if (plan.status === "empty") {
    return (
      <SectionCard title="Today's plan" icon={<CalendarCheck className="h-4 w-4" />}>
        <EmptyState title="Build your study plan" action={<LinkButton to="/app/plan">Build my plan</LinkButton>}>
          A day-by-day plan sized to your deadline and daily time, built from your gaps.
        </EmptyState>
      </SectionCard>
    );
  }
  const p = plan.progress;
  return (
    <SectionCard title="Today's plan" icon={<CalendarCheck className="h-4 w-4" />}
      subtitle={p.pct === null ? "No tasks due yet" : `${p.pct}% of tasks due so far are done · ${p.missed} missed`}
      action={<Link to="/app/plan" className="text-sm text-brand-800 hover:underline">Full plan</Link>}>
      {p.pct !== null && <ProgressBar value={p.pct} label="Plan progress" className="mb-2" />}
      {plan.today.length ? <ul className="divide-y divide-line">{plan.today.map((t: Task) => <TaskRow key={t.id} task={t} />)}</ul>
        : <p className="text-sm text-ink-muted">Nothing scheduled today. {plan.unscheduled ? `${plan.unscheduled} item(s) didn't fit before your deadline.` : ""}</p>}
    </SectionCard>
  );
}

function CoverageCard({ data }: { data: any }) {
  return (
    <SectionCard title="Resume coverage" icon={<FileText className="h-4 w-4" />}
      action={<Link to="/app/resume?tab=match" className="text-sm text-brand-800 hover:underline">Details</Link>}>
      {data?.status === "ok" ? (
        <div className="space-y-2">
          <div className="flex items-baseline gap-1"><span className="text-2xl font-semibold tabular-nums">{data.score}</span><span className="text-xs text-ink-subtle">/100 requirement coverage</span></div>
          <ProgressBar value={data.score} label="Coverage" />
          <div className="flex flex-wrap gap-1.5 text-xs">
            <Badge tone="ok">{data.counts.evidenced} evidenced</Badge><Badge tone="warn">{data.counts.weak} weak</Badge>
            <Badge tone="neutral">{data.counts.not_shown} not shown</Badge>
          </div>
          {!data.reviewed && <p className="text-xs text-warn flex gap-1"><AlertTriangle className="h-3.5 w-3.5" />Review your parsed resume so this reflects what you confirmed.</p>}
          {data.stale && <p className="text-xs text-warn">Your resume changed since this analysis.</p>}
          <p className="text-xs text-ink-subtle">Not an ATS score — it shows what your resume visibly evidences.</p>
        </div>
      ) : data?.status === "not_analysed" ? (
        <LinkButton to="/app/resume?tab=match" size="sm" variant="secondary">Run analysis</LinkButton>
      ) : (
        <EmptyState title="No resume yet" action={<LinkButton to="/app/resume" size="sm">Add your resume</LinkButton>}>
          Upload, paste or build one to see which requirements it shows.
        </EmptyState>
      )}
    </SectionCard>
  );
}

function AssessmentCard({ data }: { data: any }) {
  return (
    <SectionCard title="Recent assessment" icon={<ClipboardCheck className="h-4 w-4" />}>
      {data?.status === "ok" ? (
        <div className="space-y-1.5">
          <div className="text-sm">{data.kind === "diagnostic" ? "Diagnostic" : `${data.skill} checkpoint`} · {fmtDate(data.date)}</div>
          <div className="flex items-baseline gap-1"><span className="text-2xl font-semibold tabular-nums">{data.score ?? "—"}</span><span className="text-xs text-ink-subtle">/100 on {data.items_scored} scored questions</span></div>
          {data.partial && <p className="text-xs text-warn">Some answers are awaiting evaluation (they don't count as zero).</p>}
          <Link to={`/app/results?assessment=${data.id}`} className="text-sm text-brand-800 hover:underline">View results</Link>
        </div>
      ) : <LinkButton to="/app/assessment" size="sm" variant="secondary">Take the diagnostic</LinkButton>}
    </SectionCard>
  );
}

function InterviewCard({ data }: { data: any }) {
  return (
    <SectionCard title="Mock interviews" icon={<MessageSquare className="h-4 w-4" />}>
      {data?.status === "ok" ? (
        <div className="space-y-1.5 text-sm">
          <div className="flex items-baseline gap-1"><span className="text-2xl font-semibold tabular-nums">{data.mean_overall}</span><span className="text-xs text-ink-subtle">/100 mean of last {data.answers} answers</span></div>
          <div className="text-ink-muted">Weakest dimension: <span className="font-medium text-ink capitalize">{data.weakest_dimension}</span></div>
          <Link to="/app/interview" className="text-brand-800 hover:underline">Practise again</Link>
        </div>
      ) : <LinkButton to="/app/interview" size="sm" variant="secondary">Try a mock interview</LinkButton>}
    </SectionCard>
  );
}

function SkillsCard({ strengths, notAssessed }: { strengths: SkillState[]; notAssessed: SkillState[] }) {
  return (
    <SectionCard title="Skills evidence" icon={<Sparkles className="h-4 w-4" />}>
      <div className="space-y-3 text-sm">
        <div>
          <div className="text-xs text-ink-muted mb-1">Demonstrated strengths</div>
          {strengths.length ? <div className="flex flex-wrap gap-1">{strengths.map((s) => <Badge key={s.slug} tone="ok">{s.name}</Badge>)}</div>
            : <p className="text-ink-subtle text-xs">None demonstrated yet — strengths appear after enough correct answers.</p>}
        </div>
        <div>
          <div className="text-xs text-ink-muted mb-1">Not yet assessed</div>
          {notAssessed.length ? <div className="flex flex-wrap gap-1">{notAssessed.slice(0, 10).map((s) => <Link key={s.slug} to={`/app/assessment?checkpoint=${s.slug}`}><Badge>{s.name}</Badge></Link>)}</div>
            : <p className="text-ink-subtle text-xs">Every required skill has some evidence.</p>}
        </div>
      </div>
    </SectionCard>
  );
}

function ProgressCard({ data }: { data: any }) {
  if (!Array.isArray(data) || !data.length) {
    return (
      <SectionCard title="Measured progress" icon={<TrendingUp className="h-4 w-4" />}>
        <p className="text-sm text-ink-muted">Change is shown only between comparable checkpoints on the same skill. Take a checkpoint after practising to measure change.</p>
      </SectionCard>
    );
  }
  return (
    <SectionCard title="Measured progress" icon={<TrendingUp className="h-4 w-4" />}
      action={<Link to="/app/progress" className="text-sm text-brand-800 hover:underline">Progress</Link>}>
      <ul className="divide-y divide-line text-sm">
        {data.map((s: any) => {
          const cps = s.series.filter((p: any) => p.kind === "checkpoint");
          const last = cps[cps.length - 1];
          return (
            <li key={s.skill.slug} className="py-2 flex items-center justify-between gap-2">
              <span className="font-medium">{s.skill.name}</span>
              {last?.comparable_with_previous ? (
                <span className="tabular-nums">{cps[cps.length - 2].score} → {last.score}{" "}
                  <Badge tone={last.change === "Improved" ? "ok" : last.change === "Declined" ? "bad" : "neutral"}>{last.change}</Badge></span>
              ) : <span className="text-xs text-ink-subtle">{last ? `${last.score} · ${last.reason ?? "first checkpoint"}` : "—"}</span>}
            </li>
          );
        })}
      </ul>
    </SectionCard>
  );
}

function ActivityCard({ data }: { data: any }) {
  if (!Array.isArray(data) || !data.length) return null;
  return (
    <SectionCard title="Recent activity" icon={<Activity className="h-4 w-4" />}>
      <ul className="space-y-1.5 text-sm">
        {data.slice(0, 6).map((e: any, i: number) => (
          <li key={i} className="flex justify-between gap-2"><span className="truncate">{e.text}</span><span className="text-xs text-ink-subtle shrink-0">{fmtDateTime(e.date)}</span></li>
        ))}
      </ul>
    </SectionCard>
  );
}

