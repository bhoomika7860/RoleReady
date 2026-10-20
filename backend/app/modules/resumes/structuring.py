"""Resume text → ResumeContent (W-1 with deterministic safety checks; heuristic fallback)."""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from app.ai import prompts
from app.ai.gateway import AIFailed, AIGateway, untrusted
from app.ai.redaction import redact
from app.ai.schemas import W1Output
from app.ai.textcheck import near_verbatim, normalise, tokens
from app.core.config import get_settings
from app.core.errors import AIQuotaExceeded, AIUnavailableError
from app.modules.catalog.matcher import SkillMatcher
from app.modules.resumes.schemas import (Achievement, Bullet, Certification, Education, Experience, Header, Link,
                                         Project, ResumeContent, SkillItem, ensure_ids)

DATE_TOKEN = re.compile(r"(\d{4})(?:[-/](\d{1,2}))?")
PLACEHOLDER = re.compile(r"\[(EMAIL|PHONE|URL|NAME|ADDRESS)\]")


@dataclass
class StructureResult:
    content: ResumeContent
    status: str  # complete | partial
    warnings: list[str] = field(default_factory=list)
    unparsed: list[str] = field(default_factory=list)
    model: str | None = None


def _norm_date(v: str | None) -> str | None:
    if not v:
        return None
    if re.search(r"present|current|now|ongoing", v, re.IGNORECASE):
        return "Present"
    m = DATE_TOKEN.search(v)
    if not m:
        months = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9,
                  "oct": 10, "nov": 11, "dec": 12}
        return None if not months else None
    year, month = m.group(1), m.group(2)
    if not month:
        mm = re.search(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", v, re.IGNORECASE)
        if mm:
            month = str(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
                        .index(mm.group(1).lower()) + 1)
    if month and 1 <= int(month) <= 12:
        return f"{year}-{int(month):02d}"
    return year


def _clean(s: str | None, limit: int) -> str | None:
    if s is None:
        return None
    s = PLACEHOLDER.sub("", s).strip(" ,;|-•")
    s = re.sub(r"\s+", " ", s)
    return s[:limit] or None


def _header_from(found: dict[str, list[str]], fallback_name: str) -> Header:
    links = []
    for u in found.get("url", [])[:5]:
        url = u if u.lower().startswith("http") else f"https://{u.lstrip('/')}"
        host = (urlsplit(url).hostname or "link").replace("www.", "")
        label = host.split(".")[0].capitalize()[:40]
        if re.match(r"^https?://\S+$", url) and len(url) <= 300:
            links.append(Link(label=label, url=url))
    phone = None
    for p in found.get("phone", []):
        cand = re.sub(r"[^0-9 +\-()]", "", p).strip()
        if 7 <= len(cand) <= 20:
            phone = cand
            break
    email = found.get("email", [None])[0] if found.get("email") else None
    name = (found.get("name") or [fallback_name])[0][:100]
    return Header(full_name=name, email=email, phone=phone, links=links)


def _in_source(text: str | None, source_tokens: list[str], source_norm: str) -> bool:
    if not text:
        return False
    n = normalise(PLACEHOLDER.sub("", text))
    return bool(n) and (n in source_norm or near_verbatim(n, source_tokens, 0.85))


def from_w1(out: W1Output, raw_text: str, found: dict, matcher: SkillMatcher, fallback_name: str) -> StructureResult:
    src_tokens = tokens(raw_text)
    src_norm = normalise(raw_text)
    unparsed = [u for u in out.unparsed_text if u.strip()]
    dropped = 0

    def ok(t: str | None) -> bool:
        return _in_source(t, src_tokens, src_norm)

    def bullets(items: list[str]) -> list[Bullet]:
        nonlocal dropped
        res = []
        for b in items:
            b2 = _clean(b, 1000) or ""
            if not b2:
                continue
            if not ok(b2) or len(b2) > 300 or len(res) >= 8:
                unparsed.append(b2)
                dropped += 1 if not ok(b2) else 0
                continue
            res.append(Bullet(text=b2))
        return res

    def techs(items: list[str]) -> list[str]:
        return [t.strip()[:60] for t in items if t.strip() and (ok(t) or matcher.find(t))][:30]

    education = []
    for e in out.education[:5]:
        inst = _clean(e.institution, 200)
        if not inst or not ok(inst):
            dropped += 1
            continue
        education.append(Education(institution=inst, degree=_clean(e.degree, 150) if ok(e.degree) else None,
                                   field=_clean(e.field, 150) if ok(e.field) else None, start=_norm_date(e.start),
                                   end=_norm_date(e.end), score=_clean(e.score, 40),
                                   details=[d for d in (_clean(x, 300) for x in e.details) if d and ok(d)][:10]))
    experience = []
    for x in out.experience:
        title = _clean(x.title, 150)
        if not title or not ok(title) or len(experience) >= 10:
            dropped += 1
            unparsed.extend(x.bullets)
            continue
        experience.append(Experience(title=title, organization=_clean(x.organization, 150) if ok(x.organization)
                                     else None, location=_clean(x.location, 100), start=_norm_date(x.start),
                                     end=_norm_date(x.end), is_current=bool(x.is_current) or
                                     _norm_date(x.end) == "Present", technologies=techs(x.technologies),
                                     bullets=bullets(x.bullets)))
    projects = []
    for p in out.projects:
        name = _clean(p.name, 150)
        if not name or not ok(name) or len(projects) >= 10:
            dropped += 1
            unparsed.extend(p.bullets)
            continue
        projects.append(Project(name=name, role=_clean(p.role, 100) if ok(p.role) else None,
                                start=_norm_date(p.start), end=_norm_date(p.end), technologies=techs(p.technologies),
                                bullets=bullets(p.bullets)))
    skills = []
    seen = set()
    for s in out.skills:
        s2 = _clean(s, 80)
        if not s2 or s2.lower() in seen or not ok(s2) or len(skills) >= 60:
            continue
        seen.add(s2.lower())
        skills.append(SkillItem(name=s2, skill_slug=matcher.map_phrase(s2)))
    certs = [Certification(name=_clean(c.name, 200) or "", issuer=_clean(c.issuer, 150) if ok(c.issuer) else None,
                           date=_norm_date(c.date))
             for c in out.certifications if _clean(c.name, 200) and ok(c.name)][:15]
    achievements = [Achievement(text=a2) for a2 in (_clean(a, 300) for a in out.achievements) if a2 and ok(a2)][:15]
    summary = _clean(out.summary, 600) if out.summary and ok(out.summary) else None

    content = ensure_ids(ResumeContent(header=_header_from(found, fallback_name), summary=summary,
                                       education=education, skills=skills, experience=experience,
                                       projects=projects, certifications=certs, achievements=achievements))
    warnings = []
    if dropped:
        warnings.append("UNVERIFIED_ITEMS_MOVED")
    return StructureResult(content, "complete", warnings, [u for u in unparsed if u][:60])


HEADINGS = {
    "education": r"education|academic(s| background| qualifications)?|qualifications",
    "skills": r"(technical |key |core )?skills|technologies|tech stack|skills & tools|tools",
    "experience": r"(work |professional )?experience|internships?|employment|work history",
    "projects": r"(academic |personal |key )?projects",
    "certifications": r"certifications?|courses|certificates",
    "achievements": r"achievements|awards|honou?rs|accomplishments|extra[- ]curricular(s| activities)?",
    "summary": r"summary|profile|objective|about me",
}
BULLET_RE = re.compile(r"^\s*([•●▪◦\-*–·]|\d+\.)\s+")


def heuristic(raw_text: str, found: dict, matcher: SkillMatcher, fallback_name: str) -> StructureResult:
    lines = [ln.strip() for ln in raw_text.split("\n")]
    section = None
    buckets: dict[str, list[str]] = {k: [] for k in HEADINGS}
    unparsed: list[str] = []
    for ln in lines:
        if not ln:
            continue
        clean = ln.strip(":").strip()
        matched = None
        if len(clean) <= 40:
            for key, pat in HEADINGS.items():
                if re.fullmatch(pat, clean, re.IGNORECASE):
                    matched = key
                    break
        if matched:
            section = matched
            continue
        (buckets[section] if section else unparsed).append(ln)

    skills = []
    seen = set()
    for ln in buckets["skills"]:
        body = ln.split(":", 1)[-1]
        for part in re.split(r"[,|•;/]", body):
            p = part.strip()
            if 1 < len(p) <= 60 and p.lower() not in seen and len(skills) < 60:
                seen.add(p.lower())
                skills.append(SkillItem(name=p, skill_slug=matcher.map_phrase(p)))

    def entries(blines: list[str], kind: str):
        out_entries: list = []
        current = None
        for ln in blines:
            if BULLET_RE.match(ln) and current is not None:
                text = BULLET_RE.sub("", ln)[:300]
                if text and len(current.bullets) < 8:
                    current.bullets.append(Bullet(text=text))
                continue
            if BULLET_RE.match(ln) and current is None:
                unparsed.append(ln)
                continue
            if current is not None and not current.bullets and len(ln) > 60:
                current.bullets.append(Bullet(text=ln[:300]))
                continue
            if len(out_entries) >= 10:
                unparsed.append(ln)
                continue
            title = ln[:150]
            current = Experience(title=title) if kind == "experience" else Project(name=title)
            current.technologies = [s.name for s in skills if matcher.find(ln) and s.skill_slug in matcher.find(ln)]
            out_entries.append(current)
        return out_entries

    experience = entries(buckets["experience"], "experience")
    projects = entries(buckets["projects"], "project")
    for entry in [*experience, *projects]:
        hits = set()
        for b in entry.bullets:
            hits |= set(matcher.find(b.text))
        entry.technologies = [matcher.by_slug[h].name for h in sorted(hits)][:30]
    education = [Education(institution=ln[:200]) for ln in buckets["education"][:5] if len(ln) > 3]
    unparsed += buckets["education"][5:]
    achievements = [Achievement(text=BULLET_RE.sub("", ln)[:300]) for ln in buckets["achievements"][:15]]
    certs = [Certification(name=BULLET_RE.sub("", ln)[:200]) for ln in buckets["certifications"][:15]]
    summary = " ".join(buckets["summary"])[:600] or None
    content = ensure_ids(ResumeContent(header=_header_from(found, fallback_name), summary=summary,
                                       education=education, skills=skills, experience=experience, projects=projects,
                                       certifications=certs, achievements=achievements))
    return StructureResult(content, "partial", ["AI_FALLBACK"], unparsed[:60])


def structure_text(raw_text: str, matcher: SkillMatcher, gateway: AIGateway, user_id: uuid.UUID | None,
                   fallback_name: str) -> StructureResult:
    red = redact(raw_text)
    found = red.found
    text_for_ai = red.text if get_settings().pii_redaction_enabled else raw_text
    try:
        out = gateway.run(workflow="W-1", prompt_version=prompts.W1_VERSION, system=prompts.W1_SYSTEM,
                          user=untrusted("resume", text_for_ai), output_model=W1Output, user_id=user_id,
                          max_tokens=4000, temperature=0.1, timeout_s=60)
    except (AIUnavailableError, AIQuotaExceeded, AIFailed) as exc:
        res = heuristic(raw_text, found, matcher, fallback_name)
        res.warnings.append(f"AI_REASON:{exc.code}")
        return res
    res = from_w1(out, raw_text, found, matcher, fallback_name)
    res.model = gateway.model_name
    total_items = len(res.content.experience) + len(res.content.projects) + len(res.content.education)
    if total_items == 0 and not res.content.skills:
        fb = heuristic(raw_text, found, matcher, fallback_name)
        fb.warnings.append("AI_EMPTY_RESULT")
        return fb
    return res
