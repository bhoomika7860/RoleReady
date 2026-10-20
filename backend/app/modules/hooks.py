"""Cross-module reactions to state changes (kept in one place to avoid import cycles).

requirements/resume change → coverage analysis → evidence → gap report → (maybe) replan
assessment/practice/interview scored → evidence → gap report → task auto-completion → (maybe) replan
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models import GapReport, Resume, TargetRole, User

log = logging.getLogger("roleready.hooks")


def _active_target(db: Session, user: User) -> TargetRole | None:
    from app.modules.targets.service import active_target
    return active_target(db, user)


def evidence_changed(db: Session, user: User, target: TargetRole, trigger: str) -> GapReport:
    from app.modules.evidence.engine import recompute
    from app.modules.plans.service import after_gap_report
    report = recompute(db, user, target, trigger)
    try:
        after_gap_report(db, user, target, report)
    except Exception:  # planning must never block evidence from being recorded
        db.rollback()
        log.exception("replan_after_gap_report_failed")
    return report


def requirements_changed(db: Session, user: User, target: TargetRole, trigger: str) -> None:
    from app.modules.evidence.engine import primary_resume
    from app.modules.resumes.coverage import run_analysis
    resume = primary_resume(db, user.id)
    if resume is not None and resume.current_version_id is not None:
        run_analysis(db, user.id, target, resume)
    evidence_changed(db, user, target, trigger)


def resume_changed(db: Session, user: User, resume: Resume) -> None:
    from app.modules.resumes.coverage import run_analysis
    target = _active_target(db, user)
    if target is None or resume.current_version_id is None:
        return
    run_analysis(db, user.id, target, resume)
    evidence_changed(db, user, target, "resume_analysis")


def resume_deleted(db: Session, user: User) -> None:
    target = _active_target(db, user)
    if target is not None:
        requirements_changed(db, user, target, "resume_deleted")
