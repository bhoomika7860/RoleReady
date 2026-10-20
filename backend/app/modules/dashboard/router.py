from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import current_user, owned
from app.core.timeutil import user_today
from app.models import (Assessment, InterviewSession, InterviewTurn, PracticeAttempt, Resume, ResumeAnalysis,
                        ResumeVersion, Skill, TargetRole, User)
from app.modules.assessments.service import expire_stale
from app.modules.dashboard import progress
from app.modules.dashboard.recommender import next_actions
from app.modules.evidence import engine
from app.modules.plans import service as plans
from app.modules.plans.router import plan_payload
from app.modules.targets.router import target_out
from app.modules.targets.service import active_target

router = APIRouter(tags=["dashboard"])
log = logging.getLogger("roleready.dashboard")


def _card(fn):
    try:
        return fn()
    except Exception:
        log.exception("dashboard_card_failed", extra={"card": fn.__name__})
        return {"status": "error"}


@router.get("/dashboard")
def dashboard_home(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Dashboard for the active target, or the onboarding state when there is none."""
    t = active_target(db, user)
    if t is None:
        return {"target": None, "next_action": next_actions(db, user, None), "onboarding": True}
    return _dashboard(db, user, t)


@router.get("/targets/{target_id}/dashboard")
def dashboard(target_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _dashboard(db, user, owned(db, TargetRole, target_id, user.id))


def _dashboard(db: Session, user: User, t: TargetRole) -> dict:
    today = user_today(user.timezone)
    expire_stale(db, user)
    plan = plans.active_plan(db, t)
    banner = None
    if plan is not None:
        try:
            banner = plans.rollover(db, user, t, plan)
        except Exception:
            db.rollback()
    report = engine.latest_report(db, user, t)
    gaps = engine.report_payload(db, report)

    def coverage():
        resume = engine.primary_resume(db, user.id)
        if resume is None:
            return {"status": "empty"}
        a = engine.latest_analysis(db, user.id, t.id)
        if a is None:
            return {"status": "not_analysed", "resume_id": str(resume.id)}
        return {"status": "ok", "resume_id": str(resume.id), "score": a.coverage_score, "counts": a.result["counts"],
                "stale": a.resume_version_id != resume.current_version_id, "reviewed": resume.reviewed_at is not None,
                "date": a.created_at.isoformat()}

    def plan_card():
        if plan is None:
            return {"status": "empty"}
        p = plan_payload(db, user, db.get(type(plan), plan.id), banner)
        today_tasks = next((d["tasks"] for d in p["days"] if d["date"] == today.isoformat()), [])
        overdue = [x for x in p["history"] if x["status"] == "missed"][-3:]
        return {"status": "ok", "plan_id": p["plan_id"], "today": today_tasks, "progress": p["progress"],
                "banner": banner, "change_summary": p["change_summary"], "overdue": overdue,
                "unscheduled": len(p["unscheduled"])}

    def latest_assessment():
        a = db.scalar(select(Assessment).where(Assessment.target_id == t.id,
                                               Assessment.status.in_(("scored", "scored_partial")))
                      .order_by(Assessment.scored_at.desc()).limit(1))
        if a is None:
            return {"status": "empty"}
        skill = db.get(Skill, a.skill_id) if a.skill_id else None
        return {"status": "ok", "id": str(a.id), "kind": a.kind, "skill": skill.name if skill else None,
                "score": round(float(a.score) * 100) if a.score is not None else None, "items_scored": a.items_scored,
                "items_total": a.items_total, "date": a.scored_at.isoformat(), "partial": a.status == "scored_partial"}

    def interview():
        turns = db.scalars(select(InterviewTurn).join(InterviewSession, InterviewSession.id ==
                                                      InterviewTurn.session_id)
                           .where(InterviewSession.target_id == t.id, InterviewTurn.user_id == user.id,
                                  InterviewTurn.evaluation_status == "scored")
                           .order_by(InterviewTurn.answered_at.desc()).limit(5)).all()
        if not turns:
            return {"status": "empty"}
        dims = {d: round(sum(x.rubric_scores[d]["score"] for x in turns) / len(turns), 1)
                for d in turns[0].rubric_scores}
        return {"status": "ok", "mean_overall": round(sum(x.overall_score for x in turns) / len(turns)),
                "answers": len(turns), "weakest_dimension": min(dims, key=dims.get), "dimensions": dims,
                "last_date": turns[0].answered_at.isoformat()}

    def recent_activity():
        events = []
        for a in db.scalars(select(Assessment).where(Assessment.target_id == t.id, Assessment.scored_at.is_not(None))
                            .order_by(Assessment.scored_at.desc()).limit(5)):
            events.append({"type": "assessment", "date": a.scored_at.isoformat(),
                           "text": f"{a.kind.capitalize()} scored: {round(float(a.score) * 100) if a.score is not None else '—'}%"})
        for p in db.scalars(select(PracticeAttempt).where(PracticeAttempt.target_id == t.id,
                                                          PracticeAttempt.user_id == user.id)
                            .order_by(PracticeAttempt.created_at.desc()).limit(5)):
            events.append({"type": "practice", "date": p.created_at.isoformat(),
                           "text": "Practice answer " + ("correct" if p.is_correct else "reviewed" if p.is_correct is
                                                         not None else "saved")})
        for x in db.scalars(select(InterviewTurn).join(InterviewSession, InterviewSession.id ==
                                                       InterviewTurn.session_id)
                            .where(InterviewSession.target_id == t.id, InterviewTurn.answered_at.is_not(None))
                            .order_by(InterviewTurn.answered_at.desc()).limit(5)):
            events.append({"type": "interview", "date": x.answered_at.isoformat(),
                           "text": f"Interview answer {'scored ' + str(x.overall_score) if x.overall_score is not None else x.evaluation_status.replace('_', ' ')}"})
        for v in db.scalars(select(ResumeVersion).join(Resume, Resume.id == ResumeVersion.resume_id)
                            .where(Resume.user_id == user.id).order_by(ResumeVersion.created_at.desc()).limit(5)):
            events.append({"type": "resume", "date": v.created_at.isoformat(),
                           "text": f"Resume v{v.version_number}: {v.change_summary or 'saved'}"})
        events.sort(key=lambda e: e["date"], reverse=True)
        return events[:10]

    def skill_progress():
        return [s for s in progress.skill_series(db, user, t) if any(p["kind"] == "checkpoint" for p in s["series"])]

    return {
        "target": target_out(db, t, today),
        "next_action": _card(lambda: next_actions(db, user, t)),
        "readiness": {"dimensions": gaps["dimension_scores"], "index": None if report.readiness_index is None else {
            "score": report.readiness_index, "band": engine._band(report.readiness_index)},
            "note": "Estimates from your evidence so far — not a prediction of interviews or offers."},
        "top_gaps": gaps["gaps"][:3], "gap_count": len(gaps["gaps"]),
        "strengths": gaps["strengths"], "not_assessed": gaps["not_assessed"],
        "coverage": _card(coverage), "plan": _card(plan_card), "latest_assessment": _card(latest_assessment),
        "interview": _card(interview), "skill_progress": _card(skill_progress),
        "recent_activity": _card(recent_activity), "computed_at": report.created_at.isoformat(),
    }


@router.get("/targets/{target_id}/progress")
def progress_view(target_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = owned(db, TargetRole, target_id, user.id)
    return {"skills": progress.skill_series(db, user, t), "interview_retries": progress.interview_retries(db, user, t),
            "interview_trend": progress.interview_trend(db, user, t),
            "coverage": progress.coverage_history(db, user, t),
            "rules": "Changes are shown only between checkpoints on the same skill with the same difficulty mix; "
                     "changes smaller than 17 points are reported as 'No clear change'. Interview sessions on "
                     "different questions are not compared."}


@router.get("/targets/{target_id}/recommendations/next")
def recommendation(target_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return next_actions(db, user, owned(db, TargetRole, target_id, user.id))


__all__ = ["router", "ResumeAnalysis"]
