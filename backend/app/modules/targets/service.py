"""Target roles, job-description extraction (W-2) and requirement confirmation (SRS 5.2)."""
from __future__ import annotations

import hashlib
import re
import uuid
from datetime import date, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.ai import prompts
from app.ai.gateway import AIFailed, AIGateway, untrusted
from app.ai.schemas import W2Output
from app.ai.textcheck import normalise
from app.core.db import bulk_insert
from app.core.errors import AIQuotaExceeded, AIUnavailableError, AppError, Conflict, NotFound, ValidationFailed
from app.core.security import utcnow
from app.models import JobDescription, JobRequirement, Role, RoleSkill, Skill, TargetRole, User
from app.modules.catalog.matcher import SkillMatcher, get_matcher
from app.modules.targets.requirements import importance_for, load_requirements

PREFERRED_MARKERS = re.compile(r"nice[\s-]to[\s-]have|preferred|bonus|good[\s-]to[\s-]have|\bplus\b|desirable|"
                               r"optional|advantage", re.IGNORECASE)
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def company_notice(target: TargetRole, role_name: str) -> str | None:
    if not target.company_name:
        return None
    return (f"We don't have verified company-specific questions for {target.company_name}. "
            f"Practice uses curated questions for the {role_name} role.")


def get_role(db: Session, slug: str) -> Role:
    role = db.scalar(select(Role).where(Role.slug == slug, Role.is_active))
    if role is None:
        raise NotFound("That role isn't supported. Choose the closest supported role.", code="ROLE_NOT_FOUND")
    return role


def active_target(db: Session, user: User) -> TargetRole | None:
    return db.scalar(select(TargetRole).where(TargetRole.user_id == user.id, TargetRole.status == "active"))


def req_row(target: TargetRole, *, skill_id, raw_phrase: str, category: str, level: str, importance: str,
            origin: str, jd_id=None, evidence: str | None = None, inferred: bool = False) -> dict:
    return {"id": uuid.uuid4(), "target_id": target.id, "user_id": target.user_id, "job_description_id": jd_id,
            "skill_id": skill_id, "raw_phrase": raw_phrase[:200], "category": category, "requirement_level": level,
            "importance": importance, "origin": origin, "evidence_snippet": evidence, "is_inferred": inferred,
            "is_active": True}


def _role_defaults(db: Session, target: TargetRole, role) -> list[dict]:
    from app.modules.catalog.cache import catalog
    cat = catalog(db)
    reqs = []
    for skill_id, (importance, _w) in cat.role_skills.get(role.id, {}).items():
        skill = cat.skills_by_id[skill_id]
        level = "required" if importance in ("core", "required") else "preferred"
        reqs.append(req_row(target, skill_id=skill.id, raw_phrase=skill.name, category="skill", level=level,
                            importance=importance, origin="role_default"))
    return reqs


def validate_target_fields(deadline: date | None, daily_minutes: int | None, today: date) -> None:
    fields = {}
    if deadline is not None and not (today + timedelta(days=1) <= deadline <= today + timedelta(days=365)):
        fields["deadline_date"] = "Choose a date between tomorrow and one year from today."
    if daily_minutes is not None and (not 30 <= daily_minutes <= 240 or daily_minutes % 15):
        fields["daily_minutes"] = "Must be between 30 and 240, in steps of 15."
    if fields:
        raise ValidationFailed(details={"fields": fields})


def create_target(db: Session, user: User, *, role_slug: str, job_title: str | None, company_name: str | None,
                  deadline_date: date | None, daily_minutes: int, archive_current: bool, today: date) -> TargetRole:
    role = get_role(db, role_slug)
    deadline = deadline_date or today + timedelta(days=28)
    validate_target_fields(deadline, daily_minutes, today)
    current = active_target(db, user)
    if current is not None:
        if not archive_current:
            raise Conflict("You already have an active target. Confirm to archive it and start a new one.",
                           code="ACTIVE_TARGET_EXISTS", details={"active_target_id": str(current.id)})
        current.status, current.archived_at = "archived", utcnow()
        db.flush()
    target = TargetRole(user_id=user.id, role_id=role.id, job_title=(job_title or role.name).strip()[:120],
                        company_name=(company_name or "").strip()[:120] or None, deadline_date=deadline,
                        daily_minutes=daily_minutes, status="active")
    db.add(target)
    db.flush()
    bulk_insert(db, JobRequirement, _role_defaults(db, target, role))
    db.commit()
    return target


def update_target(db: Session, user: User, target: TargetRole, data: dict, today: date) -> TargetRole:
    if target.status == "archived":
        raise Conflict("Archived targets are read-only.", code="TARGET_ARCHIVED")
    validate_target_fields(data.get("deadline_date"), data.get("daily_minutes"), today)
    time_changed = False
    for key in ("job_title", "company_name", "deadline_date", "daily_minutes"):
        if key in data:
            value = data[key]
            if key in ("job_title", "company_name") and isinstance(value, str):
                value = value.strip()[:120] or None
            if key == "job_title" and not value:
                continue
            if key in ("deadline_date", "daily_minutes") and value is not None and getattr(target, key) != value:
                time_changed = True
            if value is not None or key == "company_name":
                setattr(target, key, value)
    db.commit()
    if time_changed:
        from app.modules.plans.service import replan_if_active
        replan_if_active(db, user, target, reason="Your deadline or daily study time changed.")
    return target


# ------------------------------------------------------------------ JD extraction
def _clean_jd(text: str) -> str:
    return CONTROL.sub("", text or "").strip()


def _level_from_context(text: str, start: int, end: int) -> str:
    clause_end = len(text)
    m = re.search(r"[,;\n.]", text[end:])
    if m:
        clause_end = end + m.start()
    after = text[end:min(clause_end, end + 60)]
    if PREFERRED_MARKERS.search(after):
        return "preferred"
    sent_start = max(text.rfind("\n", 0, start), text.rfind(". ", 0, start), start - 80, 0)
    if PREFERRED_MARKERS.search(text[sent_start:start]):
        return "preferred"
    return "required"


def prepass(text: str, matcher: SkillMatcher) -> dict[str, dict]:
    """Deterministic alias scan: slug -> {level, evidence}."""
    found: dict[str, dict] = {}
    for slug, spans in matcher.find(text).items():
        levels = [_level_from_context(text, s, e) for s, e in spans]
        s, e = spans[0]
        line_start = text.rfind("\n", 0, s) + 1
        line_end = text.find("\n", e)
        snippet = text[line_start: line_end if line_end != -1 else len(text)].strip()[:300]
        found[slug] = {"level": "required" if "required" in levels else "preferred", "evidence": snippet}
    return found


def submit_job_description(db: Session, user: User, target: TargetRole, text: str, force: bool,
                           gateway: AIGateway) -> tuple[JobDescription, list[str]]:
    if target.status == "archived":
        raise Conflict("Archived targets are read-only.", code="TARGET_ARCHIVED")
    jd_text = _clean_jd(text)
    if len(jd_text) > 15000:
        raise ValidationFailed("Job descriptions can be up to 15,000 characters.",
                               details={"fields": {"text": "Too long (max 15,000 characters)."}})
    if len(jd_text) < 200 and not force:
        raise AppError("This looks too short to be a job description.", code="JD_TOO_SHORT", status_code=422,
                       details={"min_chars": 200, "length": len(jd_text)})
    if not jd_text:
        raise ValidationFailed(details={"fields": {"text": "Paste the job description text."}})

    role = db.get(Role, target.role_id)
    assert role is not None
    sha = hashlib.sha256(jd_text.encode()).hexdigest()
    # Save the user's input before any AI call (NFR-009).
    db.execute(update(JobDescription).where(JobDescription.target_id == target.id,
                                            JobDescription.superseded_at.is_(None)).values(superseded_at=utcnow()))
    jd = JobDescription(target_id=target.id, user_id=user.id, raw_text=jd_text, text_sha256=sha, status="processing")
    db.add(jd)
    db.commit()

    matcher = get_matcher(db)
    pre = prepass(jd_text, matcher)
    warnings: list[str] = []
    ai_out: W2Output | None = None
    if len(re.findall(r"[^\x00-\x7F]", jd_text)) > len(jd_text) * 0.3:
        warnings.append("NON_ENGLISH_TEXT")
    try:
        taxonomy = ", ".join(f"{s.slug} ({s.name})" for s in matcher.skills)
        system = prompts.W2_SYSTEM.format(role_name=role.name, taxonomy=taxonomy)
        ai_out = gateway.run(workflow="W-2", prompt_version=prompts.W2_VERSION, system=system,
                             user=untrusted("job_description", jd_text), output_model=W2Output, user_id=user.id,
                             max_tokens=2500, temperature=0.2)
    except (AIUnavailableError, AIQuotaExceeded, AIFailed) as exc:
        warnings.append("AI_FALLBACK")
        warnings.append(f"AI_REASON:{exc.code}")

    from app.modules.catalog.cache import catalog
    cat = catalog(db)
    norm_jd = normalise(jd_text)
    role_rows = {sid: imp for sid, (imp, _w) in cat.role_skills.get(role.id, {}).items()}
    skill_rows = cat.skills_by_slug

    # slug -> requirement dict ; unmapped / non-skill rows kept separately
    merged: dict[str, dict] = {}
    extra_rows: list[dict] = []
    analysis: dict = {"responsibilities": [], "experience_expectations": [], "collaboration": [], "tools": [],
                      "notes": []}
    if ai_out is not None:
        analysis = {k: getattr(ai_out, k)[:20] for k in analysis}
        for item in ai_out.requirements:
            evidence = item.evidence.strip()
            in_text = bool(evidence) and normalise(evidence) in norm_jd
            slug = item.skill_slug if item.skill_slug in skill_rows else None
            if slug is None and item.category == "skill":
                slug = matcher.map_phrase(item.phrase) or (matcher.map_phrase(evidence) if in_text else None)
            row = {"phrase": item.phrase.strip()[:200], "level": item.level, "category": item.category,
                   "evidence": evidence[:300] if in_text else None, "inferred": not in_text}
            if item.category == "skill" and slug:
                prev = merged.get(slug)
                if prev is None or (prev["level"] == "preferred" and row["level"] == "required"):
                    merged[slug] = row
            else:
                extra_rows.append(row)
        # alias hits the model missed are still stated in the text
        for slug, hit in pre.items():
            merged.setdefault(slug, {"phrase": skill_rows[slug].name, "level": hit["level"], "category": "skill",
                                     "evidence": hit["evidence"], "inferred": False})
        jd.status = "extracted"
        jd.prompt_version = prompts.W2_VERSION
        jd.model = gateway.model_name
    else:
        for slug, hit in pre.items():
            merged[slug] = {"phrase": skill_rows[slug].name, "level": hit["level"], "category": "skill",
                            "evidence": hit["evidence"], "inferred": False}
        jd.status = "fallback"

    # replace requirement set atomically
    db.execute(update(JobRequirement).where(JobRequirement.target_id == target.id, JobRequirement.is_active)
               .values(is_active=False))
    db.flush()
    new_rows: list[dict] = []
    for slug, row in merged.items():
        skill = skill_rows[slug]
        new_rows.append(req_row(target, skill_id=skill.id, raw_phrase=row["phrase"] or skill.name, category="skill",
                                level=row["level"], importance=importance_for(role_rows.get(skill.id), row["level"]),
                                origin="jd_extracted", jd_id=jd.id, evidence=row["evidence"],
                                inferred=row["inferred"]))
    seen_phrases = set()
    for row in extra_rows:
        key = row["phrase"].lower()
        if key in seen_phrases or not row["phrase"]:
            continue
        seen_phrases.add(key)
        new_rows.append(req_row(target, skill_id=None, raw_phrase=row["phrase"], category=row["category"],
                                level=row["level"], importance=row["level"], origin="jd_extracted", jd_id=jd.id,
                                evidence=row["evidence"], inferred=row["inferred"]))
    # role-default core skills absent from the JD stay as preferred so fundamentals are still assessed
    merged_ids = {skill_rows[s].id for s in merged}
    for skill_id, imp in role_rows.items():
        if imp == "core" and skill_id not in merged_ids:
            skill = cat.skills_by_id[skill_id]
            new_rows.append(req_row(target, skill_id=skill_id, raw_phrase=skill.name, category="skill",
                                    level="preferred", importance="preferred", origin="role_default"))
    bulk_insert(db, JobRequirement, new_rows)

    mapped = [r for r in new_rows if r["skill_id"] and r["origin"] == "jd_extracted"]
    if mapped:
        in_role = sum(1 for r in mapped if r["skill_id"] in role_rows)
        if in_role / len(mapped) < 0.3:
            warnings.append("ROLE_MISMATCH")
    if not mapped:
        warnings.append("NO_SKILLS_FOUND")
    jd.analysis = analysis
    jd.warnings = warnings
    target.requirements_confirmed_at = None
    target.updated_at = utcnow()
    db.commit()
    return jd, warnings


def replace_requirements(db: Session, user: User, target: TargetRole, items: list[dict],
                         expected_updated_at) -> None:
    if target.status == "archived":
        raise Conflict("Archived targets are read-only.", code="TARGET_ARCHIVED")
    if expected_updated_at is not None and abs((target.updated_at - expected_updated_at).total_seconds()) > 0.001:
        raise Conflict("These requirements were changed elsewhere. Reload to see the latest list.",
                       code="STALE_UPDATE")
    if not 3 <= len(items) <= 40:
        raise ValidationFailed("Keep between 3 and 40 requirements.",
                               details={"fields": {"requirements": "Keep between 3 and 40 requirements."}})
    from app.modules.catalog.cache import catalog
    cat = catalog(db)
    skills = cat.skills_by_slug
    role_rows = {sid: imp for sid, (imp, _w) in cat.role_skills.get(target.role_id, {}).items()}
    existing = {r.id: r for r in db.scalars(select(JobRequirement).where(
        JobRequirement.target_id == target.id, JobRequirement.is_active)).all()}
    seen_skills: set[str] = set()
    keep_ids: set[uuid.UUID] = set()
    new_rows: list[dict] = []
    for i, item in enumerate(items):
        slug = item.get("skill_slug")
        phrase = (item.get("raw_phrase") or "").strip()[:200]
        level = item.get("requirement_level", "required")
        if level not in ("required", "preferred"):
            raise ValidationFailed(details={"fields": {f"requirements.{i}.requirement_level": "Invalid level."}})
        if slug and slug not in skills:
            raise ValidationFailed(details={"fields": {f"requirements.{i}.skill_slug": "Unknown skill."}})
        if not slug and not phrase:
            raise ValidationFailed(details={"fields": {f"requirements.{i}": "Needs a skill or a phrase."}})
        if slug:
            if slug in seen_skills:
                raise ValidationFailed(details={"fields": {f"requirements.{i}.skill_slug": "Duplicate skill."}})
            seen_skills.add(slug)
        rid = item.get("id")
        row = existing.get(uuid.UUID(rid)) if rid else None
        if row is not None:
            keep_ids.add(row.id)
            row.requirement_level = level
            if row.category == "skill":
                row.importance = importance_for(role_rows.get(row.skill_id), level)
            else:
                row.importance = level
            if phrase:
                row.raw_phrase = phrase
        else:
            skill = skills.get(slug) if slug else None
            new_rows.append(req_row(target, skill_id=skill.id if skill else None,
                                    raw_phrase=phrase or (skill.name if skill else ""),
                                    category=item.get("category") or "skill", level=level,
                                    importance=importance_for(role_rows.get(skill.id) if skill else None, level),
                                    origin="user_added"))
    mapped = sum(1 for rid in keep_ids if existing[rid].skill_id) + sum(1 for r in new_rows if r["skill_id"])
    if mapped == 0:
        db.rollback()
        raise ValidationFailed("Keep at least one requirement that maps to a skill.")
    removed = [rid for rid in existing if rid not in keep_ids]
    if removed:
        db.execute(update(JobRequirement).where(JobRequirement.id.in_(removed)).values(is_active=False))
    db.flush()
    bulk_insert(db, JobRequirement, new_rows)
    target.requirements_confirmed_at = utcnow()
    target.updated_at = utcnow()
    db.commit()
