from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import AppError, NotFound
from app.models import Role, RoleSkill, Skill

router = APIRouter(tags=["catalogue"])


class SkillOut(BaseModel):
    slug: str
    name: str
    category: str


class RoleSkillOut(SkillOut):
    importance: str
    weight: float


class RoleOut(BaseModel):
    slug: str
    name: str
    description: str
    top_skills: list[SkillOut]
    dimensions: list[str]


class RoleDetailOut(BaseModel):
    slug: str
    name: str
    description: str
    skills: list[RoleSkillOut]


def role_skills(db: Session, role_id) -> list[RoleSkillOut]:
    rows = db.execute(select(Skill, RoleSkill).join(RoleSkill, RoleSkill.skill_id == Skill.id)
                      .where(RoleSkill.role_id == role_id)).all()
    order = {"core": 0, "required": 1, "preferred": 2}
    rows.sort(key=lambda r: (order[r.RoleSkill.importance], -float(r.RoleSkill.weight)))
    return [RoleSkillOut(slug=s.slug, name=s.name, category=s.category, importance=rs.importance,
                         weight=float(rs.weight)) for s, rs in rows]


@router.get("/roles", response_model=list[RoleOut])
def list_roles(db: Session = Depends(get_db)):
    roles = db.scalars(select(Role).where(Role.is_active).order_by(Role.name)).all()
    if not roles:
        raise AppError("The role catalogue is empty — run the seed command.", code="CATALOGUE_EMPTY",
                       status_code=503)
    out = []
    for r in roles:
        skills = role_skills(db, r.id)
        dims = [k for k, v in r.dimension_config.get("dimensions", {}).items() if v.get("applies")]
        out.append(RoleOut(slug=r.slug, name=r.name, description=r.description,
                           top_skills=[SkillOut(slug=s.slug, name=s.name, category=s.category) for s in skills[:6]],
                           dimensions=dims))
    return out


@router.get("/roles/{slug}", response_model=RoleDetailOut)
def role_detail(slug: str, db: Session = Depends(get_db)):
    role = db.scalar(select(Role).where(Role.slug == slug, Role.is_active))
    if role is None:
        raise NotFound("That role isn't supported.", code="ROLE_NOT_FOUND")
    return RoleDetailOut(slug=role.slug, name=role.name, description=role.description,
                         skills=role_skills(db, role.id))


@router.get("/skills", response_model=list[SkillOut])
def list_skills(q: str | None = Query(default=None, max_length=50), db: Session = Depends(get_db)):
    stmt = select(Skill).where(Skill.is_active).order_by(Skill.name)
    if q:
        stmt = stmt.where(Skill.name.ilike(f"%{q}%"))
    return [SkillOut(slug=s.slug, name=s.name, category=s.category) for s in db.scalars(stmt).all()]
