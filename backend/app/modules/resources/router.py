from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import current_user, owned
from app.models import GapReport, LearningResource, ResourceSkill, Skill, SkillGap, TargetRole, User

router = APIRouter(tags=["resources"])


@router.get("/resources")
def list_resources(skill: str | None = Query(default=None, max_length=50),
                   format: str | None = Query(default=None, pattern="^(doc|article|video|course|interactive|notes)$"),
                   difficulty: str | None = Query(default=None, pattern="^(beginner|intermediate|advanced)$"),
                   free: bool | None = None, q: str | None = Query(default=None, max_length=80),
                   target_id: uuid.UUID | None = None, page: int = Query(default=1, ge=1),
                   page_size: int = Query(default=20, ge=1, le=50),
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    # Only link-checked resources are served (SRS FR-070, T-121).
    stmt = select(LearningResource).where(LearningResource.is_active, LearningResource.last_verified_at.is_not(None))
    if skill:
        stmt = stmt.join(ResourceSkill, ResourceSkill.resource_id == LearningResource.id) \
            .join(Skill, Skill.id == ResourceSkill.skill_id).where(Skill.slug == skill)
    if format:
        stmt = stmt.where(LearningResource.format == format)
    if difficulty:
        stmt = stmt.where(LearningResource.difficulty == difficulty)
    if free is not None:
        stmt = stmt.where(LearningResource.is_free == free)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(LearningResource.title.ilike(like), LearningResource.description.ilike(like),
                              LearningResource.provider.ilike(like)))
    rows = db.scalars(stmt.distinct()).all()

    gap_priority: dict[uuid.UUID, int] = {}
    if target_id is not None:
        t = owned(db, TargetRole, target_id, user.id)
        rep = db.scalar(select(GapReport.id).where(GapReport.target_id == t.id)
                        .order_by(GapReport.created_at.desc()).limit(1))
        if rep:
            for sid, pr in db.execute(select(SkillGap.skill_id, SkillGap.priority_score)
                                      .where(SkillGap.gap_report_id == rep, SkillGap.skill_id.is_not(None))).all():
                gap_priority[sid] = max(pr, gap_priority.get(sid, 0))

    ids = [r.id for r in rows]
    links: dict[uuid.UUID, list[dict]] = {}
    if ids:
        for rid, s, topic in db.execute(select(ResourceSkill.resource_id, Skill, ResourceSkill.topic)
                                        .join(Skill, Skill.id == ResourceSkill.skill_id)
                                        .where(ResourceSkill.resource_id.in_(ids))).all():
            links.setdefault(rid, []).append({"slug": s.slug, "name": s.name, "topic": topic,
                                              "gap_priority": gap_priority.get(s.id)})
    items = []
    for r in rows:
        sk = links.get(r.id, [])
        rel = max([x["gap_priority"] or 0 for x in sk] or [0])
        items.append({"id": str(r.id), "title": r.title, "url": r.url, "provider": r.provider, "format": r.format,
                      "difficulty": r.difficulty, "minutes": r.est_minutes, "is_free": r.is_free,
                      "description": r.description, "last_verified_at": r.last_verified_at.isoformat(),
                      "verification_note": r.verification_note, "skills": sk, "relevance": rel})
    items.sort(key=lambda x: (-x["relevance"], x["title"].lower()))
    total = len(items)
    start = (page - 1) * page_size
    total_unverified = db.scalar(select(func.count()).select_from(LearningResource)
                                 .where(LearningResource.last_verified_at.is_(None))) or 0
    return {"items": items[start:start + page_size], "page": page, "page_size": page_size, "total": total,
            "hidden_unverified": total_unverified}
