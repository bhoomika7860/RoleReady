"""Requirement coverage — deterministic, reproducible (SRS 5.3.2, FR-026, FR-027, 9.2 PE).

Resume evidence is about what the document SHOWS. Absence is worded as "not shown on your resume",
never as a lack of ability; demonstrated ability is measured separately by assessments/practice.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.scoring_config import (EVIDENCE_LEVEL_CREDIT, EVIDENCE_LEVEL_LABEL, EVIDENCE_LEVEL_STATE,
                                     QUANTIFIED_UNITS, REQUIREMENT_WEIGHT, SCORING_VERSION)
from app.models import Resume, ResumeAnalysis, ResumeVersion, SkillEvidence, TargetRole
from app.modules.catalog.matcher import SkillMatcher, get_matcher
from app.modules.resumes.schemas import ResumeContent, resume_plain_text
from app.modules.targets.requirements import Req, load_requirements, requirements_hash

_units = "|".join(re.escape(u) for u in sorted(QUANTIFIED_UNITS, key=len, reverse=True))
QUANTIFIED = re.compile(rf"\d[\d,.]*\s*(?:\+\s*)?(?:{_units})(?![A-Za-z])", re.IGNORECASE)
STOP = {"and", "or", "the", "a", "an", "of", "with", "in", "on", "for", "to", "experience", "knowledge",
        "understanding", "familiarity", "good", "strong", "basic", "working", "ability", "skills", "skill", "using"}


def is_quantified(text: str) -> bool:
    return bool(QUANTIFIED.search(text or ""))


@dataclass
class Location:
    section: str
    entry_id: str | None
    bullet_id: str | None
    entry_name: str | None
    text: str

    def as_dict(self) -> dict:
        return {"section": self.section, "entry_id": self.entry_id, "bullet_id": self.bullet_id,
                "entry_name": self.entry_name, "text": self.text[:300]}


def skill_level(slug: str, c: ResumeContent, m: SkillMatcher) -> tuple[int, list[Location], bool]:
    """Returns (level 0–3, locations, used_with_outcome)."""
    listed: list[Location] = []
    for s in c.skills:
        if s.skill_slug == slug or m.matches(slug, s.name):
            listed.append(Location("skills", s.id, None, None, s.name))
    if c.summary and m.matches(slug, c.summary):
        listed.append(Location("summary", None, None, None, c.summary))
    for cert in c.certifications:
        if m.matches(slug, f"{cert.name} {cert.issuer or ''}"):
            listed.append(Location("certifications", cert.id, None, cert.name, cert.name))

    used: list[Location] = []
    entries_used: set[str] = set()
    quantified = False
    for section, entries in (("experience", c.experience), ("projects", c.projects)):
        for e in entries:
            name = getattr(e, "name", None) or getattr(e, "title", None)
            hit = False
            for t in e.technologies:
                if m.matches(slug, t):
                    used.append(Location(section, e.id, None, name, f"Technologies: {', '.join(e.technologies)}"))
                    hit = True
                    break
            for b in e.bullets:
                if m.matches(slug, b.text):
                    used.append(Location(section, e.id, b.id, name, b.text))
                    hit = True
                    if is_quantified(b.text):
                        quantified = True
            if hit:
                entries_used.add(e.id)
    if used:
        level = 3 if (len(entries_used) >= 2 or quantified) else 2
        return level, used + listed, quantified
    if listed:
        return 1, listed, False
    return 0, [], False


def phrase_level(phrase: str, plain: str) -> int:
    toks = [t for t in re.findall(r"[a-z0-9+#.]+", phrase.lower()) if t not in STOP and len(t) > 1]
    if not toks:
        return 0
    low = plain.lower()
    return 1 if all(re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", low) for t in toks) else 0


def _explain(r: Req, level: int, locs: list[Location]) -> str:
    name = r.skill_name or r.raw_phrase
    used_names = sorted({loc.entry_name for loc in locs if loc.section in ("experience", "projects")
                         and loc.entry_name})
    if level == 3:
        return f"{name} appears in the work of {len(used_names)} entr{'y' if len(used_names) == 1 else 'ies'} " \
               f"({', '.join(used_names[:3])})" + (" with a measured outcome." if len(used_names) < 2 else ".")
    if level == 2:
        return f"{name} is shown being used in {', '.join(used_names[:2]) or 'one entry'}."
    if level == 1:
        where = sorted({loc.section for loc in locs})
        return f"{name} is listed ({', '.join(where)}) but not shown in a project or experience bullet."
    return f"{name} isn't shown on your resume. That doesn't mean you lack it — an assessment can show it."


def _suggest(r: Req, level: int, demonstrated: bool) -> dict | None:
    name = r.skill_name or r.raw_phrase
    if level == 0 and not demonstrated:
        return {"type": "demonstrate_first",
                "text": f"Take a short checkpoint on {name} to find out where you stand. If you have used it in a "
                        f"project, you could also mention it there."}
    if level <= 1:
        return {"type": "add_to_project",
                "text": f"If you used {name} in a project or internship, mention it in that entry's bullets."}
    if level == 2:
        return {"type": "quantify",
                "text": f"If you measured a result where you used {name}, consider adding it to that bullet."}
    return None


def analyse(content: ResumeContent, reqs: list[Req], m: SkillMatcher,
            demonstrated_slugs: set[str] | None = None) -> dict:
    demonstrated_slugs = demonstrated_slugs or set()
    plain = resume_plain_text(content)
    rows = []
    num = den = 0.0
    for r in reqs:
        if r.category != "skill":
            continue
        if r.skill_slug:
            level, locs, _ = skill_level(r.skill_slug, content, m)
        else:
            level, locs = phrase_level(r.raw_phrase, plain), []
        w = REQUIREMENT_WEIGHT[r.importance]
        num += w * EVIDENCE_LEVEL_CREDIT[level]
        den += w
        rows.append({
            "requirement_id": str(r.id), "skill": {"slug": r.skill_slug, "name": r.skill_name} if r.skill_slug
            else None, "raw_phrase": r.raw_phrase, "importance": r.importance, "origin": r.origin, "level": level,
            "state": EVIDENCE_LEVEL_STATE[level], "label": EVIDENCE_LEVEL_LABEL[level],
            "explanation": _explain(r, level, locs), "locations": [loc.as_dict() for loc in locs[:5]],
            "suggestion": _suggest(r, level, (r.skill_slug or "") in demonstrated_slugs)})
    coverage = round(100 * num / den) if den else 0

    # Project & experience evidence (SRS 9.2 PE)
    core = [r for r in reqs if r.importance == "core" and r.skill_slug]
    core_levels = {r.skill_slug: next(x["level"] for x in rows if x["requirement_id"] == str(r.id)) for r in core}
    entries_with_core = 0
    for e in [*content.experience, *content.projects]:
        texts = [*e.technologies, *(b.text for b in e.bullets)]
        if any(m.matches(r.skill_slug, t) for r in core for t in texts if r.skill_slug):
            entries_with_core += 1
    q = sum(1 for e in [*content.experience, *content.projects] for b in e.bullets if is_quantified(b.text))
    cc = (sum(1 for lv in core_levels.values() if lv >= 2) / len(core_levels)) if core_levels else 0.0
    pe = round(100 * (0.5 * min(1, entries_with_core / 2) + 0.3 * cc + 0.2 * min(1, q / 2)))
    counts = {state: sum(1 for x in rows if x["state"] == state) for state in ("evidenced", "weak", "not_shown")}
    return {"coverage_score": coverage, "pe_score": pe, "requirements": rows, "counts": counts,
            "formula": "Coverage = round(100 × Σ w·f(level) / Σ w); w: core 3, required 2, preferred 1; "
                       "f: not shown 0, listed only 0.4, used 0.8, used with depth 1.0",
            "pe_inputs": {"entries_with_core_skill": entries_with_core, "core_share_used": round(cc, 2),
                          "quantified_bullets": q}}


def run_analysis(db: Session, user_id, target: TargetRole, resume: Resume,
                 version: ResumeVersion | None = None) -> ResumeAnalysis:
    """Persist an analysis and replace this target's resume-sourced evidence in the same transaction."""
    version = version or db.get(ResumeVersion, resume.current_version_id)
    assert version is not None
    content = ResumeContent.model_validate(version.content)
    reqs = load_requirements(db, target, scored_only=True)
    m = get_matcher(db)
    measured_ids = set(db.scalars(select(SkillEvidence.skill_id).where(
        SkillEvidence.user_id == user_id, SkillEvidence.source_type != "resume",
        SkillEvidence.skill_id.is_not(None))).all())
    demonstrated = {r.skill_slug for r in reqs if r.skill_slug and r.skill_id in measured_ids}
    result = analyse(content, reqs, m, demonstrated)
    analysis = ResumeAnalysis(user_id=user_id, target_id=target.id, resume_id=resume.id,
                              resume_version_id=version.id, requirements_hash=requirements_hash(reqs),
                              coverage_score=result["coverage_score"], pe_score=result["pe_score"], result=result,
                              scoring_version=SCORING_VERSION)
    db.add(analysis)
    db.flush()
    db.execute(delete(SkillEvidence).where(SkillEvidence.user_id == user_id, SkillEvidence.target_id == target.id,
                                           SkillEvidence.source_type == "resume"))
    by_id = {str(r.id): r for r in reqs}
    from app.core.db import bulk_insert
    from app.core.security import utcnow
    now = utcnow()
    bulk_insert(db, SkillEvidence, [
        {"id": uuid.uuid4(), "user_id": user_id, "target_id": target.id, "skill_id": by_id[row["requirement_id"]].skill_id,
         "source_type": "resume", "resume_level": row["level"], "resume_analysis_id": analysis.id,
         "difficulty_weight": 1, "incomplete_attempt": False, "observed_at": now}
        for row in result["requirements"] if by_id[row["requirement_id"]].skill_id is not None])
    db.commit()
    return analysis
