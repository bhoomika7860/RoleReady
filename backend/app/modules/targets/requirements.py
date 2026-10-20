"""Requirement-set helpers shared by coverage, gaps, assessments and the planner."""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import JobRequirement, RoleSkill, Skill, TargetRole


@dataclass
class Req:
    id: uuid.UUID
    skill_id: uuid.UUID | None
    skill_slug: str | None
    skill_name: str | None
    raw_phrase: str
    category: str
    level: str
    importance: str
    origin: str
    evidence_snippet: str | None
    is_inferred: bool
    role_weight: float


def load_requirements(db: Session, target: TargetRole, *, scored_only: bool = False) -> list[Req]:
    rows = db.execute(
        select(JobRequirement, Skill.slug, Skill.name)
        .outerjoin(Skill, Skill.id == JobRequirement.skill_id)
        .where(JobRequirement.target_id == target.id, JobRequirement.is_active)
    ).all()
    from app.modules.catalog.cache import catalog
    weights = {sid: w for sid, (_, w) in catalog(db).role_skills.get(target.role_id, {}).items()}
    out = []
    for jr, slug, name in rows:
        if scored_only and jr.category != "skill":
            continue
        out.append(Req(jr.id, jr.skill_id, slug, name, jr.raw_phrase, jr.category, jr.requirement_level,
                       jr.importance, jr.origin, jr.evidence_snippet, jr.is_inferred,
                       float(weights.get(jr.skill_id, 0))))
    order = {"core": 0, "required": 1, "preferred": 2}
    origin_order = {"jd_extracted": 0, "user_added": 1, "role_default": 2}
    out.sort(key=lambda r: (order[r.importance], origin_order[r.origin], -r.role_weight, r.raw_phrase))
    return out


def requirements_hash(reqs: list[Req]) -> str:
    key = "|".join(sorted(f"{r.skill_id or r.raw_phrase.lower()}:{r.importance}" for r in reqs
                          if r.category == "skill"))
    return hashlib.sha256(key.encode()).hexdigest()


def importance_for(role_importance: str | None, level: str) -> str:
    if role_importance == "core" and level == "required":
        return "core"
    return level


def req_out(r: Req) -> dict:
    return {"id": str(r.id), "skill": {"slug": r.skill_slug, "name": r.skill_name} if r.skill_slug else None,
            "raw_phrase": r.raw_phrase, "category": r.category, "requirement_level": r.level,
            "importance": r.importance, "origin": r.origin, "evidence_snippet": r.evidence_snippet,
            "is_inferred": r.is_inferred, "scored": r.category == "skill"}
