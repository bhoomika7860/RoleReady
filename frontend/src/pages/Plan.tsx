import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BookOpen, CalendarCheck, CheckCircle2, ClipboardCheck, ExternalLink, FileText, MessageSquare, RefreshCw, SkipForward,
  Trophy, Undo2,
} from "lucide-react";
import { Link } from "react-router-dom";
import { ApiError, get, patch, post } from "@/api/client";
import type { Plan, Task } from "@/api/types";
import { NeedTarget, SectionCard } from "@/components/domain";
import { Badge, Button, cx, EmptyState, ErrorState, Notice, PageHeader, PageSkeleton, ProgressBar, Stat } from "@/components/ui";
import { fmtDate, fmtDay } from "@/lib/format";

const ICON: Record<string, any> = { learn: BookOpen, practice: Trophy, reassess: ClipboardCheck, assess: ClipboardCheck,
  interview: MessageSquare, resume: FileText };
const TYPE_LABEL: Record<string, string> = { learn: "Learn", practice: "Practise", reassess: "Re-check", assess: "Assess",
  interview: "Interview", resume: "Resume" };

export default function PlanPage() {
  return <NeedTarget>{(tid) => <PlanView tid={tid} />}</NeedTarget>;
}

function PlanView({ tid }: { tid: string }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["plan", tid], retry: false, queryFn: () => get<Plan>(`/targets/${tid}/plans/active`) });
  const build = useMutation({ mutationFn: () => post<Plan>(`/targets/${tid}/plans`),
    onSuccess: (p) => { qc.setQueryData(["plan", tid], p); qc.invalidateQueries({ queryKey: ["dashboard"] }); } });
  const replan = useMutation({ mutationFn: () => post<Plan>(`/plans/${q.data!.plan_id}/replan`),
    onSuccess: (p) => { qc.setQueryData(["plan", tid], p); qc.invalidateQueries({ queryKey: ["dashboard"] }); } });

  if (q.isLoading) return <PageSkeleton />;
  const noPlan = q.error instanceof ApiError && q.error.code === "NO_PLAN";
  if (q.isError && !noPlan) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  if (noPlan || !q.data) {
    return (
      <div className="max-w-2xl space-y-5">
        <PageHeader title="Study plan" subtitle="A day-by-day plan built from your ranked gaps, sized to your deadline and daily time." />
        <EmptyState title="You don't have a plan yet" icon={<CalendarCheck className="h-5 w-5" />}
          action={<Button loading={build.isPending} onClick={() => build.mutate()}>Build my plan</Button>}>
          The planner is deterministic: the same gaps, dates and minutes always give the same plan. If you haven't taken the
          diagnostic, the plan starts with it.
        </EmptyState>
        {build.isError && <ErrorState error={build.error} compact />}
      </div>
    );
  }
  const p = q.data;
  const today = p.days.find((d) => d.date === p.today);
  const upcoming = p.days.filter((d) => d.date !== p.today);
  return (
    <div className="space-y-5">
      <PageHeader title="Study plan" subtitle={`Revision ${p.revision} · ${fmtDate(p.start_date)} to ${fmtDate(p.end_date)}`}
        action={<Button variant="secondary" loading={replan.isPending} onClick={() => replan.mutate()} icon={<RefreshCw className="h-4 w-4" />}>Replan</Button>} />
      {p.banner && <Notice tone="info">{p.banner}</Notice>}
      {p.change_summary && !p.banner && <Notice tone="info" title="Latest update">{p.change_summary}</Notice>}
      {replan.isError && <ErrorState error={replan.error} compact />}
      <div className="card p-4 grid grid-cols-2 sm:grid-cols-4 gap-4">
        <Stat label="Daily budget" value={`${p.daily_minutes} min`} />
        <Stat label="Tasks done" value={`${p.progress.done} / ${p.progress.total}`} />
        <Stat label="Missed" value={p.progress.missed} sub="rescheduled automatically" />
        <div><div className="text-xs text-ink-muted">Due so far, done</div>
          <div className="text-lg font-semibold">{p.progress.pct === null ? "—" : `${p.progress.pct}%`}</div>
          {p.progress.pct !== null && <ProgressBar value={p.progress.pct} className="mt-1" label="Plan progress" />}</div>
      </div>

      <SectionCard title={`Today · ${fmtDay(p.today)}`} icon={<CalendarCheck className="h-4 w-4" />}
        subtitle={today ? `${today.total_minutes} of ${p.daily_minutes} minutes planned` : undefined}>
        {today?.tasks.length ? <ul className="space-y-2">{today.tasks.map((t) => <TaskItem key={t.id} t={t} tid={tid} />)}</ul>
          : <p className="text-sm text-ink-muted">Nothing scheduled today.</p>}
      </SectionCard>

      {upcoming.length > 0 && (
        <SectionCard title="Coming up" icon={<CalendarCheck className="h-4 w-4" />}>
          <div className="space-y-4">
            {upcoming.slice(0, 14).map((d) => (
              <div key={d.date}>
                <div className="flex justify-between text-xs text-ink-muted mb-1.5"><span className="font-medium text-ink">{fmtDay(d.date)}</span><span>{d.total_minutes} min</span></div>
                <ul className="space-y-2">{d.tasks.map((t) => <TaskItem key={t.id} t={t} tid={tid} compact />)}</ul>
              </div>
            ))}
            {upcoming.length > 14 && <p className="text-xs text-ink-subtle">+ {upcoming.length - 14} more days</p>}
          </div>
        </SectionCard>
      )}

      {p.unscheduled.length > 0 && (
        <SectionCard title="Not scheduled — not enough time before your deadline" icon={<SkipForward className="h-4 w-4" />}
          subtitle="Lower-priority work is listed here instead of overloading your days. Extend the deadline or add daily time to include it.">
          <ul className="text-sm space-y-1">{p.unscheduled.map((u, i) => <li key={i} className="flex justify-between gap-2"><span>{u.task ?? u.skill}</span><span className="text-xs text-ink-subtle">{u.reason}</span></li>)}</ul>
        </SectionCard>
      )}
      {p.history.length > 0 && (
        <details className="card p-4"><summary className="cursor-pointer text-sm font-medium">Past tasks ({p.history.length})</summary>
          <ul className="mt-3 space-y-1 text-sm">{p.history.map((t) => (
            <li key={t.id} className="flex justify-between gap-2"><span className={cx(t.status === "done" && "line-through text-ink-subtle")}>{t.title}</span>
              <Badge tone={t.status === "done" ? "ok" : t.status === "missed" ? "warn" : "neutral"}>{t.status}</Badge></li>))}</ul>
        </details>
      )}
    </div>
  );
}

function TaskItem({ t, tid, compact }: { t: Task; tid: string; compact?: boolean }) {
  const qc = useQueryClient();
  const set = useMutation({ mutationFn: (status: string) => patch(`/plan-tasks/${t.id}`, { status }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["plan", tid] }); qc.invalidateQueries({ queryKey: ["dashboard"] }); } });
  const Icon = ICON[t.type] ?? CalendarCheck;
  const done = t.status === "done";
  const skipped = t.status === "skipped";
  return (
    <li className={cx("rounded-md border border-line bg-white p-3", (done || skipped) && "bg-slate-50")}>
      <div className="flex items-start gap-3">
        <Icon className={cx("h-4 w-4 mt-0.5 shrink-0", done ? "text-ok" : "text-brand-700")} aria-hidden />
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className={cx("text-sm font-medium", (done || skipped) && "line-through text-ink-subtle")}>{t.title}</span>
            <Badge tone="neutral">{TYPE_LABEL[t.type]}</Badge><span className="text-xs text-ink-subtle">{t.minutes} min</span>
            {done && <Badge tone="ok" icon={<CheckCircle2 className="h-3 w-3" />}>Done</Badge>}
            {skipped && <Badge>Skipped</Badge>}
          </div>
          {!compact && <p className="text-xs text-ink-muted mt-1">{t.rationale}</p>}
          {t.resource && <p className="text-xs text-ink-subtle mt-1">{t.resource.provider} · {t.resource.format} · {t.resource.is_free ? "free" : "paid"} · link checked {fmtDate(t.resource.last_verified_at)}</p>}
        </div>
      </div>
      {!done && !skipped && (
        <div className="flex flex-wrap gap-2 mt-2.5 pl-7">
          {t.external ? <a href={t.link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md bg-brand-700 text-white text-sm">Open resource <ExternalLink className="h-3.5 w-3.5" /></a>
            : <Link to={t.link} className="inline-flex items-center h-8 px-3 rounded-md bg-brand-700 text-white text-sm">Start</Link>}
          {!t.auto_completes && <Button size="sm" variant="secondary" loading={set.isPending} onClick={() => set.mutate("done")} icon={<CheckCircle2 className="h-3.5 w-3.5" />}>Mark done</Button>}
          <Button size="sm" variant="ghost" onClick={() => set.mutate("skipped")} icon={<SkipForward className="h-3.5 w-3.5" />}>Skip</Button>
          {t.auto_completes && <span className="text-xs text-ink-subtle self-center">Ticks itself when you finish the activity</span>}
        </div>
      )}
      {(done || skipped) && !t.auto_completes && (
        <button className="mt-2 ml-7 text-xs text-brand-800 hover:underline inline-flex items-center gap-1" onClick={() => set.mutate("pending")}><Undo2 className="h-3 w-3" />Undo</button>
      )}
      {skipped && t.auto_completes && (
        <button className="mt-2 ml-7 text-xs text-brand-800 hover:underline inline-flex items-center gap-1" onClick={() => set.mutate("pending")}><Undo2 className="h-3 w-3" />Undo skip</button>
      )}
      {set.isError && <div className="mt-2"><ErrorState error={set.error} compact /></div>}
    </li>
  );
}
