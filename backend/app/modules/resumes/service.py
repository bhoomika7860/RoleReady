"""Resume Studio services (SRS 5.3): import, scratch creation, versions, rewrite suggestions."""
from __future__ import annotations

import json
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.ai import fact_guard, prompts
from app.ai.gateway import AIFailed, AIGateway, untrusted
from app.ai.redaction import redact
from app.ai.schemas import W3Output
from app.core.errors import AIQuotaExceeded, AIUnavailableError, AppError, Conflict, NotFound, ValidationFailed
from app.core.security import utcnow
from app.models import Resume, ResumeVersion, RewriteSuggestion, Role, TargetRole, User
from app.modules.catalog.matcher import get_matcher
from app.modules.resumes.schemas import ResumeContent, ensure_ids
from app.modules.resumes.structuring import StructureResult, structure_text
from app.modules.targets.requirements import load_requirements

MAX_RESUMES = 5
MAX_VERSIONS = 30


def check_limit(db: Session, user: User) -> None:
    n = db.scalar(select(func.count()).select_from(Resume).where(Resume.user_id == user.id)) or 0
    if n >= MAX_RESUMES:
        raise Conflict(f"You can keep up to {MAX_RESUMES} resumes. Delete one to add another.",
                       code="RESUME_LIMIT_REACHED")


def _create(db: Session, user: User, *, title: str, source: str, filename: str | None, raw_text: str | None,
            content: ResumeContent, extraction_status: str, created_by: str, reviewed: bool) -> tuple[Resume,
                                                                                                   ResumeVersion]:
    resume = Resume(user_id=user.id, title=title[:100] or "My resume", source=source, original_filename=filename,
                    raw_text=raw_text, extraction_status=extraction_status, reviewed_at=utcnow() if reviewed else None)
    db.add(resume)
    db.flush()
    version = ResumeVersion(resume_id=resume.id, user_id=user.id, version_number=1,
                            content=content.model_dump(mode="json"), created_by=created_by,
                            change_summary="Imported" if created_by == "import" else "Created")
    db.add(version)
    db.flush()
    resume.current_version_id = version.id
    db.commit()
    return resume, version


def import_text(db: Session, user: User, raw_text: str, *, title: str, source: str, filename: str | None,
                gateway: AIGateway) -> tuple[Resume, ResumeVersion, StructureResult]:
    check_limit(db, user)
    result = structure_text(raw_text, get_matcher(db), gateway, user.id,
                            fallback_name=user.preferred_name or "Your name")
    resume, version = _create(db, user, title=title, source=source, filename=filename, raw_text=raw_text,
                              content=result.content, extraction_status=result.status, created_by="import",
                              reviewed=False)
    return resume, version, result


def create_from_scratch(db: Session, user: User, title: str, content: ResumeContent) -> tuple[Resume, ResumeVersion]:
    check_limit(db, user)
    if not (content.education or content.experience or content.projects):
        raise ValidationFailed("Add at least one education, experience or project entry.",
                               details={"fields": {"content": "Add at least one education, experience or project."}})
    content = _with_skill_slugs(db, ensure_ids(content))
    return _create(db, user, title=title, source="scratch", filename=None, raw_text=None, content=content,
                   extraction_status="manual", created_by="user", reviewed=True)


def _with_skill_slugs(db: Session, content: ResumeContent) -> ResumeContent:
    m = get_matcher(db)
    for s in content.skills:
        s.skill_slug = m.map_phrase(s.name)  # set by alias matching only, never by the client or the LLM
    return content


def current_version(db: Session, resume: Resume) -> ResumeVersion:
    v = db.get(ResumeVersion, resume.current_version_id)
    if v is None:
        raise NotFound()
    return v


def save_version(db: Session, user: User, resume: Resume, content: ResumeContent, base_version_id: uuid.UUID,
                 *, created_by: str = "user", change_summary: str | None = None,
                 mark_reviewed: bool = False) -> ResumeVersion:
    locked = db.scalar(select(Resume).where(Resume.id == resume.id).with_for_update())
    assert locked is not None
    if locked.current_version_id != base_version_id:
        latest = db.get(ResumeVersion, locked.current_version_id)
        db.rollback()
        raise Conflict("A newer version of this resume exists. Load the latest version and reapply your edits.",
                       code="STALE_VERSION",
                       details={"latest_version_id": str(latest.id) if latest else None})
    content = _with_skill_slugs(db, ensure_ids(content))
    max_no = db.scalar(select(func.max(ResumeVersion.version_number)).where(ResumeVersion.resume_id == resume.id)) or 0
    version = ResumeVersion(resume_id=resume.id, user_id=user.id, version_number=max_no + 1,
                            parent_version_id=base_version_id, content=content.model_dump(mode="json"),
                            created_by=created_by, change_summary=(change_summary or "Edited")[:300])
    db.add(version)
    db.flush()
    locked.current_version_id = version.id
    if mark_reviewed and locked.reviewed_at is None:
        locked.reviewed_at = utcnow()
    db.execute(update(RewriteSuggestion).where(RewriteSuggestion.resume_id == resume.id,
                                               RewriteSuggestion.status.in_(("pending", "flagged")))
               .values(status="expired"))
    # keep at most MAX_VERSIONS (oldest non-v1 pruned)
    ids = db.scalars(select(ResumeVersion.id).where(ResumeVersion.resume_id == resume.id,
                                                    ResumeVersion.version_number > 1)
                     .order_by(ResumeVersion.version_number.desc()).offset(MAX_VERSIONS - 1)).all()
    for vid in ids:
        db.delete(db.get(ResumeVersion, vid))
    db.commit()
    return version


# ------------------------------------------------------------------ rewrite (W-3 + fact guard)
def find_bullet(content: ResumeContent, bullet_id: str):
    for section, entries in (("experience", content.experience), ("projects", content.projects)):
        for entry in entries:
            for b in entry.bullets:
                if b.id == bullet_id:
                    return section, entry, b
    raise NotFound("That bullet isn't in this version of the resume.")


def allowed_facts(entry, bullet_text: str, answers: list[dict]) -> list[str]:
    facts = [bullet_text, getattr(entry, "title", None) or getattr(entry, "name", ""),
             getattr(entry, "organization", None) or getattr(entry, "role", None) or "",
             *entry.technologies, *(b.text for b in entry.bullets)]
    facts += [a.get("answer", "") for a in answers if a.get("answer")]
    return [f for f in facts if f]


def _call_w3(gateway: AIGateway, user: User, role_name: str, entry, bullet_text: str, emphasis: list[str],
             answers: list[dict], violations: list[str]) -> W3Output:
    entry_doc = {
        "kind": "experience" if hasattr(entry, "title") else "project",
        "title": getattr(entry, "title", None) or getattr(entry, "name", None),
        "organization": getattr(entry, "organization", None) or getattr(entry, "role", None),
        "technologies": entry.technologies,
        "other_bullets": [b.text for b in entry.bullets if b.text != bullet_text],
        "bullet_to_improve": bullet_text,
        "emphasis_terms_already_in_entry": emphasis,
        "candidate_answers": answers,
    }
    text = redact(json.dumps(entry_doc, ensure_ascii=False)).text
    note = ("Your previous suggestions were rejected by the fact checker for: " + "; ".join(violations) +
            ". Remove those facts.") if violations else ""
    system = prompts.W3_SYSTEM.format(role_name=role_name, violations=note)
    return gateway.run(workflow="W-3", prompt_version=prompts.W3_VERSION, system=system,
                       user=untrusted("resume_entry", text), output_model=W3Output, user_id=user.id,
                       max_tokens=900, temperature=0.5)


def request_rewrite(db: Session, user: User, resume: Resume, version: ResumeVersion, bullet_id: str,
                    target: TargetRole | None, gateway: AIGateway, answers: list[dict] | None = None,
                    previous_questions: list[dict] | None = None) -> list[RewriteSuggestion]:
    if version.id != resume.current_version_id:
        raise Conflict("This version is no longer current. Reload the latest version.", code="STALE_VERSION")
    content = ResumeContent.model_validate(version.content)
    section, entry, bullet = find_bullet(content, bullet_id)
    answers = answers or []
    facts = allowed_facts(entry, bullet.text, answers)
    m = get_matcher(db)
    role_name = "the target"
    emphasis: list[str] = []
    if target is not None:
        role = db.get(Role, target.role_id)
        role_name = role.name if role else role_name
        fact_text = "\n".join(facts)
        emphasis = [r.skill_name for r in load_requirements(db, target, scored_only=True)
                    if r.skill_slug and m.matches(r.skill_slug, fact_text)][:8]

    first = _call_w3(gateway, user, role_name, entry, bullet.text, emphasis, answers, [])
    reports = [(s, fact_guard.check(s.text, facts, m)) for s in first.suggestions]
    passing = [(s, r) for s, r in reports if r.ok]
    failing = [(s, r) for s, r in reports if not r.ok]
    questions = [q.model_dump() for q in first.questions][:3]
    if failing:
        violations = sorted({v for _, r in failing for v in r.violations})
        try:
            second = _call_w3(gateway, user, role_name, entry, bullet.text, emphasis, answers, violations)
            reports2 = [(s, fact_guard.check(s.text, facts, m)) for s in second.suggestions]
            passing += [(s, r) for s, r in reports2 if r.ok]
            failing = [(s, r) for s, r in reports2 if not r.ok]
            questions = questions or [q.model_dump() for q in second.questions][:3]
        except (AIFailed, AIUnavailableError, AIQuotaExceeded):
            pass

    rows: list[RewriteSuggestion] = []
    seen = set()
    base = dict(user_id=user.id, resume_id=resume.id, resume_version_id=version.id,
                target_id=target.id if target else None,
                bullet_ref={"section": section, "entry_id": entry.id, "bullet_id": bullet.id},
                original_text=bullet.text, questions=questions, user_answers=answers,
                prompt_version=prompts.W3_VERSION)
    for s, r in passing:
        if s.text in seen or s.text.strip() == bullet.text.strip() or len(rows) >= 2:
            continue
        seen.add(s.text)
        rows.append(RewriteSuggestion(**base, suggested_text=s.text[:300], rationale=s.rationale[:300],
                                      facts_used=s.facts_used, guard_report=r.as_dict(), status="pending"))
    if not rows:
        for s, r in failing[:1]:
            rows.append(RewriteSuggestion(**base, suggested_text=s.text[:300], rationale=s.rationale[:300],
                                          facts_used=s.facts_used, guard_report=r.as_dict(), status="flagged"))
        if questions and not rows:
            rows.append(RewriteSuggestion(**base, suggested_text=None, rationale=None, facts_used=[],
                                          guard_report={"ok": True, "violations": []}, status="pending"))
    db.add_all(rows)
    db.commit()
    return rows


def apply_suggestion(db: Session, user: User, sug: RewriteSuggestion, edited_text: str | None) -> ResumeVersion:
    resume = db.get(Resume, sug.resume_id)
    assert resume is not None
    if resume.current_version_id != sug.resume_version_id:
        sug.status = "expired"
        db.commit()
        raise Conflict("The resume changed since this suggestion was made. Request a new suggestion.",
                       code="STALE_VERSION")
    text = (edited_text or "").strip() or sug.suggested_text
    if not text:
        raise ValidationFailed("There's no suggested text to apply.")
    if sug.status == "flagged" and not (edited_text or "").strip():
        raise AppError("This suggestion couldn't be verified against your resume. Edit it yourself before using it.",
                       code="SUGGESTION_UNVERIFIED", status_code=409)
    if len(text) > 300:
        raise ValidationFailed(details={"fields": {"edited_text": "Bullets can be at most 300 characters."}})
    version = db.get(ResumeVersion, sug.resume_version_id)
    assert version is not None
    content = ResumeContent.model_validate(version.content)
    _, entry, bullet = find_bullet(content, sug.bullet_ref["bullet_id"])
    bullet.text = text
    edited = bool((edited_text or "").strip()) and edited_text.strip() != sug.suggested_text
    new_version = save_version(db, user, resume, content, version.id, created_by="user" if edited else "ai_tailor",
                               change_summary=f"{'Edited' if edited else 'Accepted'} rewrite in "
                                              f"{getattr(entry, 'title', None) or getattr(entry, 'name', '')}")
    sug = db.get(RewriteSuggestion, sug.id)
    sug.status, sug.decided_at, sug.applied_version_id = "accepted", utcnow(), new_version.id
    db.commit()
    return new_version
