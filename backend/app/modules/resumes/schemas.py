"""ResumeContent — the validated JSON document stored in resume_versions.content (SRS 5.3.1)."""
from __future__ import annotations

import re
import secrets
import string

from pydantic import BaseModel, ConfigDict, Field, field_validator

DATE_RE = re.compile(r"^(\d{4}(-\d{2})?|Present)$")
_ALPHABET = string.ascii_lowercase + string.digits


def new_id() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(8))


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _date(v):
    if v in (None, ""):
        return None
    v = str(v).strip()
    if not DATE_RE.match(v):
        raise ValueError("Use YYYY, YYYY-MM or Present.")
    return v


class Link(_Base):
    label: str = Field(max_length=40)
    url: str = Field(max_length=300, pattern=r"^https?://\S+$")


class Header(_Base):
    full_name: str = Field(min_length=1, max_length=100)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=20)
    location: str | None = Field(default=None, max_length=100)
    links: list[Link] = Field(default_factory=list, max_length=5)

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        if v and not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", v):
            raise ValueError("Enter a valid email address.")
        return v or None

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        if v and not re.match(r"^[0-9 +\-()]{7,20}$", v):
            raise ValueError("Phone may contain digits, spaces and + - ( ) only (7–20 characters).")
        return v or None


class Bullet(_Base):
    id: str = Field(default_factory=new_id, max_length=12)
    text: str = Field(min_length=1, max_length=300)


class Education(_Base):
    id: str = Field(default_factory=new_id, max_length=12)
    institution: str = Field(min_length=1, max_length=200)
    degree: str | None = Field(default=None, max_length=150)
    field: str | None = Field(default=None, max_length=150)
    start: str | None = None
    end: str | None = None
    score: str | None = Field(default=None, max_length=40)
    details: list[str] = Field(default_factory=list, max_length=10)

    _d = field_validator("start", "end", mode="before")(_date)


class SkillItem(_Base):
    id: str = Field(default_factory=new_id, max_length=12)
    name: str = Field(min_length=1, max_length=80)
    skill_slug: str | None = Field(default=None, max_length=50)
    category: str | None = Field(default=None, max_length=40)


class Experience(_Base):
    id: str = Field(default_factory=new_id, max_length=12)
    title: str = Field(min_length=1, max_length=150)
    organization: str | None = Field(default=None, max_length=150)
    location: str | None = Field(default=None, max_length=100)
    start: str | None = None
    end: str | None = None
    is_current: bool = False
    technologies: list[str] = Field(default_factory=list, max_length=30)
    bullets: list[Bullet] = Field(default_factory=list, max_length=8)

    _d = field_validator("start", "end", mode="before")(_date)


class Project(_Base):
    id: str = Field(default_factory=new_id, max_length=12)
    name: str = Field(min_length=1, max_length=150)
    role: str | None = Field(default=None, max_length=100)
    link: str | None = Field(default=None, max_length=300, pattern=r"^https?://\S+$")
    start: str | None = None
    end: str | None = None
    technologies: list[str] = Field(default_factory=list, max_length=30)
    bullets: list[Bullet] = Field(default_factory=list, max_length=8)

    _d = field_validator("start", "end", mode="before")(_date)


class Certification(_Base):
    id: str = Field(default_factory=new_id, max_length=12)
    name: str = Field(min_length=1, max_length=200)
    issuer: str | None = Field(default=None, max_length=150)
    date: str | None = None
    url: str | None = Field(default=None, max_length=300, pattern=r"^https?://\S+$")

    _d = field_validator("date", mode="before")(_date)


class Achievement(_Base):
    id: str = Field(default_factory=new_id, max_length=12)
    text: str = Field(min_length=1, max_length=300)


SECTIONS = ("education", "skills", "experience", "projects", "certifications", "achievements")


class ResumeContent(_Base):
    schema_version: int = 1
    header: Header
    summary: str | None = Field(default=None, max_length=600)
    education: list[Education] = Field(default_factory=list, max_length=5)
    skills: list[SkillItem] = Field(default_factory=list, max_length=60)
    experience: list[Experience] = Field(default_factory=list, max_length=10)
    projects: list[Project] = Field(default_factory=list, max_length=10)
    certifications: list[Certification] = Field(default_factory=list, max_length=15)
    achievements: list[Achievement] = Field(default_factory=list, max_length=15)
    section_order: list[str] = Field(default_factory=lambda: list(SECTIONS))

    @field_validator("section_order")
    @classmethod
    def _order(cls, v):
        if sorted(v) != sorted(SECTIONS):
            return list(SECTIONS)
        return v


def ensure_ids(content: ResumeContent) -> ResumeContent:
    """Guarantee unique IDs (client-supplied duplicates are replaced)."""
    seen: set[str] = set()

    def fix(obj):
        if not obj.id or obj.id in seen:
            obj.id = new_id()
        seen.add(obj.id)

    for section in (content.education, content.skills, content.certifications, content.achievements):
        for item in section:
            fix(item)
    for entry in [*content.experience, *content.projects]:
        fix(entry)
        for b in entry.bullets:
            fix(b)
    return content


def resume_plain_text(c: ResumeContent) -> str:
    parts = [c.summary or ""]
    parts += [s.name for s in c.skills]
    for e in c.education:
        parts += [e.institution, e.degree or "", e.field or "", *e.details]
    for x in c.experience:
        parts += [x.title, x.organization or "", *x.technologies, *(b.text for b in x.bullets)]
    for p in c.projects:
        parts += [p.name, p.role or "", *p.technologies, *(b.text for b in p.bullets)]
    parts += [f"{c_.name} {c_.issuer or ''}" for c_ in c.certifications]
    parts += [a.text for a in c.achievements]
    return "\n".join(x for x in parts if x)
