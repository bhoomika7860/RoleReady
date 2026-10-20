"""Deterministic anti-fabrication check for AI rewrites (SRS 5.3.3).

A suggestion may only use facts from the allowed fact set F: the original bullet, the same entry's
title/organisation/technologies/other bullets, and the user's answers to clarifying questions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.ai.textcheck import normalise
from app.modules.catalog.matcher import SkillMatcher

NUMBER_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
                "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
                "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17", "eighteen": "18",
                "nineteen": "19", "twenty": "20", "hundred": "100", "thousand": "1000", "million": "1000000",
                "double": "2x", "triple": "3x", "doubled": "2x", "tripled": "3x", "halved": "50%"}
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*\s*(?:%|x\b|k\b|\+)?", re.IGNORECASE)
CLAIM_WORDS = ("certified", "certification", "award", "awarded", "winner", "won", "patent", "published",
               "led a team", "team of", "managed", "mentored", "production", "promoted", "ranked", "top ")
COMMON_CAPITALISED = {
    "built", "developed", "designed", "implemented", "created", "led", "improved", "reduced", "increased",
    "optimised", "optimized", "automated", "integrated", "deployed", "wrote", "added", "migrated", "refactored",
    "engineered", "launched", "delivered", "collaborated", "analysed", "analyzed", "maintained", "tested",
    "configured", "used", "enabled", "streamlined", "established", "a", "an", "the", "and", "for", "with",
    "using", "via", "on", "in", "to", "of", "by", "api", "apis", "rest", "restful", "ui", "ux", "crud", "json",
    "http", "https", "sql", "orm", "jwt", "oauth", "html", "css", "ci", "cd", "ml", "ai", "nlp", "etl",
    "dashboard", "backend", "frontend", "web", "app", "application", "system", "service", "services",
    "database", "server", "client", "users", "students", "college", "university", "campus", "project", "team",
}


@dataclass
class GuardReport:
    ok: bool
    violations: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"ok": self.ok, "violations": self.violations}


def _numbers(text: str) -> set[str]:
    nums = {re.sub(r"\s+", "", m.group(0)).lower().replace(",", "") for m in NUMBER_RE.finditer(text)}
    words = re.findall(r"[a-z]+", text.lower())
    nums |= {NUMBER_WORDS[w] for w in words if w in NUMBER_WORDS}
    return nums


def _bare(n: str) -> str:
    return re.sub(r"[^\d.]", "", n)


def _proper_nouns(text: str) -> set[str]:
    out: set[str] = set()
    for sentence in re.split(r"(?<=[.!?;])\s+", text):
        words = re.findall(r"[A-Za-z][A-Za-z0-9.+#\-]*", sentence)
        for i, w in enumerate(words):
            if i == 0:
                continue
            if (w[0].isupper() or any(c.isupper() for c in w[1:])) and w.lower().strip(".") not in COMMON_CAPITALISED:
                out.add(w.strip("."))
    return out


def check(suggestion: str, allowed_facts: list[str], matcher: SkillMatcher) -> GuardReport:
    allowed = " \n ".join(a for a in allowed_facts if a)
    allowed_norm = normalise(allowed)
    v: list[str] = []

    # shape
    if len(suggestion) > 300:
        v.append("shape:too_long")
    if "[" in suggestion or "]" in suggestion:
        v.append("shape:placeholder")
    if re.search(r"https?://|www\.", suggestion, re.IGNORECASE):
        v.append("shape:url")
    if re.search(r"\b(I|me|my|we|our)\b", suggestion):
        v.append("shape:first_person")

    # numbers
    allowed_nums = {_bare(n) for n in _numbers(allowed)}
    for n in _numbers(suggestion):
        if _bare(n) and _bare(n) not in allowed_nums:
            v.append(f"number:{n}")

    # technologies (taxonomy aliases)
    sug_skills = set(matcher.find(suggestion))
    allowed_skills = set(matcher.find(allowed))
    for slug in sorted(sug_skills - allowed_skills):
        v.append(f"technology:{slug}")

    # proper nouns
    allowed_tokens = set(re.findall(r"[a-z0-9.+#\-]+", allowed_norm))
    for noun in sorted(_proper_nouns(suggestion)):
        low = noun.lower()
        if low not in allowed_tokens and low not in allowed_norm:
            v.append(f"proper_noun:{noun}")

    # claim words
    sug_norm = normalise(suggestion)
    for word in CLAIM_WORDS:
        if word in sug_norm and word not in allowed_norm:
            v.append(f"claim:{word.strip()}")

    return GuardReport(ok=not v, violations=sorted(set(v)))
