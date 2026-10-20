"""Idempotent, validated content seeding (SRS FR-070, FR-120, FR-124).

python -m app.seed            # load/refresh all catalogue content
python -m app.seed --if-empty # only when the catalogue is empty (container start)
"""
from __future__ import annotations

import json
import math
from collections import Counter
from datetime import date
from pathlib import Path

import yaml
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import (OBJECTIVE_TYPES, QUESTION_TYPES, SKILL_CATEGORIES, LearningResource, Question,
                        ResourceSkill, Role, RoleSkill, Skill, SkillPrerequisite)

SEED_DIR = Path(__file__).resolve().parent
MIN_TOTAL_QUESTIONS = 120


class SeedError(Exception):
    pass


def _load(name: str) -> dict:
    with open(SEED_DIR / name, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


# ------------------------------------------------------------------ validation
def validate_skills(skills: list[dict]) -> None:
    slugs = [s["slug"] for s in skills]
    dupes = [s for s, c in Counter(slugs).items() if c > 1]
    if dupes:
        raise SeedError(f"skills.yaml: duplicate slugs {dupes}")
    known = set(slugs)
    graph: dict[str, list[str]] = {}
    for s in skills:
        if s["category"] not in SKILL_CATEGORIES:
            raise SeedError(f"skills.yaml: {s['slug']} has invalid category {s['category']}")
        for p in s.get("prerequisites", []):
            if p not in known:
                raise SeedError(f"skills.yaml: {s['slug']} prerequisite {p} is not a skill")
        graph[s["slug"]] = s.get("prerequisites", [])
    state: dict[str, int] = {}

    def visit(node: str, path: list[str]) -> None:
        if state.get(node) == 1:
            raise SeedError(f"skills.yaml: prerequisite cycle {' -> '.join(path + [node])}")
        if state.get(node) == 2:
            return
        state[node] = 1
        for nxt in graph[node]:
            visit(nxt, path + [node])
        state[node] = 2

    for node in graph:
        visit(node, [])


def validate_question(q: dict, where: str, skill_slugs: set[str]) -> None:
    def fail(msg: str) -> None:
        raise SeedError(f"{where} [{q.get('slug', '?')}]: {msg}")

    for key in ("slug", "skill", "topic", "type", "difficulty", "purpose", "prompt", "explanation"):
        if not q.get(key):
            fail(f"missing {key}")
    if q["skill"] not in skill_slugs:
        fail(f"unknown skill {q['skill']}")
    if q["type"] not in QUESTION_TYPES:
        fail(f"invalid type {q['type']}")
    if q["difficulty"] not in ("easy", "medium", "hard"):
        fail("invalid difficulty")
    if q["purpose"] not in ("assessment", "practice", "interview", "any"):
        fail("invalid purpose")
    if len(q["prompt"]) > 4000:
        fail("prompt longer than 4000 characters")
    if q["type"] in OBJECTIVE_TYPES:
        opts = q.get("options") or []
        if not 3 <= len(opts) <= 6:
            fail("objective questions need 3–6 options")
        ids = [o["id"] for o in opts]
        if len(set(ids)) != len(ids) or len({o["text"] for o in opts}) != len(opts):
            fail("option ids and texts must be distinct")
        ans = q.get("answer")
        if q["type"] == "mcq_multi":
            if not isinstance(ans, list) or not ans or any(a not in ids for a in ans):
                fail("mcq_multi answer must be a non-empty list of option ids")
        elif ans not in ids:
            fail("answer must be one of the option ids")
    else:
        kps = q.get("key_points") or []
        if len(kps) < 3:
            fail("short answers need at least 3 key points")
        if not math.isclose(sum(k["weight"] for k in kps), 1.0, abs_tol=0.001):
            fail("key point weights must sum to 1.0")
        if len({k["id"] for k in kps}) != len(kps):
            fail("key point ids must be distinct")
        if not q.get("reference_answer"):
            fail("short answers need a reference_answer")


def validate_resource(r: dict, where: str, skill_slugs: set[str]) -> None:
    def fail(msg: str) -> None:
        raise SeedError(f"{where} [{r.get('url', '?')}]: {msg}")

    if not str(r.get("url", "")).startswith("https://"):
        fail("url must start with https://")
    if r.get("format") not in ("doc", "article", "video", "course", "interactive", "notes"):
        fail("invalid format")
    if r.get("difficulty") not in ("beginner", "intermediate", "advanced"):
        fail("invalid difficulty")
    if not 5 <= int(r.get("minutes", 0)) <= 180:
        fail("minutes must be 5–180")
    skills = r.get("skills") or []
    if not 1 <= len(skills) <= 3 or any(s not in skill_slugs for s in skills):
        fail("each resource maps to 1–3 known skills")


def load_questions_yaml() -> list[tuple[str, dict]]:
    items: list[tuple[str, dict]] = []
    for path in sorted((SEED_DIR / "questions").glob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        defaults = doc.get("defaults", {})
        for q in doc.get("questions", []):
            items.append((path.name, {**defaults, **q}))
    return items


def load_verification() -> dict[str, dict]:
    path = SEED_DIR / "resource_verification.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ loading
def seed(db: Session, *, strict: bool = True) -> dict[str, int]:
    skills_doc, roles_doc, res_doc = _load("skills.yaml"), _load("roles.yaml"), _load("resources.yaml")
    skills = skills_doc["skills"]
    validate_skills(skills)
    skill_slugs = {s["slug"] for s in skills}
    questions = load_questions_yaml()
    for where, q in questions:
        validate_question(q, where, skill_slugs)
    q_slugs = [q["slug"] for _, q in questions]
    dupes = [s for s, c in Counter(q_slugs).items() if c > 1]
    if dupes:
        raise SeedError(f"duplicate question slugs: {dupes[:5]}")
    for r in res_doc.get("resources", []):
        validate_resource(r, "resources.yaml", skill_slugs)
    if strict and len(questions) < MIN_TOTAL_QUESTIONS:
        raise SeedError(f"question bank has {len(questions)} items; minimum is {MIN_TOTAL_QUESTIONS}")

    # skills
    for s in skills:
        db.execute(insert(Skill).values(slug=s["slug"], name=s["name"], category=s["category"],
                                        aliases=s.get("aliases", []), description=s.get("description"))
                   .on_conflict_do_update(index_elements=["slug"], set_={
                       "name": s["name"], "category": s["category"], "aliases": s.get("aliases", []),
                       "description": s.get("description"), "is_active": True}))
    skill_ids = {row.slug: row.id for row in db.execute(select(Skill.slug, Skill.id))}
    db.execute(delete(SkillPrerequisite))
    for s in skills:
        for p in s.get("prerequisites", []):
            db.add(SkillPrerequisite(skill_id=skill_ids[s["slug"]], prerequisite_skill_id=skill_ids[p]))

    # roles
    for r in roles_doc["roles"]:
        dims = r["dimensions"]
        config = {"scoring_version": "s1",
                  "dimensions": {k: {"applies": True, "weight": v} for k, v in dims.items()},
                  "bands": [[75, "Strong"], [60, "Approaching"], [40, "Developing"], [0, "Early"]]}
        db.execute(insert(Role).values(slug=r["slug"], name=r["name"], description=r["description"],
                                       dimension_config=config)
                   .on_conflict_do_update(index_elements=["slug"], set_={
                       "name": r["name"], "description": r["description"], "dimension_config": config,
                       "is_active": True}))
        role_id = db.scalar(select(Role.id).where(Role.slug == r["slug"]))
        db.execute(delete(RoleSkill).where(RoleSkill.role_id == role_id))
        for slug, importance, weight in r["skills"]:
            if slug not in skill_ids:
                raise SeedError(f"roles.yaml: {r['slug']} references unknown skill {slug}")
            db.add(RoleSkill(role_id=role_id, skill_id=skill_ids[slug], importance=importance, weight=weight))

    # questions (upsert by slug; removed items are retired, never deleted)
    for _, q in questions:
        values = dict(
            slug=q["slug"], skill_id=skill_ids[q["skill"]], topic=q["topic"], type=q["type"],
            difficulty=q["difficulty"], purpose=q["purpose"], prompt=q["prompt"].strip(),
            options=q.get("options"),
            correct_answer=({"selected": q["answer"] if isinstance(q["answer"], list) else [q["answer"]]}
                            if q["type"] in OBJECTIVE_TYPES else None),
            reference_answer=q.get("reference_answer"),
            rubric=({"version": q.get("rubric_version", "sar-1"), "key_points": q["key_points"]}
                    if q["type"] not in OBJECTIVE_TYPES else None),
            explanation=q["explanation"].strip(), source_type=q.get("source_type", "curated_general"),
            authoring=q.get("authoring", "ai_assisted"), reviewed_by=q.get("reviewed_by"),
            reviewed_at=q.get("reviewed_at"), bank_version=str(q.get("bank_version", "v1")), status="active")
        update_cols = {k: v for k, v in values.items() if k != "slug"}
        db.execute(insert(Question).values(**values).on_conflict_do_update(index_elements=["slug"],
                                                                          set_=update_cols))
    db.execute(update(Question).where(Question.owner_user_id.is_(None), Question.slug.is_not(None),
                                      Question.slug.not_in(q_slugs)).values(status="retired"))

    # resources: verified date comes only from the link-check report
    verification = load_verification()
    for r in res_doc.get("resources", []):
        v = verification.get(r["url"], {})
        verified = date.fromisoformat(v["checked_on"]) if v.get("ok") else None
        values = dict(title=r["title"], url=r["url"], provider=r["provider"], format=r["format"],
                      difficulty=r["difficulty"], est_minutes=int(r["minutes"]), is_free=bool(r.get("free", True)),
                      description=r.get("description"), last_verified_at=verified,
                      verification_note=(f"HTTP {v.get('status')} on {v.get('checked_on')}" if v else
                                         "Not yet link-checked"),
                      is_active=True)
        db.execute(insert(LearningResource).values(**values).on_conflict_do_update(
            index_elements=["url"], set_={k: val for k, val in values.items() if k != "url"}))
        rid = db.scalar(select(LearningResource.id).where(LearningResource.url == r["url"]))
        db.execute(delete(ResourceSkill).where(ResourceSkill.resource_id == rid))
        for slug in r["skills"]:
            db.add(ResourceSkill(resource_id=rid, skill_id=skill_ids[slug], topic=r.get("topic")))
    db.commit()
    from app.modules.catalog import cache
    from app.modules.catalog.matcher import reset_matcher
    reset_matcher()
    cache.reset()

    counts = {
        "skills": len(skills), "roles": len(roles_doc["roles"]), "questions": len(questions),
        "resources": len(res_doc.get("resources", [])),
        "resources_verified": sum(1 for r in res_doc.get("resources", []) if verification.get(r["url"], {}).get("ok")),
        "questions_unreviewed": sum(1 for _, q in questions if not q.get("reviewed_by")),
    }
    return counts


def catalogue_empty(db: Session) -> bool:
    return db.scalar(select(Role.id).limit(1)) is None
