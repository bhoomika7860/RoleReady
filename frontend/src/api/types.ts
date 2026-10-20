/* Response shapes used by the UI (mirrors backend payloads). */

export type User = {
  id: string; identifier: string; identifier_kind: "email" | "username"; preferred_name: string | null;
  experience_level: string | null; timezone: string; onboarding_step: number; onboarding_completed: boolean;
  is_demo: boolean;
};
export type Me = { user: User; active_target_id: string | null; auth_mode: string };
export type LoginOut = Me & { is_new_user: boolean; redirect_to: string };

export type SkillRef = { slug: string; name: string };
export type Role = { slug: string; name: string; description: string; top_skills: (SkillRef & { category: string })[];
  dimensions: string[] };

export type Requirement = {
  id: string; skill: SkillRef | null; raw_phrase: string; category: "skill" | "experience" | "education" | "other";
  requirement_level: "required" | "preferred"; importance: "core" | "required" | "preferred";
  origin: "role_default" | "jd_extracted" | "user_added"; evidence_snippet: string | null; is_inferred: boolean;
  scored: boolean;
};
export type RequirementsPayload = { requirements: Requirement[]; confirmed_at: string | null; updated_at: string };

export type Target = {
  id: string; role: SkillRef; job_title: string; company_name: string | null; deadline_date: string;
  days_to_deadline: number; deadline_passed: boolean; daily_minutes: number; status: string;
  requirements_confirmed_at: string | null; updated_at: string; company_notice: string | null;
  job_description: null | { id: string; status: string; text: string; analysis: Record<string, string[]>;
    warnings: string[]; created_at: string; model: string | null };
};

export type Bullet = { id?: string; text: string };
export type ResumeContent = {
  schema_version?: number;
  header: { full_name: string; email?: string | null; phone?: string | null; location?: string | null;
    links?: { label: string; url: string }[] };
  summary?: string | null;
  education: { id?: string; institution: string; degree?: string | null; field?: string | null; start?: string | null;
    end?: string | null; score?: string | null; details?: string[] }[];
  skills: { id?: string; name: string; skill_slug?: string | null; category?: string | null }[];
  experience: { id?: string; title: string; organization?: string | null; location?: string | null;
    start?: string | null; end?: string | null; is_current?: boolean; technologies: string[]; bullets: Bullet[] }[];
  projects: { id?: string; name: string; role?: string | null; link?: string | null; start?: string | null;
    end?: string | null; technologies: string[]; bullets: Bullet[] }[];
  certifications: { id?: string; name: string; issuer?: string | null; date?: string | null }[];
  achievements: { id?: string; text: string }[];
  section_order?: string[];
};
export type ResumeVersion = { id: string; version_number: number; created_by: string; change_summary: string | null;
  created_at: string; content: ResumeContent };
export type Resume = { id: string; title: string; source: string; original_filename: string | null;
  extraction_status: string; reviewed_at: string | null; updated_at: string; created_at: string;
  current_version: ResumeVersion | null; raw_text?: string | null };

export type CoverageRow = {
  requirement_id: string; skill: SkillRef | null; raw_phrase: string; importance: string; origin: string;
  level: 0 | 1 | 2 | 3; state: "evidenced" | "weak" | "not_shown"; label: string; explanation: string;
  locations: { section: string; entry_id: string | null; bullet_id: string | null; entry_name: string | null;
    text: string }[];
  suggestion: { type: string; text: string } | null;
};
export type Analysis = { id: string; coverage_score: number; pe_score: number | null; requirements: CoverageRow[];
  counts: Record<string, number>; formula: string; created_at: string; stale: boolean;
  requirements_changed: boolean; disclaimer: string; warnings?: string[]; pe_inputs?: Record<string, number> };

export type Suggestion = { id: string; status: string; original: string; suggested: string | null;
  rationale: string | null; facts_used: string[]; guard_report: { ok: boolean; violations: string[] };
  questions: { id: string; text: string }[]; user_answers: { question_id: string; answer: string }[];
  bullet_ref: { section: string; entry_id: string; bullet_id: string } };

export type AssessmentItem = { position: number; question_id: string; type: string; difficulty: string;
  skill: SkillRef; topic: string; prompt: string; options: { id: string; text: string }[] | null;
  source_label: string; response: any; answered: boolean };
export type AssessmentSummary = { id: string; kind: "diagnostic" | "checkpoint"; status: string; target_id: string;
  skill: SkillRef | null; score: number | null; items_total: number; items_scored: number; created_at: string;
  expires_at: string; submitted_at: string | null; scored_at: string | null; includes_repeats: boolean;
  difficulty_mix: Record<string, number> | null; scoring_version: string };
export type AssessmentState = AssessmentSummary & { items: AssessmentItem[]; first_unanswered: number | null;
  blueprint: Record<string, any> };

export type DimensionScore = { score: number | null; confidence: "none" | "low" | "medium" | "high"; basis: string;
  name: string; weight: number | null };
export type Gap = { id: string; type: string; label: string; skill: SkillRef | null; interview_dimension: string | null;
  importance: string; priority: number; rank: number; inputs: Record<string, any>; explanation: string;
  adjustments: string[]; next_action: { type: string; label: string; skill: string | null; deep_link: string };
  resume_state: string | null; demonstrated_state: string | null };
export type SkillState = { skill_id: string; slug: string; name: string; importance: string; R: number | null;
  D: number | null; n: number; confidence: string; sources: Record<string, number>; resume_state: string;
  demonstrated_state: string; demonstrated_source: string | null };
export type GapReport = { report_id: string; created_at: string; gaps: Gap[]; resolved: { name: string; text: string }[];
  skill_states: SkillState[]; strengths: SkillState[]; not_assessed: SkillState[]; unassessable_skills: string[];
  dimension_scores: Record<string, DimensionScore>; readiness_index: number | null; formula: string; disclaimer: string };

export type Task = { id: string; date: string; type: string; title: string; description: string | null;
  rationale: string; minutes: number; priority: number; status: string; gap_type: string | null;
  skill: SkillRef | null; interview_dimension: string | null; auto_completes: boolean;
  resource: null | { id: string; title: string; url: string; provider: string; format: string; minutes: number;
    is_free: boolean; last_verified_at: string | null };
  link: string; external: boolean; completed_at: string | null };
export type Plan = { plan_id: string; revision: number; start_date: string; end_date: string; daily_minutes: number;
  horizon_days: number; change_summary: string | null; banner: string | null; today: string;
  days: { date: string; total_minutes: number; tasks: Task[] }[]; history: Task[];
  unscheduled: { skill: string; gap_type: string | null; priority: number; reason: string; task?: string }[];
  progress: { done: number; missed: number; pending_due: number; total: number; pct: number | null } };

export type Recommendation = { action_type: string; title: string; why: string; based_on: string[]; deep_link: string;
  minutes: number; skill: SkillRef | null; score_breakdown: { rule: string; base: number; adjustments: string[];
    score: number } };
export type NextActions = { primary: Recommendation | null; alternatives: Recommendation[]; mode: string;
  remaining_minutes_today?: number };

export type RubricScore = { score: number; quote: string | null; quote_verified: boolean; comment: string;
  note: string | null };
export type Turn = { id: string; sequence: number; question_text: string; source_label: string;
  attempt_number: number; parent_turn_id: string | null; answer_text: string | null; input_mode: string;
  answered_at: string | null; evaluation_status: string; rubric_scores: Record<string, RubricScore> | null;
  overall_score: number | null; feedback: any; delta: null | { overall: number; dimensions: Record<string, number>;
    previous_overall: number; note: string }; disclaimer: string; guidance: string };
export type InterviewSession = { id: string; type: string; status: string; skill: SkillRef | null;
  max_questions: number; rubric_version: string; created_at: string; ended_at: string | null; summary: any;
  questions_asked: number; mean_overall: number | null; turns?: Turn[] };

export type ResourceItem = { id: string; title: string; url: string; provider: string; format: string;
  difficulty: string; minutes: number; is_free: boolean; description: string | null; last_verified_at: string;
  verification_note: string | null; skills: { slug: string; name: string; topic: string | null;
    gap_priority: number | null }[]; relevance: number };
