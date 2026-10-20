import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Check, FileText } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { useNavigate } from "react-router-dom";
import { z } from "zod";
import { ApiError, get, patch, post } from "@/api/client";
import type { Me, Role, Target, User } from "@/api/types";
import { JDForm, RequirementEditor, ResumeImport } from "@/components/domain";
import { Badge, Button, Card, CardBody, cx, Dialog, ErrorState, Field, Input, Notice, PageHeader, Select, Skeleton } from "@/components/ui";
import { useSession } from "@/hooks/session";

const STEPS = ["About you", "Target role", "Job description", "Resume"];

const profileSchema = z.object({
  preferred_name: z.string().trim().min(1, "Tell us what to call you.").max(100),
  experience_level: z.enum(["student", "fresher", "early_career"], { errorMap: () => ({ message: "Choose one." }) }),
});

function addDays(n: number) {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}

export const targetSchema = z.object({
  role_slug: z.string().min(1, "Choose a role."),
  job_title: z.string().trim().max(120).optional(),
  company_name: z.string().trim().max(120).optional(),
  deadline_date: z.string().refine((v) => v > new Date().toISOString().slice(0, 10), "Choose a future date.")
    .refine((v) => v <= addDays(365), "Choose a date within a year."),
  daily_minutes: z.coerce.number().min(30).max(240).multipleOf(15, "Use steps of 15 minutes."),
});
export type TargetForm = z.infer<typeof targetSchema>;

export default function Onboarding() {
  const { data: me } = useSession();
  const qc = useQueryClient();
  const nav = useNavigate();
  const [step, setStep] = useState(1);
  useEffect(() => {
    if (me) setStep(Math.min(Math.max(me.user.onboarding_step, 1), 4));
  }, [me?.user.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const advance = useMutation({
    mutationFn: (to: number) => patch<User>("/profile", to > 4 ? { complete_onboarding: true } : { onboarding_step: to }),
    onSuccess: (user, to) => {
      // Update the cached session synchronously so route guards see the new onboarding state before navigating.
      qc.setQueryData<Me | null>(["me"], (old) => (old ? { ...old, user } : old));
      qc.invalidateQueries({ queryKey: ["me"] });
      if (to > 4) nav("/app/dashboard", { replace: true });
      else setStep(to);
    },
  });

  return (
    <div className="max-w-3xl">
      <PageHeader eyebrow="Getting started" title="Set up your preparation"
        subtitle="Four short steps. Each one is saved, so you can stop and continue later." />
      <ol className="flex gap-2 mb-6" aria-label="Progress">
        {STEPS.map((s, i) => {
          const n = i + 1;
          return (
            <li key={s} className="flex-1">
              <div className={cx("h-1.5 rounded-full", n < step ? "bg-brand-600" : n === step ? "bg-brand-500" : "bg-slate-200")} />
              <div className={cx("mt-1.5 text-xs", n === step ? "text-ink font-medium" : "text-ink-subtle")}>
                <span className="sm:hidden">{n === step ? s : n}</span><span className="hidden sm:inline">{n}. {s}</span>
              </div>
            </li>
          );
        })}
      </ol>
      {step === 1 && <ProfileStep onNext={() => advance.mutate(2)} />}
      {step === 2 && <TargetStep onNext={() => advance.mutate(3)} onBack={() => setStep(1)} />}
      {step === 3 && <JDStep onNext={() => advance.mutate(4)} onBack={() => setStep(2)} />}
      {step === 4 && <ResumeStep onFinish={() => advance.mutate(5)} onBack={() => setStep(3)} finishing={advance.isPending} />}
      {advance.isError && <div className="mt-3"><ErrorState error={advance.error} compact /></div>}
    </div>
  );
}

function ProfileStep({ onNext }: { onNext: () => void }) {
  const { data: me } = useSession();
  const qc = useQueryClient();
  const { register, handleSubmit, formState: { errors } } = useForm<z.infer<typeof profileSchema>>({
    resolver: zodResolver(profileSchema),
    defaultValues: { preferred_name: me?.user.preferred_name ?? "", experience_level: (me?.user.experience_level as any) ?? undefined },
  });
  const save = useMutation({ mutationFn: (v: any) => patch("/profile", v),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["me"] }); onNext(); } });
  return (
    <Card><CardBody>
      <form onSubmit={handleSubmit((v) => save.mutate(v))} className="space-y-4" noValidate>
        <Field label="What should we call you?" htmlFor="pn" error={errors.preferred_name?.message} required>
          <Input id="pn" autoComplete="given-name" invalid={!!errors.preferred_name} {...register("preferred_name")} />
        </Field>
        <Field label="Where are you in your career?" htmlFor="xp" error={errors.experience_level?.message} required>
          <Select id="xp" {...register("experience_level")} defaultValue={me?.user.experience_level ?? ""}>
            <option value="" disabled>Choose…</option>
            <option value="student">Student (internships)</option>
            <option value="fresher">Fresher / final-year (campus or first job)</option>
            <option value="early_career">Early career (up to 2 years)</option>
          </Select>
        </Field>
        {save.isError && <ErrorState error={save.error} compact />}
        <Button type="submit" loading={save.isPending} icon={<ArrowRight className="h-4 w-4" />}>Continue</Button>
      </form>
    </CardBody></Card>
  );
}

export function TargetFields({ register, errors, roles, watchRole, minutes }: { register: any; errors: any; roles?: Role[];
  watchRole?: string; minutes: number }) {
  return (
    <div className="space-y-5">
      <fieldset>
        <legend className="label">Target role <span className="text-bad">*</span></legend>
        <div className="grid gap-2 sm:grid-cols-2 mt-1">
          {!roles && [0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-24" />)}
          {roles?.map((r) => (
            <label key={r.slug} className={cx("card p-3.5 cursor-pointer transition-colors",
              watchRole === r.slug ? "border-brand-600 ring-2 ring-brand-600/20" : "hover:border-slate-300")}>
              <div className="flex items-start gap-2">
                <input type="radio" value={r.slug} className="mt-1 accent-brand-700" {...register("role_slug")} />
                <div>
                  <div className="font-medium text-sm">{r.name}</div>
                  <div className="text-xs text-ink-muted mt-0.5">{r.description}</div>
                  <div className="mt-2 flex flex-wrap gap-1">{r.top_skills.slice(0, 4).map((s) => <Badge key={s.slug}>{s.name}</Badge>)}</div>
                </div>
              </div>
            </label>
          ))}
        </div>
        {errors.role_slug && <p className="text-sm text-bad mt-1" role="alert">{errors.role_slug.message}</p>}
      </fieldset>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Job title (optional)" htmlFor="jt" hint="Shown as a label, e.g. “Backend Engineer – Fresher”.">
          <Input id="jt" {...register("job_title")} />
        </Field>
        <Field label="Company (optional)" htmlFor="co" hint="Used as a label only — we don't have company-specific question data.">
          <Input id="co" {...register("company_name")} />
        </Field>
        <Field label="Preparation deadline" htmlFor="dl" error={errors.deadline_date?.message} required>
          <Input id="dl" type="date" min={addDays(1)} max={addDays(365)} {...register("deadline_date")} />
        </Field>
        <Field label={`Daily study time: ${minutes} minutes`} htmlFor="dm" error={errors.daily_minutes?.message}
          hint="Your plan never schedules more than this per day.">
          <input id="dm" type="range" min={30} max={240} step={15} className="w-full accent-brand-700 h-10" {...register("daily_minutes")} />
        </Field>
      </div>
    </div>
  );
}

function TargetStep({ onNext, onBack }: { onNext: () => void; onBack: () => void }) {
  const qc = useQueryClient();
  const { data: me } = useSession();
  const roles = useQuery({ queryKey: ["roles"], queryFn: () => get<Role[]>("/roles"), staleTime: Infinity });
  const existing = useQuery({ queryKey: ["target", me?.active_target_id], enabled: !!me?.active_target_id,
    queryFn: () => get<Target>(`/targets/${me!.active_target_id}`) });
  const [confirmArchive, setConfirmArchive] = useState<TargetForm | null>(null);
  const { register, handleSubmit, watch, formState: { errors } } = useForm<TargetForm>({
    resolver: zodResolver(targetSchema), defaultValues: { deadline_date: addDays(28), daily_minutes: 60, role_slug: "" },
  });
  const create = useMutation({
    mutationFn: ({ v, archive }: { v: TargetForm; archive: boolean }) =>
      post("/targets", { ...v, job_title: v.job_title || undefined, company_name: v.company_name || undefined, archive_current: archive }),
    onSuccess: () => { qc.invalidateQueries(); onNext(); },
    onError: (e, vars) => { if (e instanceof ApiError && e.code === "ACTIVE_TARGET_EXISTS") setConfirmArchive(vars.v); },
  });
  return (
    <Card><CardBody>
      {existing.data && (
        <Notice tone="info" className="mb-4" title={`You already have a target: ${existing.data.job_title}`}
          action={<Button size="sm" variant="secondary" onClick={onNext}>Keep it</Button>}>
          Keep it and continue, or choose a new role below (your current target will be archived, not deleted).
        </Notice>
      )}
      <form onSubmit={handleSubmit((v) => create.mutate({ v, archive: false }))} className="space-y-5" noValidate>
        <TargetFields register={register} errors={errors} roles={roles.data} watchRole={watch("role_slug")} minutes={Number(watch("daily_minutes"))} />
        {create.isError && !(create.error instanceof ApiError && create.error.code === "ACTIVE_TARGET_EXISTS") && <ErrorState error={create.error} compact />}
        <div className="flex gap-2">
          <Button type="button" variant="ghost" onClick={onBack} icon={<ArrowLeft className="h-4 w-4" />}>Back</Button>
          <Button type="submit" loading={create.isPending} icon={<ArrowRight className="h-4 w-4" />}>Save target</Button>
        </div>
      </form>
      <Dialog open={!!confirmArchive} onClose={() => setConfirmArchive(null)} title="Start a new target?"
        footer={<><Button variant="secondary" onClick={() => setConfirmArchive(null)}>Cancel</Button>
          <Button onClick={() => { create.mutate({ v: confirmArchive!, archive: true }); setConfirmArchive(null); }}>Archive and continue</Button></>}>
        Your current target will be archived. Its history stays viewable, and your assessment evidence carries over to
        skills the new role shares.
      </Dialog>
    </CardBody></Card>
  );
}

function JDStep({ onNext, onBack }: { onNext: () => void; onBack: () => void }) {
  const { data: me } = useSession();
  const tid = me?.active_target_id;
  const [phase, setPhase] = useState<"paste" | "review">("paste");
  const [result, setResult] = useState<any>(null);
  if (!tid) return <Notice tone="warn">Create a target first.</Notice>;
  return (
    <Card><CardBody className="space-y-4">
      {phase === "paste" ? (
        <>
          <div>
            <h2 className="font-semibold">Paste the job description</h2>
            <p className="text-sm text-ink-muted mt-1">We'll extract its requirements and map them to our skill list. If you don't
              have one, use the role's default requirements.</p>
          </div>
          <JDForm targetId={tid} onDone={(r) => { setResult(r); setPhase("review"); }} />
          <div className="flex flex-wrap gap-2 pt-1 border-t border-line">
            <Button variant="ghost" onClick={onBack} icon={<ArrowLeft className="h-4 w-4" />}>Back</Button>
            <Button variant="secondary" onClick={() => setPhase("review")}>Skip — use role defaults</Button>
          </div>
        </>
      ) : (
        <>
          <div>
            <h2 className="font-semibold">Check the requirements</h2>
            <p className="text-sm text-ink-muted mt-1">These are what your resume and assessments will be measured against.</p>
          </div>
          {result?.warnings?.includes("AI_FALLBACK") && (
            <Notice tone="warn" title="Extracted with keyword matching">The AI service wasn't available, so requirements were
              found by matching known skill names. Please review them carefully.</Notice>)}
          {result?.warnings?.includes("ROLE_MISMATCH") && (
            <Notice tone="warn">This job description may not match the role you chose; consider another base role.</Notice>)}
          {result?.status === "extracted" && <Notice tone="info">Extracted by AI from your job description. Items marked
            “Inferred — check” weren't found word-for-word in the text.</Notice>}
          <RequirementEditor targetId={tid} onConfirmed={onNext} />
          <Button variant="ghost" onClick={() => setPhase("paste")} icon={<ArrowLeft className="h-4 w-4" />}>Back to job description</Button>
        </>
      )}
    </CardBody></Card>
  );
}

function ResumeStep({ onFinish, onBack, finishing }: { onFinish: () => void; onBack: () => void; finishing: boolean }) {
  const [imported, setImported] = useState<any>(null);
  return (
    <Card><CardBody className="space-y-4">
      <div>
        <h2 className="font-semibold">Add your resume</h2>
        <p className="text-sm text-ink-muted mt-1">Optional, but it lets us show which requirements your resume already evidences.
          You can review and correct everything we extract.</p>
      </div>
      {imported ? (
        <Notice tone="ok" title="Resume imported">
          We found {imported.content.projects.length} project(s), {imported.content.experience.length} experience entr{imported.content.experience.length === 1 ? "y" : "ies"}
          {" "}and {imported.content.skills.length} skills. Review it in Resume Studio after setup — nothing is treated as fact until you do.
        </Notice>
      ) : <ResumeImport onImported={(_id, r) => setImported(r)} />}
      <div className="flex flex-wrap gap-2 pt-2 border-t border-line">
        <Button variant="ghost" onClick={onBack} icon={<ArrowLeft className="h-4 w-4" />}>Back</Button>
        <Button onClick={onFinish} loading={finishing} icon={imported ? <Check className="h-4 w-4" /> : <FileText className="h-4 w-4" />}>
          {imported ? "Finish setup" : "Skip for now and finish"}
        </Button>
      </div>
    </CardBody></Card>
  );
}
