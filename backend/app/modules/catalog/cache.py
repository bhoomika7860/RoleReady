"""In-process cache of read-only catalogue data (roles, skills, role skills, prerequisites, pool sizes).

Catalogue tables only change when `python -m app.seed` runs, which calls `reset()`. Caching them removes
dozens of database round trips per request — important when the database is a remote managed instance.
"""
from __future__ import annotations

import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Question, Role, RoleSkill, Skill, SkillPrerequisite


@dataclass(frozen=True)
class SkillRow:
    id: uuid.UUID
    slug: str
    name: str
    category: str


@dataclass(frozen=True)
class RoleRow:
    id: uuid.UUID
    slug: str
    name: str
    description: str
    dimension_config: dict


@dataclass
class Catalog:
    skills_by_id: dict[uuid.UUID, SkillRow]
    skills_by_slug: dict[str, SkillRow]
    roles_by_id: dict[uuid.UUID, RoleRow]
    roles_by_slug: dict[str, RoleRow]
    role_skills: dict[uuid.UUID, dict[uuid.UUID, tuple[str, float]]]  # role → skill → (importance, weight)
    prerequisites: dict[str, set[str]]                                # skill id str → prerequisite id strs
    assessment_pool: dict[uuid.UUID, int]                             # curated assessment-eligible counts


_cache: Catalog | None = None
_lock = threading.Lock()


def _load(db: Session) -> Catalog:
    skills = [SkillRow(s.id, s.slug, s.name, s.category) for s in db.scalars(select(Skill).where(Skill.is_active))]
    roles = [RoleRow(r.id, r.slug, r.name, r.description, r.dimension_config)
             for r in db.scalars(select(Role).where(Role.is_active))]
    rs: dict[uuid.UUID, dict[uuid.UUID, tuple[str, float]]] = defaultdict(dict)
    for row in db.scalars(select(RoleSkill)):
        rs[row.role_id][row.skill_id] = (row.importance, float(row.weight))
    pre: dict[str, set[str]] = defaultdict(set)
    for sid, pid in db.execute(select(SkillPrerequisite.skill_id, SkillPrerequisite.prerequisite_skill_id)):
        pre[str(sid)].add(str(pid))
    pool = dict(db.execute(select(Question.skill_id, func.count()).where(
        Question.status == "active", Question.owner_user_id.is_(None),
        Question.purpose.in_(("assessment", "any"))).group_by(Question.skill_id)).all())
    return Catalog({s.id: s for s in skills}, {s.slug: s for s in skills}, {r.id: r for r in roles},
                   {r.slug: r for r in roles}, dict(rs), dict(pre), pool)


def catalog(db: Session) -> Catalog:
    global _cache
    with _lock:
        if _cache is None:
            _cache = _load(db)
        return _cache


def reset() -> None:
    global _cache
    with _lock:
        _cache = None
