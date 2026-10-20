"""Plan lifecycle: generate, lazy rollover, replan on new evidence, task completion (SRS FR-060–063, FR-071)."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core import scoring_config as sc
from app.core.errors import AppError, Conflict
from app.core.security import utcnow
from app.core.timeutil import user_today
from app.models import (Assessment, GapReport, LearningResource, PracticeAttempt, PreparationPlan, PreparationTask,
                        ResourceSkill, SkillGap, TargetRole, User)
from app.modules.evidence import engine
from app.modules.plans.planner import GapInput, Resource, build_plan

AUTO_TYPES = ("practice", "reassess", "assess", "interview")


def pick_resources(db: Session, user: User, wanted: dict[str, float | None]) -> dict[str, Resource | None]:
    """FR-071 for several skills at once (two queries): verified resources only; difficulty by D; free first;
    shortest that fits the learn cap; deterministic tie-break by id; skip ones used for this skill in 14 days."""
    if not wanted:
        return {}
    ids = [uuid.UUID(s) for s in wanted]
    recent = set(db.execute(select(PreparationTask.skill_id, PreparationTask.resource_id).where(
        PreparationTask.user_id == user.id, PreparationTask.task_type == "learn", PreparationTask.status == "done",
        PreparationTask.skill_id.in_(ids), PreparationTask.completed_at > utcnow() - timedelta(days=14))).all())
    rows = db.execute(select(ResourceSkill.skill_id, LearningResource)
                      .join(LearningResource, ResourceSkill.resource_id == LearningResource.id)
                      .where(ResourceSkill.skill_id.in_(ids), LearningResource.is_active,
                             LearningResource.last_verified_at.is_not(None))).all()
    out: dict[str, Resource | None] = {}
    for sid, D in wanted.items():
        cands = [r for skill_id, r in rows if str(skill_id) == sid and (skill_id, r.id) not in recent]
        if not cands:
            out[sid] = None
            continue
        want = "beginner" if (D is None or D < 0.4) else "intermediate"
        cands.sort(key=lambda r: (0 if r.difficulty == want else 1, 0 if r.is_free else 1,
                                  0 if r.est_minutes <= sc.TASK_MINUTES["learn_cap"] else 1, r.est_minutes, str(r.id)))
        out[sid] = Resource(str(cands[0].id), cands[0].title, cands[0].est_minutes)
    return out


def active_plan(db: Session, target: TargetRole) -> PreparationPlan | None:
    return db.scalar(select(PreparationPlan).where(PreparationPlan.target_id == target.id,
                                                   PreparationPlan.status == "active"))


def _has_diagnostic(db: Session, target: TargetRole) -> bool:
    return db.scalar(select(Assessment.id).where(Assessment.target_id == target.id, Assessment.kind == "diagnostic",
                                                 Assessment.status.in_(("scored", "scored_partial", "abandoned")))
                     .limit(1)) is not None


def _inputs(db: Session, user: User, target: TargetRole, report: GapReport) -> tuple[list[GapInput], GapInput | None]:
    gaps = db.scalars(select(SkillGap).where(SkillGap.gap_report_id == report.id).order_by(SkillGap.rank)).all()
    states = {s["skill_id"]: s for s in report.skill_states}
    prereq = engine.prerequisites(db)
    inputs = []
    for g in gaps:
        st = states.get(str(g.skill_id)) if g.skill_id else None
        inputs.append(GapInput(gap_type=g.gap_type, priority=g.priority_score,
                               skill_id=str(g.skill_id) if g.skill_id else None,
                               skill_slug=st["slug"] if st else None, skill_name=st["name"] if st else None,
                               importance=st["importance"] if st else "interview", D=st["D"] if st else None,
                               n=st["n"] if st else int(g.inputs.get("n", 0)), interview_dimension=g.interview_dimension,
                               prerequisite_ids=prereq.get(str(g.skill_id), set()) if g.skill_id else set()))
    core = [s for s in report.skill_states if s["importance"] == "core"]
    maint = None
    if core:
        s = sorted(core, key=lambda x: (x["n"], x["name"]))[0]
        maint = GapInput("G5", 30, s["skill_id"], s["slug"], s["name"], "core", s["D"], s["n"])
    return inputs, maint


def _completed_steps(db: Session, target: TargetRole) -> set[tuple[str, int]]:
    rows = db.execute(select(PreparationTask.sequence_key, PreparationTask.step_index)
                      .join(PreparationPlan, PreparationPlan.id == PreparationTask.plan_id)
                      .where(PreparationPlan.target_id == target.id, PreparationTask.status == "done",
                             PreparationTask.completed_at > utcnow() - timedelta(days=30))).all()
    return {(k, i) for k, i in rows}


def _insert_tasks(db: Session, plan: PreparationPlan, user: User, result) -> list[dict]:
    from app.core.db import bulk_insert
    tasks = []
    for day, items in result.days:
        for t in items:
            tasks.append({
                "id": uuid.uuid4(), "plan_id": plan.id, "user_id": user.id, "plan_revision": plan.revision,
                "scheduled_date": day, "position": t.position, "task_type": t.task_type,
                "skill_id": uuid.UUID(t.skill_id) if t.skill_id else None,
                "interview_dimension": t.interview_dimension, "gap_type": t.gap_type, "sequence_key": t.seq_key,
                "step_index": t.step_index, "resource_id": uuid.UUID(t.resource_id) if t.resource_id else None,
                "estimated_minutes": t.minutes, "priority": t.priority, "title": t.title[:150],
                "description": (t.description or "")[:400], "rationale": t.rationale[:300], "status": "pending"})
    bulk_insert(db, PreparationTask, tasks)
    return tasks


def _run_planner(db: Session, user: User, target: TargetRole, report: GapReport, today: date):
    gaps, maint = _inputs(db, user, target, report)
    resources = pick_resources(db, user, {g.skill_id: g.D for g in gaps if g.skill_id and g.gap_type == "G2"})
    return build_plan(gaps, today, target.deadline_date, target.daily_minutes, _completed_steps(db, target),
                      resources, _has_diagnostic(db, target), maint)


def generate(db: Session, user: User, target: TargetRole) -> PreparationPlan:
    today = user_today(user.timezone)
    if target.deadline_date < today:
        raise Conflict("Your deadline has passed. Set a new deadline to plan again.", code="DEADLINE_PASSED")
    existing = active_plan(db, target)
    if existing is not None:
        return replan(db, user, target, existing, "You rebuilt the plan.")
    report = engine.latest_report(db, user, target)
    result = _run_planner(db, user, target, report, today)
    plan = PreparationPlan(user_id=user.id, target_id=target.id, status="active", revision=1, start_date=today,
                           end_date=target.deadline_date, daily_minutes=target.daily_minutes,
                           horizon_days=result.horizon_days, generated_from_gap_report_id=report.id,
                           unscheduled=result.unscheduled, last_rollover_date=today,
                           change_summary=None)
    db.add(plan)
    db.flush()
    _insert_tasks(db, plan, user, result)
    db.commit()
    return plan


def replan(db: Session, user: User, target: TargetRole, plan: PreparationPlan, reason: str) -> PreparationPlan:
    """FR-063: keep history; replace pending tasks dated today or later; bump revision — atomically."""
    today = user_today(user.timezone)
    if target.deadline_date < today:
        return plan
    try:
        report = engine.latest_report(db, user, target)
        old_titles = set(db.scalars(select(PreparationTask.title).where(
            PreparationTask.plan_id == plan.id, PreparationTask.status == "pending",
            PreparationTask.scheduled_date >= today)).all())
        db.execute(delete(PreparationTask).where(PreparationTask.plan_id == plan.id,
                                                 PreparationTask.status == "pending",
                                                 PreparationTask.scheduled_date >= today))
        result = _run_planner(db, user, target, report, today)
        plan.revision += 1
        plan.start_date, plan.end_date = today, target.deadline_date
        plan.daily_minutes, plan.horizon_days = target.daily_minutes, result.horizon_days
        plan.generated_from_gap_report_id = report.id
        plan.unscheduled = result.unscheduled
        tasks = _insert_tasks(db, plan, user, result)
        new_titles = {t["title"] for t in tasks}
        added, removed = sorted(new_titles - old_titles), sorted(old_titles - new_titles)
        parts = [reason]
        if added:
            parts.append("Added: " + "; ".join(added[:4]) + ("…" if len(added) > 4 else "") + ".")
        if removed:
            parts.append("Removed: " + "; ".join(removed[:4]) + ("…" if len(removed) > 4 else "") + ".")
        plan.change_summary = " ".join(parts)[:1000]
        db.commit()
    except Exception:
        db.rollback()  # failure keeps the old pending tasks
        raise
    return plan


def replan_if_active(db: Session, user: User, target: TargetRole, reason: str) -> None:
    plan = active_plan(db, target)
    if plan is not None:
        replan(db, user, target, plan, reason)


def rollover(db: Session, user: User, target: TargetRole, plan: PreparationPlan) -> str | None:
    """FR-062: lazily mark yesterday's pending tasks missed and reschedule (idempotent per day)."""
    today = user_today(user.timezone)
    if plan.last_rollover_date == today:
        return None
    missed = db.scalars(select(PreparationTask).where(PreparationTask.plan_id == plan.id,
                                                      PreparationTask.status == "pending",
                                                      PreparationTask.scheduled_date < today)).all()
    for t in missed:
        t.status = "missed"
    plan.last_rollover_date = today
    db.commit()
    if missed:
        replan(db, user, target, plan, f"{len(missed)} task(s) from earlier days were moved to the coming days.")
        return f"{len(missed)} task(s) from earlier were moved to the coming days."
    return None


def after_gap_report(db: Session, user: User, target: TargetRole, report: GapReport) -> None:
    plan = active_plan(db, target)
    if plan is None or plan.generated_from_gap_report_id == report.id:
        return
    prev = db.get(GapReport, plan.generated_from_gap_report_id) if plan.generated_from_gap_report_id else None

    def top(rep_id) -> dict:
        rows = db.scalars(select(SkillGap).where(SkillGap.gap_report_id == rep_id).order_by(SkillGap.rank)
                          .limit(5)).all()
        return {f"{g.skill_id or g.interview_dimension}:{g.gap_type}": g.priority_score for g in rows}
    new_top = top(report.id)
    old_top = top(prev.id) if prev else {}
    changed = set(new_top) != set(old_top) or any(abs(new_top[k] - old_top[k]) >= sc.REPLAN_PRIORITY_DELTA
                                                  for k in new_top if k in old_top)
    if changed:
        replan(db, user, target, plan, "Your plan was updated with your latest results.")


def complete_linked_tasks(db: Session, user: User, target: TargetRole, task_type: str, skill_id: uuid.UUID | None,
                          entity_id: uuid.UUID, dimension: str | None = None) -> int:
    """FR-061 automatic completion. Returns number of tasks completed."""
    plan = active_plan(db, target)
    if plan is None:
        return 0
    stmt = select(PreparationTask).where(PreparationTask.plan_id == plan.id, PreparationTask.status == "pending",
                                         PreparationTask.task_type == task_type)
    if task_type in ("reassess", "practice") and skill_id is not None:
        stmt = stmt.where(PreparationTask.skill_id == skill_id)
    if task_type == "interview" and dimension:
        stmt = stmt.where((PreparationTask.interview_dimension == dimension) |
                          (PreparationTask.interview_dimension.is_(None)))
    task = db.scalar(stmt.order_by(PreparationTask.scheduled_date, PreparationTask.position).limit(1))
    if task is None:
        return 0
    if task_type == "practice":
        n = db.scalar(select(func.count()).select_from(PracticeAttempt).where(
            PracticeAttempt.user_id == user.id, PracticeAttempt.skill_id == skill_id,
            PracticeAttempt.evaluation_status.in_(("not_required", "scored")),
            PracticeAttempt.created_at >= task.created_at)) or 0
        if n < sc.PRACTICE_SET_SIZE:
            return 0
    task.status, task.completed_at, task.linked_entity_id = "done", utcnow(), entity_id
    db.commit()
    return 1


def set_task_status(db: Session, user: User, task: PreparationTask, status: str) -> PreparationTask:
    if status == "done" and task.task_type in AUTO_TYPES:
        raise AppError("This task completes automatically when you finish the linked activity.",
                       code="TASK_AUTO_COMPLETES", status_code=409)
    if status == "pending" and task.status == "missed":
        raise Conflict("Missed tasks are rescheduled automatically.", code="TASK_MISSED")
    task.status = status
    task.completed_at = utcnow() if status == "done" else None
    db.commit()
    return task
