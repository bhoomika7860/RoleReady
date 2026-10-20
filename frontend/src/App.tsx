import { lazy, ReactNode, Suspense } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { PageSkeleton } from "@/components/ui";
import { useSession } from "@/hooks/session";
import Landing from "@/pages/Landing";
import Login from "@/pages/Login";

const Onboarding = lazy(() => import("@/pages/Onboarding"));
const Dashboard = lazy(() => import("@/pages/Dashboard"));
const TargetPage = lazy(() => import("@/pages/Target"));
const ResumePage = lazy(() => import("@/pages/Resume"));
const AssessmentPage = lazy(() => import("@/pages/Assessment"));
const ResultsPage = lazy(() => import("@/pages/Results"));
const PlanPage = lazy(() => import("@/pages/Plan"));
const PracticePage = lazy(() => import("@/pages/Practice"));
const InterviewPage = lazy(() => import("@/pages/Interview"));
const ProgressPage = lazy(() => import("@/pages/Progress"));
const ResourcesPage = lazy(() => import("@/pages/Resources"));
const SettingsPage = lazy(() => import("@/pages/Settings"));
const HowScoresWork = lazy(() => import("@/pages/HowScoresWork"));
const NotFound = lazy(() => import("@/pages/NotFound"));

function RequireAuth({ children }: { children: ReactNode }) {
  const { data, isLoading } = useSession();
  const loc = useLocation();
  if (isLoading) return <div className="p-6"><PageSkeleton /></div>;
  if (!data) return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname + loc.search)}`} replace />;
  return <>{children}</>;
}

/** Until onboarding is finished, app pages redirect there (settings stays reachable). */
function RequireOnboarded({ children }: { children: ReactNode }) {
  const { data } = useSession();
  if (data && !data.user.onboarding_completed) return <Navigate to="/app/onboarding" replace />;
  return <>{children}</>;
}

const page = (el: ReactNode, onboarded = true) => (
  <Suspense fallback={<PageSkeleton />}>{onboarded ? <RequireOnboarded>{el}</RequireOnboarded> : el}</Suspense>
);

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Login />} />
      <Route path="/how-scores-work" element={<Suspense fallback={<PageSkeleton />}><HowScoresWork /></Suspense>} />
      <Route path="/app" element={<RequireAuth><AppShell /></RequireAuth>}>
        <Route index element={<Navigate to="dashboard" replace />} />
        <Route path="onboarding" element={page(<Onboarding />, false)} />
        <Route path="dashboard" element={page(<Dashboard />)} />
        <Route path="target" element={page(<TargetPage />)} />
        <Route path="resume" element={page(<ResumePage />, false)} />
        <Route path="assessment" element={page(<AssessmentPage />)} />
        <Route path="results" element={page(<ResultsPage />)} />
        <Route path="plan" element={page(<PlanPage />)} />
        <Route path="practice" element={page(<PracticePage />)} />
        <Route path="interview" element={page(<InterviewPage />)} />
        <Route path="progress" element={page(<ProgressPage />)} />
        <Route path="resources" element={page(<ResourcesPage />)} />
        <Route path="settings" element={page(<SettingsPage />, false)} />
        <Route path="*" element={page(<NotFound />, false)} />
      </Route>
      <Route path="*" element={<Suspense fallback={null}><NotFound /></Suspense>} />
    </Routes>
  );
}
