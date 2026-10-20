from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import current_user, owned
from app.core.errors import NotFound
from app.core.timeutil import user_today
from app.models import LearningResource, PreparationPlan, PreparationTask, Skill, TargetRole, User
from app.modules.catalog.cache import catalog
from app.modules.plans import service

router = APIRouter(tags=["plans"])


class TaskPatch(BaseModel):
    status: str = Field(pattern="^(done|skipped|pending)$")


def task_out(t: PreparationTask, skills: dict, resources: dict) -> dict:
    s = skills.get(t.skill_id)
    r = resources.get(t.resource_id)
    link = {"assess": "/app/assessment", "reassess": f"/app/assessment?checkpoint={s.slug if s else ''}",
            "practice": f"/app/practice?skill={s.slug if s else ''}&task={t.id}",
            "interview": f"/app/interview?focus={t.interview_dimension or ''}&skill={s.slug if s else ''}",
            "resume": "/app/resume?tab=match", "learn": r.url if r else "/app/resources"}[t.task_type]
    return {"id": str(t.id), "date": t.scheduled_date.isoformat(), "position": t.position, "type": t.task_type,
            "title": t.title, "description": t.description, "rationale": t.rationale, "minutes": t.estimated_minutes,
            "priority": t.priority, "status": t.status, "gap_type": t.gap_type,
            "skill": {"slug": s.slug, "name": s.name} if s else None, "interview_dimension": t.interview_dimension,
            "auto_completes": t.task_type in service.AUTO_TYPES,
            "resource": None if r is None else {"id": str(r.id), "title": r.title, "url": r.url, "provider": r.provider,
                                                "format": r.format, "minutes": r.est_minutes, "is_free": r.is_free,
                                                "last_verified_at": r.last_verified_at.isoformat()
                                                if r.last_verified_at else None},
            "link": link, "external": t.task_type == "learn" and r is not None,
            "completed_at": t.completed_at.isoformat() if t.completed_at else None}


def plan_payload(db: Session, user: User, plan: PreparationPlan, banner: str | None = None) -> dict:
    today = user_today(user.timezone)
    tasks = db.scalars(select(PreparationTask).where(PreparationTask.plan_id == plan.id)
                       .order_by(PreparationTask.scheduled_date, PreparationTask.position)).all()
    skills = catalog(db).skills_by_id
    res_ids = {t.resource_id for t in tasks if t.resource_id}
    resources = {r.id: r for r in db.scalars(select(LearningResource).where(LearningResource.id.in_(res_ids)))} \
        if res_ids else {}
    by_day: dict[str, list] = defaultdict(list)
    history = []
    for t in tasks:
        out = task_out(t, skills, resources)
        if t.status in ("missed",) or (t.status != "pending" and t.scheduled_date < today):
            history.append(out)
        else:
            by_day[out["date"]].append(out)
    done = sum(1 for t in tasks if t.status == "done")
    missed = sum(1 for t in tasks if t.status == "missed")
    pending_due = sum(1 for t in tasks if t.status == "pending" and t.scheduled_date <= today)
    denom = done + missed + pending_due
    days = [{"date": d, "total_minutes": sum(x["minutes"] for x in items if x["status"] != "skipped"),
             "tasks": items} for d, items in sorted(by_day.items())]
    return {"plan_id": str(plan.id), "revision": plan.revision, "start_date": plan.start_date.isoformat(),
            "end_date": plan.end_date.isoformat(), "daily_minutes": plan.daily_minutes,
            "horizon_days": plan.horizon_days, "change_summary": plan.change_summary, "banner": banner,
            "today": today.isoformat(), "days": days, "history": history[-30:], "unscheduled": plan.unscheduled,
            "progress": {"done": done, "missed": missed, "pending_due": pending_due,
                         "total": len(tasks), "pct": round(100 * done / denom) if denom else None}}


@router.post("/targets/{target_id}/plans", status_code=201)
def generate(target_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = owned(db, TargetRole, target_id, user.id)
    plan = service.generate(db, user, t)
    return plan_payload(db, user, plan)


@router.get("/targets/{target_id}/plans/active")
def get_active(target_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = owned(db, TargetRole, target_id, user.id)
    plan = service.active_plan(db, t)
    if plan is None:
        raise NotFound("You don't have a plan yet.", code="NO_PLAN")
    banner = service.rollover(db, user, t, plan)
    db.refresh(plan)
    return plan_payload(db, user, plan, banner)


@router.patch("/plan-tasks/{task_id}")
def patch_task(task_id: str, body: TaskPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    task = owned(db, PreparationTask, task_id, user.id)
    service.set_task_status(db, user, task, body.status)
    skills = catalog(db).skills_by_id
    res = {task.resource_id: db.get(LearningResource, task.resource_id)} if task.resource_id else {}
    return task_out(task, skills, res)


@router.post("/plans/{plan_id}/replan")
def replan(plan_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    plan = owned(db, PreparationPlan, plan_id, user.id)
    t = db.get(TargetRole, plan.target_id)
    service.replan(db, user, t, plan, "You asked to recalculate the plan.")
    db.refresh(plan)
    return plan_payload(db, user, plan)
