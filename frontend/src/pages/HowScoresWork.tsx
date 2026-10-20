import { Link } from "react-router-dom";
import { Logo } from "@/components/AppShell";

export default function HowScoresWork() {
  return (
    <div className="min-h-screen bg-white">
      <header className="border-b border-line"><div className="mx-auto max-w-3xl px-4 h-16 flex items-center"><Link to="/"><Logo /></Link></div></header>
      <main className="mx-auto max-w-3xl px-4 py-10 prose-rr space-y-6">
        <h1 className="text-2xl font-semibold">How RoleReady's scores work</h1>
        <p>Every number comes from your stored evidence through a published formula. AI only extracts structure from text and
          judges free-text answers against explicit rubrics; it never decides a score or a priority on its own.</p>
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">Two separate signals per skill</h2>
          <p><b>Resume evidence (R, 0–3)</b> — what your resume shows: 0 not shown, 1 listed only, 2 used in a project or job,
            3 used in two or more entries or with a measured outcome. <b>Demonstrated ability (D, 0–100%)</b> — your
            difficulty-weighted results on assessment, practice and interview questions (the 12 most recent). Missing from your
            resume is never treated as "can't do it".</p>
        </section>
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">Requirement coverage</h2>
          <p>Coverage = 100 × Σ weight × credit ÷ Σ weight, where weight is 3 for core, 2 for required and 1 for preferred
            requirements, and credit is 0, 0.4, 0.8 or 1.0 for evidence levels 0–3. It is not an ATS score.</p>
        </section>
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">Gap priority</h2>
          <p>P = min(100, round(100 × I × S × C) + B). I is importance (core 1.0, required 0.75, preferred 0.4), S is the
            severity of the gap type, C is confidence from how many answers we have (0.7 with none up to 1.0 with six or more),
            and B adds 10 when other weak skills build on this one. Six gap types separate "resume claim at risk", "weak
            demonstrated skill", "demonstrated but not on resume", "not yet assessed", "not yet evidenced" and "interview weakness".</p>
        </section>
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">Readiness dimensions</h2>
          <p>Resume alignment, technical knowledge, problem solving, project evidence and interview communication are shown
            separately, each with a confidence badge. With no evidence a dimension shows "Not enough evidence yet" — never zero.
            An overall estimate appears only when at least three dimensions, including technical knowledge, have medium
            confidence. Weights are uncalibrated design choices.</p>
        </section>
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">Interview feedback</h2>
          <p>Relevance, correctness, completeness, reasoning and clarity are each scored 1–5 and must quote your own answer.
            A score whose quote doesn't appear in your answer is capped at 2. The overall score is the mean × 20, computed by
            RoleReady. Feedback covers content only — not tone, confidence or body language.</p>
        </section>
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">Honest comparisons</h2>
          <p>Change is shown only between checkpoints on the same skill with the same difficulty mix, and differences under
            17 points (about one question) are reported as "no clear change". Diagnostics and checkpoints are never compared
            with each other, and different interview questions are not treated as like-for-like.</p>
        </section>
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">Limitations</h2>
          <p>Small item counts make scores noisy; AI evaluation of free text can vary between runs; the question bank is
            fresher-level and general and does not reflect any employer's process. None of these numbers predicts
            shortlisting, interviews or offers.</p>
        </section>
        <p><Link to="/app/dashboard" className="text-brand-800 hover:underline">Back to RoleReady</Link></p>
      </main>
    </div>
  );
}
