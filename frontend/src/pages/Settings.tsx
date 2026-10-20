import { useMutation, useQueryClient } from "@tanstack/react-query";
import { LogOut, Save, ShieldAlert, Sparkles, User } from "lucide-react";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { useNavigate } from "react-router-dom";
import { patch } from "@/api/client";
import type { Me, User as UserT } from "@/api/types";
import { SectionCard } from "@/components/domain";
import { Button, ErrorState, Field, Input, Notice, PageHeader, Select, useToast } from "@/components/ui";
import { useLogout, useSession } from "@/hooks/session";

const TIMEZONES = ["Asia/Kolkata", "Asia/Dubai", "Asia/Singapore", "Europe/London", "America/New_York", "America/Los_Angeles", "UTC"];

export default function SettingsPage() {
  const { data: me } = useSession();
  const qc = useQueryClient();
  const toast = useToast();
  const nav = useNavigate();
  const logout = useLogout();
  const { register, handleSubmit, reset, formState: { isDirty } } = useForm<{ preferred_name: string; experience_level: string; timezone: string }>();
  useEffect(() => {
    if (me) reset({ preferred_name: me.user.preferred_name ?? "", experience_level: me.user.experience_level ?? "fresher", timezone: me.user.timezone });
  }, [me, reset]);
  const save = useMutation({ mutationFn: (v: any) => patch("/profile", v),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["me"] }); toast("Profile saved"); } });
  const finish = useMutation({ mutationFn: () => patch<UserT>("/profile", { complete_onboarding: true }),
    onSuccess: (user) => {
      qc.setQueryData<Me | null>(["me"], (old) => (old ? { ...old, user } : old));
      nav("/app/dashboard");
    } });

  return (
    <div className="space-y-5 max-w-2xl">
      <PageHeader title="Settings" />
      <SectionCard title="Profile" icon={<User className="h-4 w-4" />}>
        <form onSubmit={handleSubmit((v) => save.mutate(v))} className="space-y-4">
          <Field label="Preferred name" htmlFor="s-name"><Input id="s-name" maxLength={100} {...register("preferred_name")} /></Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Experience level" htmlFor="s-xp">
              <Select id="s-xp" {...register("experience_level")}><option value="student">Student</option><option value="fresher">Fresher</option><option value="early_career">Early career</option></Select>
            </Field>
            <Field label="Timezone" htmlFor="s-tz" hint="Plan days are calculated in this timezone.">
              <Select id="s-tz" {...register("timezone")}>{TIMEZONES.map((t) => <option key={t} value={t}>{t}</option>)}</Select>
            </Field>
          </div>
          {save.isError && <ErrorState error={save.error} compact />}
          <Button type="submit" disabled={!isDirty} loading={save.isPending} icon={<Save className="h-4 w-4" />}>Save</Button>
        </form>
        {me && !me.user.onboarding_completed && (
          <div className="mt-4 pt-4 border-t border-line text-sm">
            <p className="text-ink-muted mb-2">You haven't finished setup.</p>
            <Button size="sm" variant="secondary" loading={finish.isPending} onClick={() => finish.mutate()}>Skip remaining setup and open the dashboard</Button>
          </div>
        )}
      </SectionCard>

      <SectionCard title="Account and login" icon={<ShieldAlert className="h-4 w-4" />}>
        <p className="text-sm">Signed in as <span className="font-medium">{me?.user.identifier}</span> ({me?.user.identifier_kind}).</p>
        <Notice tone="warn" className="mt-3" title="Demo-only authentication">
          This hackathon prototype doesn't verify that you own this identifier — anyone who enters it opens this account.
          Don't store sensitive information. Sessions are server-side, HTTP-only cookies that expire after 7 days of inactivity.
        </Notice>
        <Button className="mt-4" variant="secondary" icon={<LogOut className="h-4 w-4" />} loading={logout.isPending}
          onClick={async () => { await logout.mutateAsync().catch(() => undefined); nav("/login", { replace: true }); }}>Log out</Button>
      </SectionCard>

      <SectionCard title="AI and your data" icon={<Sparkles className="h-4 w-4" />}>
        <ul className="text-sm text-ink-muted list-disc pl-5 space-y-1.5">
          <li>Job-description extraction, resume structuring, bullet suggestions and answer evaluation use a hosted NVIDIA model through the server. Your browser never receives the API key.</li>
          <li>Names, emails, phone numbers and links are removed from resume text before it is sent to the AI provider.</li>
          <li>Scores, gaps, plans and recommendations are calculated by RoleReady's own code, not by the AI.</li>
          <li>Original PDF files are never stored. You can delete a resume (and everything derived from it) in Resume Studio.</li>
        </ul>
      </SectionCard>
    </div>
  );
}
