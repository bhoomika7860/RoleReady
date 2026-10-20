import { useQuery } from "@tanstack/react-query";
import { BarChart3, FileText, MessageSquare, TrendingUp } from "lucide-react";
import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { get } from "@/api/client";
import { NeedTarget, SectionCard } from "@/components/domain";
import { Badge, Button, EmptyState, ErrorState, LinkButton, PageHeader, PageSkeleton } from "@/components/ui";
import { fmtDate } from "@/lib/format";

export default function ProgressPage() {
  return <NeedTarget>{(tid) => <ProgressView tid={tid} />}</NeedTarget>;
}

function ProgressView({ tid }: { tid: string }) {
  const q = useQuery({ queryKey: ["progress", tid], queryFn: () => get(`/targets/${tid}/progress`) });
  if (q.isLoading) return <PageSkeleton />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const d: any = q.data;
  return (
    <div className="space-y-5">
      <PageHeader title="Progress" subtitle="Changes are reported only between comparable measurements, with dates and item counts." />
      <p className="text-sm text-ink-muted max-w-prose">{d.rules}</p>
      <SectionCard title="Skill measurements" icon={<TrendingUp className="h-4 w-4" />}>
        {d.skills.length ? (
          <div className="space-y-4">
            {d.skills.map((s: any) => (
              <div key={s.skill.slug} className="rounded-md border border-line p-3">
                <div className="font-medium mb-2">{s.skill.name}</div>
                <ul className="space-y-1.5 text-sm">
                  {s.series.map((p: any) => (
                    <li key={p.assessment_id} className="flex flex-wrap items-center gap-2">
                      <Badge tone={p.kind === "checkpoint" ? "brand" : "neutral"}>{p.kind}</Badge>
                      <span className="text-ink-subtle">{fmtDate(p.date)}</span>
                      <span className="tabular-nums font-medium">{p.score ?? "—"}/100</span>
                      <span className="text-xs text-ink-subtle">({p.items} question{p.items === 1 ? "" : "s"})</span>
                      {p.comparable_with_previous && p.delta !== null && (
                        <Badge tone={p.change === "Improved" ? "ok" : p.change === "Declined" ? "bad" : "neutral"}>
                          {p.delta >= 0 ? "+" : ""}{p.delta} · {p.change}</Badge>)}
                      {!p.comparable_with_previous && p.reason && <span className="text-xs text-ink-subtle">Not compared: {p.reason}</span>}
                      {p.includes_repeats && <Badge tone="warn">includes repeated questions</Badge>}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        ) : <EmptyState title="No measurements yet" action={<LinkButton to="/app/assessment">Take the diagnostic</LinkButton>} />}
      </SectionCard>
      <SectionCard title="Resume coverage over time" icon={<FileText className="h-4 w-4" />}>
        {d.coverage.length ? <ChartOrTable data={d.coverage.map((c: any) => ({ date: fmtDate(c.date), value: c.coverage, note: c.reason ?? (c.delta !== null ? `${c.delta >= 0 ? "+" : ""}${c.delta}` : "") }))}
          label="Coverage" /> : <p className="text-sm text-ink-muted">No analyses yet.</p>}
        <p className="text-xs text-ink-subtle mt-2">Changes are compared only when the requirement list is the same.</p>
      </SectionCard>
      <SectionCard title="Interview retries (same question, same rubric)" icon={<MessageSquare className="h-4 w-4" />}>
        {d.interview_retries.length ? (
          <ul className="space-y-1.5 text-sm">{d.interview_retries.map((r: any, i: number) => (
            <li key={i} className="flex flex-wrap gap-2 items-center"><span className="truncate max-w-md">{r.question}</span>
              <span className="tabular-nums">{r.previous_overall} → {r.overall}</span>
              <Badge tone={r.delta > 0 ? "ok" : r.delta < 0 ? "bad" : "neutral"}>{r.delta >= 0 ? "+" : ""}{r.delta}</Badge></li>))}</ul>
        ) : <p className="text-sm text-ink-muted">Retry an interview question to see a like-for-like comparison.</p>}
      </SectionCard>
      <SectionCard title="All interview answers" icon={<BarChart3 className="h-4 w-4" />} subtitle="Different questions — a trend, not a like-for-like comparison.">
        {d.interview_trend.length ? <ChartOrTable data={d.interview_trend.map((t: any) => ({ date: fmtDate(t.date), value: t.overall, note: t.question }))} label="Overall" />
          : <p className="text-sm text-ink-muted">No interview answers yet.</p>}
      </SectionCard>
    </div>
  );
}

function ChartOrTable({ data, label }: { data: { date: string; value: number; note: string }[]; label: string }) {
  const [table, setTable] = useState(false);
  return (
    <div>
      <div className="flex justify-end mb-1"><Button size="sm" variant="ghost" onClick={() => setTable(!table)}>{table ? "Show chart" : "Show table"}</Button></div>
      {table ? (
        <table className="w-full text-sm"><thead><tr className="text-left text-xs text-ink-muted"><th className="py-1">Date</th><th>{label}</th><th>Note</th></tr></thead>
          <tbody>{data.map((r, i) => <tr key={i} className="border-t border-line"><td className="py-1.5">{r.date}</td><td className="tabular-nums">{r.value}</td><td className="text-ink-muted truncate max-w-xs">{r.note}</td></tr>)}</tbody></table>
      ) : (
        <div className="h-56" role="img" aria-label={`${label} over time: ${data.map((d) => `${d.date} ${d.value}`).join(", ")}`}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 12, left: -16, bottom: 0 }}>
              <CartesianGrid stroke="#E2E8F0" vertical={false} />
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#64748B" }} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: "#64748B" }} />
              <Tooltip />
              <Line type="monotone" dataKey="value" name={label} stroke="#0F766E" strokeWidth={2} dot={{ r: 3 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
