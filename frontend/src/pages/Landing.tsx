import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight, BadgeCheck, ClipboardCheck, FileSearch, Gauge, MessageSquare, Route as RouteIcon, ShieldCheck,
} from "lucide-react";
import { Link } from "react-router-dom";
import { get } from "@/api/client";
import type { Role } from "@/api/types";
import { Logo } from "@/components/AppShell";
import { LinkButton, Skeleton } from "@/components/ui";
import { useSession } from "@/hooks/session";

const LOOP = [
  { icon: FileSearch, title: "Match your resume to the job", text: "Paste a job description. We extract its requirements and show which ones your resume actually evidences." },
  { icon: ClipboardCheck, title: "Measure what you can do", text: "A 15-question diagnostic tests the role's most important skills. Objective answers are scored by code." },
  { icon: Gauge, title: "See ranked, evidence-backed gaps", text: "Every gap shows its evidence and the published formula behind its priority — no mystery scores." },
  { icon: RouteIcon, title: "Follow a plan that fits your time", text: "A day-by-day plan sized to your deadline and daily minutes, with practice, mock interviews and re-checks." },
];

export default function Landing() {
  const { data: me } = useSession();
  const roles = useQuery({ queryKey: ["roles"], queryFn: () => get<Role[]>("/roles") });
  const cta = me ? { to: "/app/dashboard", label: "Go to dashboard" } : { to: "/login", label: "Login" };

  return (
    <div className="min-h-screen bg-white">
      <header className="border-b border-line">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 h-16 flex items-center justify-between">
          <Logo />
          <nav className="flex items-center gap-2">
            <Link to="/how-scores-work" className="hidden sm:inline text-sm text-ink-muted hover:text-ink px-3 py-2">How scores work</Link>
            <LinkButton to={cta.to} size="sm">{cta.label}</LinkButton>
          </nav>
        </div>
      </header>

      <section className="bg-navy-900 text-white">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 py-14 sm:py-20 grid lg:grid-cols-[1.2fr_1fr] gap-10 items-center">
          <div>
            <p className="text-brand-200 text-sm font-medium tracking-wide uppercase">Your AI job-readiness coach</p>
            <h1 className="mt-3 text-3xl sm:text-[2.6rem] sm:leading-[1.15] font-semibold text-white">
              What is stopping you from being ready for <span className="text-brand-200">this specific job</span> — and what should you do next?
            </h1>
            <p className="mt-4 text-slate-300 text-lg max-w-xl">
              RoleReady connects your resume, a diagnostic assessment, practice and mock interviews into one loop,
              so every recommendation is backed by evidence you can see.
            </p>
            <div className="mt-7 flex flex-wrap gap-3">
              <LinkButton to={cta.to} size="lg" className="bg-brand-500 hover:bg-brand-600 text-navy-950" icon={<ArrowRight className="h-4 w-4" />}>
                {me ? "Go to dashboard" : "Login to start"}
              </LinkButton>
              <LinkButton to="/how-scores-work" size="lg" variant="ghost" className="text-slate-200 hover:text-white hover:bg-white/10">
                How scoring works
              </LinkButton>
            </div>
          </div>
          <div className="rounded-lg bg-navy-800 border border-white/10 p-5">
            <div className="text-xs uppercase tracking-wide text-slate-400">Example next action</div>
            <div className="mt-2 text-white font-medium">Practise SQL (25 min)</div>
            <p className="mt-1 text-sm text-slate-300">SQL is a core requirement and your last 3 answers averaged 33%. A checkpoint is scheduled after practice.</p>
            <div className="mt-4 text-xs text-slate-400">Based on</div>
            <ul className="mt-1 space-y-1 text-sm text-slate-200">
              <li className="flex gap-2"><BadgeCheck className="h-4 w-4 text-brand-200 mt-0.5" />Diagnostic: 1 of 3 SQL questions correct</li>
              <li className="flex gap-2"><BadgeCheck className="h-4 w-4 text-brand-200 mt-0.5" />Resume lists SQL only in Skills</li>
            </ul>
            <p className="mt-4 text-[11px] text-slate-500">Illustration only — your recommendations come from your own evidence.</p>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 sm:px-6 py-14">
        <h2 className="text-xl font-semibold">One connected loop instead of five disconnected tools</h2>
        <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {LOOP.map(({ icon: Icon, title, text }, i) => (
            <div key={title} className="card p-5">
              <div className="flex items-center gap-2 text-brand-700"><Icon className="h-5 w-5" aria-hidden /><span className="text-xs font-medium">Step {i + 1}</span></div>
              <h3 className="mt-3 font-semibold text-[15px]">{title}</h3>
              <p className="mt-1 text-sm text-ink-muted leading-relaxed">{text}</p>
            </div>
          ))}
        </div>
        <div className="mt-4 card p-5 flex items-start gap-3">
          <MessageSquare className="h-5 w-5 text-brand-700 shrink-0 mt-0.5" aria-hidden />
          <p className="text-sm text-ink-muted"><span className="font-medium text-ink">Then re-measure.</span> Typed mock interviews are scored on a five-part rubric that quotes your own answer,
            and short checkpoints show change only when attempts are genuinely comparable.</p>
        </div>
      </section>

      <section className="bg-canvas border-y border-line">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 py-12">
          <h2 className="text-xl font-semibold">Supported roles</h2>
          <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {roles.isLoading && [0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-32" />)}
            {roles.data?.map((r) => (
              <div key={r.slug} className="card p-4">
                <div className="font-semibold">{r.name}</div>
                <p className="text-sm text-ink-muted mt-1">{r.description}</p>
                <div className="mt-3 flex flex-wrap gap-1">
                  {r.top_skills.slice(0, 5).map((s) => <span key={s.slug} className="text-xs rounded bg-slate-100 px-1.5 py-0.5 text-slate-700">{s.name}</span>)}
                </div>
              </div>
            ))}
            {roles.isError && <p className="text-sm text-ink-muted">Roles will appear once the server is reachable.</p>}
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 sm:px-6 py-12 grid gap-6 md:grid-cols-2">
        <div>
          <h2 className="text-xl font-semibold flex items-center gap-2"><ShieldCheck className="h-5 w-5 text-brand-700" />What we don't claim</h2>
          <ul className="mt-3 space-y-2 text-sm text-ink-muted list-disc pl-5">
            <li>No guarantee of ATS passage, interviews or offers. Readiness numbers are estimates from your evidence.</li>
            <li>No "real interview questions from Company X". Questions are curated for the role and labelled with their source.</li>
            <li>No invented resume facts. AI rewrites are checked against your own data and never applied without your approval.</li>
            <li>Missing from your resume is not the same as "can't do it" — we measure that separately.</li>
          </ul>
        </div>
        <div className="card p-5 bg-warn-bg border-amber-200">
          <h3 className="font-semibold text-amber-900">Hackathon demo login</h3>
          <p className="text-sm text-amber-900 mt-1 leading-relaxed">This prototype signs you in with just a username or email — no password and
            no email verification. Anyone who types the same identifier reaches the same account, so don't store anything
            sensitive. It is not production-grade identity verification.</p>
        </div>
      </section>

      <footer className="border-t border-line">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 py-6 text-xs text-ink-subtle flex flex-wrap gap-4 justify-between">
          <span>RoleReady · Fetch-A-Thon 3.0 prototype</span>
          <Link to="/how-scores-work" className="hover:text-ink">How scores work</Link>
        </div>
      </footer>
    </div>
  );
}
