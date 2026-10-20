"""Deterministic next-best-action engine (SRS 5.11). Same state → same recommendation; no LLM."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import scoring_config as sc
from app.core.security import utcnow
from app.core.timeutil import user_today
from app.models import (Assessment, AssessmentItem, InterviewTurn, PracticeAttempt, PreparationPlan,
                        PreparationTask, Resume, ResumeAnalysis, Skill, SkillEvidence, SkillGap, TargetRole, User)
from app.modules.evidence.engine import latest_report, primary_resume

RULE_ORDER = {"R1": 0, "R2": 1, "R4": 2, "R5": 3, "R3": 4, "FB": 5, "R6": 6, "R7": 7}
MINUTES = {"take_diagnostic": 25, "resume_assessment": 15, "reassess": 15, "practice": 25, "learn": 30,
           "interview": 20, "improve_resume": 15, "rerun_analysis": 2, "retry_evaluation": 2, "add_resume": 15,
           "review_resume": 10, "set_target": 5, "confirm_requirements": 5}


@dataclass
class Candidate:
    action_type: str
    rule: str
    base: int
    title: str
    why: str
    deep_link: str
    skill_slug: str | None = None
    skill_name: str | None = None
    based_on: list[str] = field(default_factory=list)
    minutes: int = 15
    adjustments: list[str] = field(default_factory=list)
    score: int = 0
    excluded: bool = False

    def out(self) -> dict:
        return {"action_type": self.action_type, "title": self.title, "why": self.why, "based_on": self.based_on,
                "deep_link": self.deep_link, "minutes": self.minutes,
                "skill": {"slug": self.skill_slug, "name": self.skill_name} if self.skill_slug else None,
                "score_breakdown": {"rule": self.rule, "base": self.base, "adjustments": self.adjustments,
                                    "score": self.score}}


def _c(action: str, rule: str, base: int, title: str, why: str, link: str, slug=None, name=None, based_on=None,
       minutes=None) -> Candidate:
    return Candidate(action, rule, base, title, why, link, slug, name, based_on or [],
                     minutes if minutes is not None else MINUTES.get(action, 15))


def onboarding_ladder(db: Session, user: User, target: TargetRole | None) -> tuple[Candidate | None, list[Candidate]]:
    alts: list[Candidate] = []
    if target is None:
        return _c("set_target", "R1", 100, "Choose your target role",
                  "Everything RoleReady recommends is measured against a specific job.", "/app/onboarding"), alts
    resume = primary_resume(db, user.id)
    if resume is None:
        alts.append(_c("add_resume", "R1", 60, "Add your resume",
                       "Upload, paste or build a resume so we can check which requirements it shows.",
                       "/app/resume", based_on=["No resume yet"]))
    if target.requirements_confirmed_at is None:
        return _c("confirm_requirements", "R1", 100, "Confirm your job requirements",
                  "Check the requirement list so coverage and gaps are measured against the right skills.",
                  "/app/target", based_on=["Requirements not yet confirmed"]), alts
    in_progress = db.scalar(select(Assessment).where(Assessment.target_id == target.id, Assessment.kind == "diagnostic",
                                                     Assessment.status == "in_progress"))
    done = db.scalar(select(Assessment.id).where(Assessment.target_id == target.id, Assessment.kind == "diagnostic",
                                                 Assessment.status.in_(("scored", "scored_partial", "abandoned")))
                     .limit(1))
    if done is None:
        if in_progress is not None:
            return _c("resume_assessment", "R1", 100, "Finish your diagnostic assessment",
                      "Your answers are saved — pick up where you left off.", "/app/assessment",
                      based_on=["Diagnostic in progress"]), alts
        return _c("take_diagnostic", "R1", 100, "Take your diagnostic assessment",
                  "15 questions (~20 minutes) measure where you stand on this role's most important skills.",
                  "/app/assessment", based_on=["No diagnostic yet"]), alts
    if resume is not None and resume.reviewed_at is None:
        return _c("review_resume", "R1", 100, "Review your parsed resume",
                  "Nothing on your resume is treated as fact until you've checked the extracted sections.",
                  "/app/resume", based_on=["Resume imported but not reviewed"]), alts
    return None, alts


def _since_last_assessment(db: Session, user: User, skill_id: uuid.UUID) -> tuple[int, object]:
    last = db.scalar(select(func.max(Assessment.scored_at)).join(AssessmentItem, AssessmentItem.assessment_id ==
                                                                 Assessment.id)
                     .where(Assessment.user_id == user.id, AssessmentItem.skill_id == skill_id,
                            Assessment.status.in_(("scored", "scored_partial"))))
    stmt = select(func.count(), func.min(PracticeAttempt.created_at)).where(
        PracticeAttempt.user_id == user.id, PracticeAttempt.skill_id == skill_id,
        PracticeAttempt.evaluation_status.in_(("not_required", "scored")))
    if last:
        stmt = stmt.where(PracticeAttempt.created_at > last)
    n, first = db.execute(stmt).one()
    return n or 0, first


class _Activity:
    """Per-skill activity loaded in a few batched queries (avoids one query per skill)."""

    def __init__(self, db: Session, user: User, now):
        self.last_assess = dict(db.execute(
            select(AssessmentItem.skill_id, func.max(Assessment.scored_at))
            .join(Assessment, Assessment.id == AssessmentItem.assessment_id)
            .where(Assessment.user_id == user.id, Assessment.status.in_(("scored", "scored_partial")))
            .group_by(AssessmentItem.skill_id)).all())
        self.practice = db.execute(select(PracticeAttempt.skill_id, PracticeAttempt.created_at).where(
            PracticeAttempt.user_id == user.id, PracticeAttempt.evaluation_status.in_(("not_required", "scored")),
            PracticeAttempt.created_at > now - timedelta(days=120))).all()
        self.learn_done = set(db.scalars(select(PreparationTask.skill_id).where(
            PreparationTask.user_id == user.id, PreparationTask.task_type == "learn",
            PreparationTask.status == "done")).all())
        self.recent_checkpoints = set(db.scalars(select(Assessment.skill_id).where(
            Assessment.user_id == user.id, Assessment.skill_id.is_not(None),
            Assessment.status.in_(("scored", "scored_partial")),
            Assessment.scored_at > now - timedelta(hours=12))).all())

    def since_last(self, skill_id) -> tuple[int, object]:
        last = self.last_assess.get(skill_id)
        ts = [c for s, c in self.practice if s == skill_id and (last is None or c > last)]
        return len(ts), (min(ts) if ts else None)

    def practice_after(self, skill_id, cut) -> int:
        return sum(1 for s, c in self.practice if s == skill_id and c > cut)


def next_actions(db: Session, user: User, target: TargetRole | None) -> dict:
    primary, alts = onboarding_ladder(db, user, target)
    if primary is not None:
        primary.score = primary.base
        return {"primary": primary.out(), "alternatives": [a.out() for a in alts[:3]], "mode": "onboarding"}
    assert target is not None
    now = utcnow()
    today = user_today(user.timezone)
    cands: list[Candidate] = []
    activity = _Activity(db, user, now)

    # R2 unfinished work
    ip = db.scalar(select(Assessment).where(Assessment.target_id == target.id, Assessment.status == "in_progress",
                                            Assessment.expires_at > now).order_by(Assessment.created_at.desc()).limit(1))
    if ip is not None:
        label = "diagnostic" if ip.kind == "diagnostic" else "checkpoint"
        cands.append(_c("resume_assessment", "R2", 95, f"Finish your {label}",
                        "Your answers are saved — finishing it updates your gaps and plan.",
                        f"/app/assessment?id={ip.id}", based_on=[f"{label.capitalize()} started "
                                                                 f"{ip.created_at.date().isoformat()}"]))
    failed_items = db.scalar(select(func.count()).select_from(AssessmentItem).where(
        AssessmentItem.user_id == user.id, AssessmentItem.evaluation_status == "failed")) or 0
    failed_turns = db.scalar(select(func.count()).select_from(InterviewTurn).where(
        InterviewTurn.user_id == user.id, InterviewTurn.evaluation_status == "failed")) or 0
    if failed_items or failed_turns:
        link = "/app/results" if failed_items else "/app/interview"
        cands.append(_c("retry_evaluation", "R2", 60, "Retry feedback that couldn't be generated",
                        "Some answers are saved but weren't evaluated because the AI service failed. They don't count "
                        "against you.", link, based_on=[f"{failed_items + failed_turns} answer(s) awaiting evaluation"]))

    report = latest_report(db, user, target)
    gaps = db.scalars(select(SkillGap).where(SkillGap.gap_report_id == report.id).order_by(SkillGap.rank)).all()
    states = {s["skill_id"]: s for s in report.skill_states}
    from app.modules.catalog.cache import catalog
    skills = catalog(db).skills_by_id

    # R3 gap actions
    for g in gaps:
        st = states.get(str(g.skill_id)) if g.skill_id else None
        act = g.next_action
        slug = act.get("skill")
        sk = next((s for s in skills.values() if s.slug == slug), None) if slug else None
        name = sk.name if sk else (st["name"] if st else g.interview_dimension)
        based = [g.explanation.get("label", "")]
        if st and st["n"]:
            based.append(f"Your recent {name} answers: {round((st['D'] or 0) * 100)}% over {st['n']} questions")
        if st and st["resume_state"] != "no_resume":
            based.append({"evidenced": "Resume shows it in use", "weak": "Resume only lists it",
                          "not_shown": "Not shown on your resume"}.get(st["resume_state"], ""))
        a = act["type"]
        if a == "learn" and sk is not None:
            n_practice, _ = activity.since_last(sk.id)
            if sk.id in activity.learn_done or n_practice:
                a = "practice"
        title, why = {
            "learn": (f"Review {name}", f"{name} is a {st['importance'] if st else ''} requirement and your recent "
                                        f"answers suggest it needs work. Start with a short, verified resource."),
            "practice": (f"Practise {name} (25 min)", f"{name} is a {st['importance'] if st else ''} requirement and "
                                                     f"your recent answers averaged "
                                                     f"{round(((st or {}).get('D') or 0) * 100)}%. A checkpoint "
                                                     f"follows practice."),
            "reassess": (f"Take a 6-question {name} checkpoint", f"{name} hasn't been measured enough yet — a short "
                                                                f"checkpoint shows where you stand."),
            "improve_resume": (f"Add {name} evidence to your resume", f"Your answers show strong {name}, but your "
                                                                      f"resume doesn't show it in use. If you have "
                                                                      f"used it, add it."),
            "interview": (f"Mock interview: work on {g.interview_dimension or name}",
                          g.explanation.get("text", "")[:200]),
        }.get(a, (act.get("label", "Next step"), g.explanation.get("text", "")[:200]))
        link = {"learn": f"/app/resources?skill={slug}", "practice": f"/app/practice?skill={slug}",
                "reassess": f"/app/assessment?checkpoint={slug}", "improve_resume": "/app/resume?tab=match",
                "interview": f"/app/interview?focus={g.interview_dimension or ''}"}.get(a, act.get("deep_link", "/"))
        cands.append(_c(a, "R3", g.priority_score, title, why.strip(), link, slug, name, [b for b in based if b]))

    # R4 due plan tasks
    plan = db.scalar(select(PreparationPlan).where(PreparationPlan.target_id == target.id,
                                                   PreparationPlan.status == "active"))
    if plan is not None:
        due = db.scalars(select(PreparationTask).where(PreparationTask.plan_id == plan.id,
                                                       PreparationTask.status == "pending",
                                                       PreparationTask.scheduled_date <= today)
                         .order_by(PreparationTask.scheduled_date, PreparationTask.position)).all()
        for t in due:
            sk = skills.get(t.skill_id)
            base = (t.priority + 10) if t.gap_type else 40
            overdue = t.scheduled_date < today
            action = {"assess": "take_diagnostic", "learn": "learn", "practice": "practice", "reassess": "reassess",
                      "resume": "improve_resume", "interview": "interview"}[t.task_type]
            link = {"take_diagnostic": "/app/assessment", "learn": "/app/plan", "practice":
                    f"/app/practice?skill={sk.slug if sk else ''}&task={t.id}",
                    "reassess": f"/app/assessment?checkpoint={sk.slug if sk else ''}",
                    "improve_resume": "/app/resume?tab=match",
                    "interview": f"/app/interview?focus={t.interview_dimension or ''}"}[action]
            cands.append(_c(action, "R4", min(100, base), ("Overdue: " if overdue else "") + t.title,
                            t.rationale, link, sk.slug if sk else None, sk.name if sk else None,
                            [f"Plan task for {t.scheduled_date.isoformat()}"], t.estimated_minutes))

    # R5 ready to re-measure
    gap_prio = {str(g.skill_id): g.priority_score for g in gaps if g.skill_id}
    for sid, st in states.items():
        n_practice, first = activity.since_last(uuid.UUID(sid))
        if n_practice >= sc.READY_TO_REASSESS_PRACTICE and first and first <= now - timedelta(days=1):
            cands.append(_c("reassess", "R5", min(100, gap_prio.get(sid, 25) + 15),
                            f"Take a 6-question {st['name']} checkpoint",
                            f"You've completed {n_practice} {st['name']} practice questions since your last "
                            f"measurement; a checkpoint will show whether your score has changed.",
                            f"/app/assessment?checkpoint={st['slug']}", st["slug"], st["name"],
                            [f"{n_practice} practice answers since last checkpoint"]))

    # R6 stale analysis
    resume = primary_resume(db, user.id)
    if resume is not None and resume.current_version_id:
        latest = db.scalar(select(ResumeAnalysis).where(ResumeAnalysis.resume_id == resume.id,
                                                        ResumeAnalysis.target_id == target.id)
                           .order_by(ResumeAnalysis.created_at.desc()).limit(1))
        if latest is None or latest.resume_version_id != resume.current_version_id:
            cands.append(_c("rerun_analysis", "R6", 50, "Re-run your resume analysis",
                            "Your resume changed since it was last compared with this job.", "/app/resume?tab=match",
                            based_on=["Resume edited after the last analysis"]))
    elif resume is None:
        cands.append(_c("add_resume", "R6", 45, "Add your resume",
                        "Upload, paste or build a resume so we can check which requirements it shows.", "/app/resume",
                        based_on=["No resume yet"]))

    # R7 maintenance and the insufficient-evidence fallback
    if not gaps:
        core = sorted([s for s in states.values() if s["importance"] == "core"], key=lambda s: (s["n"], s["name"]))
        if core:
            s = core[0]
            cands.append(_c("reassess", "R7", 30, f"Keep {s['name']} measured: take a checkpoint",
                            "No open gaps right now — re-measuring your least-measured core skill keeps your evidence "
                            "current.", f"/app/assessment?checkpoint={s['slug']}", s["slug"], s["name"]))
        else:
            cands.append(_c("interview", "R7", 30, "Practise a project interview",
                            "No open gaps — rehearse explaining your own projects.", "/app/interview"))
    total_ev = db.scalar(select(func.count()).select_from(SkillEvidence).where(
        SkillEvidence.user_id == user.id, SkillEvidence.source_type != "resume")) or 0
    if total_ev < 5:
        unassessed = [s for s in states.values() if s["n"] == 0 and s["importance"] == "core"]
        if unassessed:
            s = unassessed[0]
            cands.append(_c("reassess", "FB", 85, f"Measure {s['name']} with a checkpoint",
                            f"There's very little evidence about {s['name']} yet, and it's a core requirement.",
                            f"/app/assessment?checkpoint={s['slug']}", s["slug"], s["name"],
                            ["Fewer than 5 measured answers so far"]))

    # adjustments
    best: dict[tuple, Candidate] = {}
    for c in cands:
        key = (c.action_type, c.skill_slug)
        if key not in best or c.base > best[key].base:
            best[key] = c
    cands = list(best.values())
    done_minutes = db.scalar(select(func.coalesce(func.sum(PreparationTask.estimated_minutes), 0)).where(
        PreparationTask.user_id == user.id, PreparationTask.status == "done",
        PreparationTask.completed_at >= now - timedelta(hours=24))) or 0
    remaining = max(0, target.daily_minutes - int(done_minutes))
    recent_cut = now - timedelta(hours=12)
    for c in cands:
        c.score = c.base
        if c.rule != "R4" and c.skill_slug and c.action_type in ("reassess", "practice"):
            sk = catalog(db).skills_by_slug.get(c.skill_slug)
            if sk is not None:
                if c.action_type == "reassess":
                    recent = sk.id in activity.recent_checkpoints
                else:
                    recent = activity.practice_after(sk.id, recent_cut) >= sc.PRACTICE_SET_SIZE * 2
                if recent:
                    c.excluded = True
                    c.adjustments.append("Done in the last 12 hours")
        if c.minutes > remaining and c.rule not in ("R1", "R2"):
            c.score -= 10
            c.adjustments.append("−10: longer than your remaining study time today")
    ranked = sorted([c for c in cands if not c.excluded],
                    key=lambda c: (-c.score, RULE_ORDER[c.rule], c.skill_name or "", c.title))
    if not ranked:
        return {"primary": None, "alternatives": [], "mode": "empty"}
    primary = ranked[0]
    alternatives = [c for c in ranked[1:] if (c.action_type, c.skill_slug) != (primary.action_type, primary.skill_slug)]
    alt_out = [a.out() for a in (alternatives + alts)[:3]]
    return {"primary": primary.out(), "alternatives": alt_out, "mode": "evidence",
            "remaining_minutes_today": remaining}


def resume_reviewed(resume: Resume | None) -> bool:
    return bool(resume and resume.reviewed_at)
