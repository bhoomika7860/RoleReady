"""Closed skill taxonomy + alias matching (SRS 5.3.2, W-2 pre-pass).

Aliases are matched case-insensitively on alphanumeric boundaries. An alias prefixed with "=" is
case-sensitive (e.g. "=REST" so the English word "rest" doesn't count as REST APIs).
"""
from __future__ import annotations

import re
import threading
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Skill


@dataclass(frozen=True)
class SkillInfo:
    id: uuid.UUID
    slug: str
    name: str
    category: str
    patterns: tuple[re.Pattern, ...]


def _compile(alias: str) -> re.Pattern:
    case_sensitive = alias.startswith("=")
    term = alias[1:] if case_sensitive else alias
    pattern = r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9+#])"
    return re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)


class SkillMatcher:
    def __init__(self, skills: list[SkillInfo]):
        self.skills = skills
        self.by_slug = {s.slug: s for s in skills}
        self.by_id = {s.id: s for s in skills}

    @classmethod
    def from_db(cls, db: Session) -> "SkillMatcher":
        rows = db.scalars(select(Skill).where(Skill.is_active)).all()
        infos = []
        for r in rows:
            aliases = list(dict.fromkeys([r.name, *(r.aliases or [])]))
            infos.append(SkillInfo(r.id, r.slug, r.name, r.category, tuple(_compile(a) for a in aliases if a)))
        return cls(infos)

    def find(self, text: str) -> dict[str, list[tuple[int, int]]]:
        """slug -> list of (start, end) match spans."""
        hits: dict[str, list[tuple[int, int]]] = {}
        if not text:
            return hits
        for s in self.skills:
            spans = [(m.start(), m.end()) for p in s.patterns for m in p.finditer(text)]
            if spans:
                hits[s.slug] = sorted(spans)
        return hits

    def matches(self, slug: str, text: str) -> bool:
        info = self.by_slug.get(slug)
        return bool(info and text and any(p.search(text) for p in info.patterns))

    def map_phrase(self, phrase: str) -> str | None:
        """Best single skill for a requirement phrase (longest alias match wins)."""
        best, best_len = None, 0
        for s in self.skills:
            for p in s.patterns:
                m = p.search(phrase or "")
                if m and (m.end() - m.start()) > best_len:
                    best, best_len = s.slug, m.end() - m.start()
        return best


_cache: SkillMatcher | None = None
_lock = threading.Lock()


def get_matcher(db: Session) -> SkillMatcher:
    global _cache
    with _lock:
        if _cache is None:
            _cache = SkillMatcher.from_db(db)
        return _cache


def reset_matcher() -> None:
    global _cache
    with _lock:
        _cache = None
