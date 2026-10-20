import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Briefcase, FileSearch, ListChecks, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { get, patch } from "@/api/client";
import type { Target } from "@/api/types";
import { JDForm, NeedTarget, RequirementEditor, SectionCard } from "@/components/domain";
import { Badge, Button, ErrorState, Field, Input, Notice, PageHeader, PageSkeleton, useToast } from "@/components/ui";
import { fmtDateTime } from "@/lib/format";

export default function TargetPage() {
  return <NeedTarget>{(tid) => <TargetView tid={tid} />}</NeedTarget>;
}

function TargetView({ tid }: { tid: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["target", tid], queryFn: () => get<Target>(`/targets/${tid}`) });
  const [showJD, setShowJD] = useState(false);
  const { register, handleSubmit, reset, watch, formState: { isDirty } } = useForm<{ job_title: string;
    company_name: string; deadline_date: string; daily_minutes: number }>();
  useEffect(() => {
    if (q.data) reset({ job_title: q.data.job_title, company_name: q.data.company_name ?? "",
      deadline_date: q.data.deadline_date, daily_minutes: q.data.daily_minutes });
  }, [q.data, reset]);
  const save = useMutation({
    mutationFn: (v: any) => patch<Target>(`/targets/${tid}`, { ...v, daily_minutes: Number(v.daily_minutes),
      company_name: v.company_name || null }),
    onSuccess: (t) => { qc.setQueryData(["target", tid], t); qc.invalidateQueries({ queryKey: ["plan"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] }); toast("Target updated — your plan was recalculated if timing changed"); },
  });
  if (q.isLoading) return <PageSkeleton />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const t = q.data!;
  const jd = t.job_description;

  return (
    <div className="space-y-5 max-w-4xl">
      <PageHeader eyebrow={t.role.name} title={t.job_title} subtitle="Your target job, its requirements, and the time you have." />
      {t.company_notice && <Notice tone="info">{t.company_notice}</Notice>}

      <SectionCard title="Target settings" icon={<Briefcase className="h-4 w-4" />}>
        <form onSubmit={handleSubmit((v) => save.mutate(v))} className="grid gap-4 sm:grid-cols-2" noValidate>
          <Field label="Job title" htmlFor="tjt"><Input id="tjt" maxLength={120} {...register("job_title")} /></Field>
          <Field label="Company (label only)" htmlFor="tco"><Input id="tco" maxLength={120} {...register("company_name")} /></Field>
          <Field label="Deadline" htmlFor="tdl"><Input id="tdl" type="date" {...register("deadline_date")} /></Field>
          <Field label={`Daily study time: ${watch("daily_minutes")} minutes`} htmlFor="tdm">
            <input id="tdm" type="range" min={30} max={240} step={15} className="w-full accent-brand-700 h-10" {...register("daily_minutes")} />
          </Field>
          <div className="sm:col-span-2 flex flex-wrap items-center gap-3">
            <Button type="submit" disabled={!isDirty} loading={save.isPending} icon={<Save className="h-4 w-4" />}>Save changes</Button>
            <span className="text-xs text-ink-subtle">Changing the deadline or daily time reschedules future tasks; completed ones stay.</span>
          </div>
          {save.isError && <div className="sm:col-span-2"><ErrorState error={save.error} compact /></div>}
        </form>
      </SectionCard>

      <SectionCard title="Job description" icon={<FileSearch className="h-4 w-4" />}
        subtitle={jd ? `Analysed ${fmtDateTime(jd.created_at)} · ${jd.status === "extracted" ? `AI extraction (${jd.model})` : "keyword matching fallback"}` : "Using the role's default requirements"}
        action={<Button size="sm" variant="secondary" onClick={() => setShowJD(!showJD)}>{jd ? "Replace" : "Add job description"}</Button>}>
        {showJD && <div className="mb-4"><JDForm targetId={tid} onDone={() => { setShowJD(false); qc.invalidateQueries({ queryKey: ["target", tid] }); }} /></div>}
        {jd ? (
          <div className="space-y-4">
            {jd.warnings.includes("AI_FALLBACK") && <Notice tone="warn">Extracted with keyword matching because the AI service wasn't available — review carefully.</Notice>}
            <div className="grid gap-4 sm:grid-cols-2">
              {(["responsibilities", "tools", "experience_expectations", "collaboration"] as const).map((k) => (
                jd.analysis[k]?.length ? (
                  <div key={k}>
                    <div className="text-xs font-medium text-ink-muted mb-1 capitalize">{k.replace("_", " ")}</div>
                    <ul className="text-sm space-y-1 list-disc pl-4">{jd.analysis[k].slice(0, 8).map((x) => <li key={x}>{x}</li>)}</ul>
                  </div>
                ) : null
              ))}
            </div>
            <details className="text-sm">
              <summary className="cursor-pointer text-brand-800">Show original text</summary>
              <p className="mt-2 whitespace-pre-wrap text-ink-muted max-h-64 overflow-y-auto">{jd.text}</p>
            </details>
          </div>
        ) : !showJD && <p className="text-sm text-ink-muted">Add a job description to measure against this specific posting.</p>}
      </SectionCard>

      <SectionCard title="Requirements" icon={<ListChecks className="h-4 w-4" />}
        subtitle={t.requirements_confirmed_at ? undefined : "Not confirmed yet — confirm so coverage and gaps use the right list."}
        action={t.requirements_confirmed_at ? <Badge tone="ok">Confirmed</Badge> : <Badge tone="warn">Needs confirmation</Badge>}>
        <RequirementEditor targetId={tid} onConfirmed={() => qc.invalidateQueries({ queryKey: ["target", tid] })} />
      </SectionCard>
    </div>
  );
}
