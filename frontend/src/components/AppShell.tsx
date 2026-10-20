import { useQuery } from "@tanstack/react-query";
import {
  BarChart3, BookOpen, CalendarCheck, ClipboardCheck, FileText, Gauge, LayoutDashboard, LogOut, Menu, MessageSquare,
  Settings, Target, Trophy, X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { get } from "@/api/client";
import type { Target as TargetT } from "@/api/types";
import { cx } from "@/components/ui";
import { useActiveTargetId, useLogout, useSession } from "@/hooks/session";

const NAV = [
  { to: "/app/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/app/target", label: "Target job", icon: Target },
  { to: "/app/resume", label: "Resume Studio", icon: FileText },
  { to: "/app/assessment", label: "Assessment", icon: ClipboardCheck },
  { to: "/app/results", label: "Results & gaps", icon: Gauge },
  { to: "/app/plan", label: "Study plan", icon: CalendarCheck },
  { to: "/app/practice", label: "Practice lab", icon: Trophy },
  { to: "/app/interview", label: "Mock interview", icon: MessageSquare },
  { to: "/app/progress", label: "Progress", icon: BarChart3 },
  { to: "/app/resources", label: "Resources", icon: BookOpen },
];
const MOBILE_TABS = ["/app/dashboard", "/app/plan", "/app/practice", "/app/interview"];
const SHORT: Record<string, string> = { "/app/dashboard": "Home", "/app/plan": "Plan", "/app/practice": "Practice",
  "/app/interview": "Interview" };

export function Logo({ dark = false }: { dark?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2 font-semibold tracking-tight">
      <svg viewBox="0 0 32 32" className="h-7 w-7" aria-hidden>
        <rect width="32" height="32" rx="7" fill={dark ? "#ffffff" : "#0B1F3A"} />
        <path d="M9 22V10h7.2c2.9 0 4.6 1.6 4.6 4 0 1.8-1 3.1-2.6 3.6L21.5 22h-3.3l-2.9-4.1H12V22H9zm3-6.8h4c1.2 0 1.9-.6 1.9-1.6s-.7-1.6-1.9-1.6h-4v3.2z"
          fill={dark ? "#0B1F3A" : "#fff"} />
        <circle cx="24" cy="10" r="2.2" fill="#14B8A6" />
      </svg>
      <span className={dark ? "text-white" : "text-navy-900"}>RoleReady</span>
    </span>
  );
}

function useTarget() {
  const tid = useActiveTargetId();
  return useQuery({ queryKey: ["target", tid], queryFn: () => get<TargetT>(`/targets/${tid}`), enabled: !!tid });
}

export function AppShell() {
  const { data: me } = useSession();
  const { data: target } = useTarget();
  const logout = useLogout();
  const nav = useNavigate();
  const loc = useLocation();
  const [moreOpen, setMoreOpen] = useState(false);
  useEffect(() => { setMoreOpen(false); window.scrollTo(0, 0); }, [loc.pathname]);

  const doLogout = async () => {
    await logout.mutateAsync().catch(() => undefined);
    nav("/login", { replace: true });
  };
  const name = me?.user.preferred_name || me?.user.identifier;

  return (
    <div className="min-h-screen lg:flex">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 bg-white px-3 py-2 rounded">
        Skip to content</a>
      {/* desktop sidebar */}
      <aside className="hidden lg:flex lg:flex-col w-64 shrink-0 bg-navy-900 text-slate-200 min-h-screen sticky top-0 h-screen">
        <div className="px-5 py-5"><NavLink to="/app/dashboard"><Logo dark /></NavLink></div>
        {target && (
          <div className="mx-4 mb-3 rounded-md bg-navy-800 px-3 py-2.5">
            <div className="text-[11px] uppercase tracking-wide text-slate-400">Preparing for</div>
            <div className="text-sm font-medium text-white truncate" title={target.job_title}>{target.job_title}</div>
            <div className="text-xs text-slate-400 mt-0.5">
              {target.deadline_passed ? "Deadline passed" : `${target.days_to_deadline} days to deadline`}
            </div>
          </div>
        )}
        <nav aria-label="Main" className="flex-1 overflow-y-auto px-3 space-y-0.5">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} className={({ isActive }) => cx(
              "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
              isActive ? "bg-white/10 text-white font-medium" : "text-slate-300 hover:bg-white/5 hover:text-white")}>
              <Icon className="h-4 w-4 shrink-0" aria-hidden />{label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-white/10 p-3 space-y-0.5">
          <NavLink to="/app/settings" className={({ isActive }) => cx("flex items-center gap-3 rounded-md px-3 py-2 text-sm",
            isActive ? "bg-white/10 text-white" : "text-slate-300 hover:bg-white/5 hover:text-white")}>
            <Settings className="h-4 w-4" aria-hidden />Settings
          </NavLink>
          <button onClick={doLogout} className="w-full flex items-center gap-3 rounded-md px-3 py-2 text-sm text-slate-300 hover:bg-white/5 hover:text-white">
            <LogOut className="h-4 w-4" aria-hidden />Log out
          </button>
          <div className="px-3 pt-2 text-xs text-slate-400 truncate" title={me?.user.identifier}>Signed in as {name}</div>
        </div>
      </aside>

      {/* mobile top bar */}
      <header className="lg:hidden sticky top-0 z-30 bg-navy-900 text-white">
        <div className="flex items-center justify-between px-4 h-14">
          <NavLink to="/app/dashboard"><Logo dark /></NavLink>
          <div className="text-xs text-slate-300 truncate max-w-[45%] text-right">{target?.job_title}</div>
        </div>
      </header>

      <main id="main" className="flex-1 min-w-0 pb-24 lg:pb-10">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8 py-6">
          <Outlet />
        </div>
      </main>

      {/* mobile bottom tabs */}
      <nav aria-label="Main" className="lg:hidden fixed bottom-0 inset-x-0 z-30 bg-white border-t border-line">
        <div className="grid grid-cols-5">
          {MOBILE_TABS.map((to) => {
            const item = NAV.find((n) => n.to === to)!;
            const Icon = item.icon;
            return (
              <NavLink key={to} to={to} className={({ isActive }) => cx("flex flex-col items-center justify-center gap-0.5 h-16 text-[11px]",
                isActive ? "text-brand-700 font-medium" : "text-ink-muted")}>
                <Icon className="h-5 w-5" aria-hidden />
                {SHORT[to]}
              </NavLink>
            );
          })}
          <button onClick={() => setMoreOpen(true)} className="flex flex-col items-center justify-center gap-0.5 h-16 text-[11px] text-ink-muted"
            aria-haspopup="dialog" aria-expanded={moreOpen}>
            <Menu className="h-5 w-5" aria-hidden />More
          </button>
        </div>
      </nav>
      {moreOpen && (
        <div className="lg:hidden fixed inset-0 z-40" role="dialog" aria-modal="true" aria-label="More navigation">
          <div className="absolute inset-0 bg-navy-950/40" onClick={() => setMoreOpen(false)} aria-hidden />
          <div className="absolute bottom-0 inset-x-0 bg-white rounded-t-xl p-3 pb-6 shadow-pop">
            <div className="flex items-center justify-between px-2 pb-2">
              <span className="text-sm font-semibold">Menu</span>
              <button onClick={() => setMoreOpen(false)} aria-label="Close" className="p-2"><X className="h-4 w-4" /></button>
            </div>
            <div className="grid grid-cols-2 gap-1">
              {[...NAV.filter((n) => !MOBILE_TABS.includes(n.to)), { to: "/app/settings", label: "Settings", icon: Settings }]
                .map(({ to, label, icon: Icon }) => (
                  <NavLink key={to} to={to} className="flex items-center gap-2 rounded-md px-3 py-3 text-sm hover:bg-slate-50">
                    <Icon className="h-4 w-4 text-brand-700" aria-hidden />{label}
                  </NavLink>
                ))}
              <button onClick={doLogout} className="flex items-center gap-2 rounded-md px-3 py-3 text-sm hover:bg-slate-50 text-left">
                <LogOut className="h-4 w-4 text-brand-700" aria-hidden />Log out
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
