from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.gateway import get_gateway
from app.core.db import get_db
from app.core.deps import current_user, owned
from app.core.errors import NotFound
from app.core.timeutil import user_today
from app.models import JobDescription, Role, TargetRole, User
from app.modules import hooks
from app.modules.targets import service
from app.modules.targets.requirements import load_requirements, req_out

router = APIRouter(prefix="/targets", tags=["targets"])


class TargetCreate(BaseModel):
    role_slug: str = Field(max_length=40)
    job_title: str | None = Field(default=None, max_length=120)
    company_name: str | None = Field(default=None, max_length=120)
    deadline_date: date | None = None
    daily_minutes: int = Field(default=60, ge=30, le=240)
    archive_current: bool = False


class TargetPatch(BaseModel):
    job_title: str | None = Field(default=None, max_length=120)
    company_name: str | None = Field(default=None, max_length=120)
    deadline_date: date | None = None
    daily_minutes: int | None = Field(default=None, ge=30, le=240)


class JDIn(BaseModel):
    text: str = Field(max_length=20000)
    force: bool = False


class RequirementItem(BaseModel):
    id: str | None = None
    skill_slug: str | None = Field(default=None, max_length=50)
    raw_phrase: str | None = Field(default=None, max_length=200)
    requirement_level: str = Field(default="required", pattern="^(required|preferred)$")
    category: str | None = Field(default=None, pattern="^(skill|experience|education|other)$")


class RequirementsPut(BaseModel):
    requirements: list[RequirementItem] = Field(max_length=60)
    expected_updated_at: datetime | None = None


def target_out(db: Session, t: TargetRole, today: date) -> dict:
    role = db.get(Role, t.role_id)
    assert role is not None
    jd = db.scalar(select(JobDescription).where(JobDescription.target_id == t.id,
                                                JobDescription.superseded_at.is_(None)))
    return {
        "id": str(t.id), "role": {"slug": role.slug, "name": role.name}, "job_title": t.job_title,
        "company_name": t.company_name, "deadline_date": t.deadline_date.isoformat(),
        "days_to_deadline": (t.deadline_date - today).days, "deadline_passed": t.deadline_date < today,
        "daily_minutes": t.daily_minutes, "status": t.status,
        "requirements_confirmed_at": t.requirements_confirmed_at.isoformat() if t.requirements_confirmed_at else None,
        "updated_at": t.updated_at.isoformat(), "company_notice": service.company_notice(t, role.name),
        "job_description": None if jd is None else {
            "id": str(jd.id), "status": jd.status, "text": jd.raw_text, "analysis": jd.analysis,
            "warnings": jd.warnings, "created_at": jd.created_at.isoformat(), "model": jd.model},
    }


def requirements_payload(db: Session, t: TargetRole) -> dict:
    return {"requirements": [req_out(r) for r in load_requirements(db, t)],
            "confirmed_at": t.requirements_confirmed_at.isoformat() if t.requirements_confirmed_at else None,
            "updated_at": t.updated_at.isoformat()}


@router.post("", status_code=201)
def create(body: TargetCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    today = user_today(user.timezone)
    t = service.create_target(db, user, role_slug=body.role_slug, job_title=body.job_title,
                              company_name=body.company_name, deadline_date=body.deadline_date,
                              daily_minutes=body.daily_minutes, archive_current=body.archive_current, today=today)
    hooks.requirements_changed(db, user, t, trigger="target_created")
    return {"target": target_out(db, t, today), **requirements_payload(db, t)}


@router.get("")
def list_targets(status: str | None = Query(default=None, pattern="^(active|archived)$"),
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(TargetRole).where(TargetRole.user_id == user.id).order_by(TargetRole.created_at.desc())
    if status:
        stmt = stmt.where(TargetRole.status == status)
    today = user_today(user.timezone)
    return [target_out(db, t, today) for t in db.scalars(stmt).all()]


@router.get("/active")
def get_active(user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = service.active_target(db, user)
    if t is None:
        raise NotFound("You don't have an active target yet.", code="NO_ACTIVE_TARGET")
    return target_out(db, t, user_today(user.timezone))


@router.get("/{target_id}")
def get_target(target_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return target_out(db, owned(db, TargetRole, target_id, user.id), user_today(user.timezone))


@router.patch("/{target_id}")
def patch_target(target_id: str, body: TargetPatch, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    t = owned(db, TargetRole, target_id, user.id)
    today = user_today(user.timezone)
    service.update_target(db, user, t, body.model_dump(exclude_unset=True), today)
    return target_out(db, t, today)


@router.post("/{target_id}/archive")
def archive(target_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from app.core.security import utcnow
    t = owned(db, TargetRole, target_id, user.id)
    if t.status != "archived":
        t.status, t.archived_at = "archived", utcnow()
        db.commit()
    return target_out(db, t, user_today(user.timezone))


@router.post("/{target_id}/job-description")
def submit_jd(target_id: str, body: JDIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = owned(db, TargetRole, target_id, user.id)
    jd, warnings = service.submit_job_description(db, user, t, body.text, body.force, get_gateway())
    hooks.requirements_changed(db, user, t, trigger="requirements_changed")
    return {"job_description_id": str(jd.id), "status": jd.status, "warnings": warnings, "analysis": jd.analysis,
            "model": jd.model, **requirements_payload(db, t)}


@router.get("/{target_id}/requirements")
def get_requirements(target_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return requirements_payload(db, owned(db, TargetRole, target_id, user.id))


@router.put("/{target_id}/requirements")
def put_requirements(target_id: str, body: RequirementsPut, user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    t = owned(db, TargetRole, target_id, user.id)
    service.replace_requirements(db, user, t, [i.model_dump() for i in body.requirements], body.expected_updated_at)
    hooks.requirements_changed(db, user, t, trigger="requirements_changed")
    return requirements_payload(db, t)
