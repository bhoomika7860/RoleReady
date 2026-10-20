"""Contact-PII redaction before any resume text is sent to the AI provider (SRS 8.4, NFR-024)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
URL = re.compile(r"(?:https?://|www\.)[^\s|,;<>()]+|(?:linkedin\.com|github\.com|gitlab\.com|leetcode\.com|"
                 r"behance\.net|medium\.com)/[^\s|,;<>()]*", re.IGNORECASE)
PHONE = re.compile(r"(?<![\w])(?:\+?\d{1,3}[\s\-.]?)?(?:\(?\d{2,5}\)?[\s\-.]?)?\d{3,5}[\s\-.]?\d{4,5}(?![\w])")
ADDRESS = re.compile(r"\b\d{1,5}[,\s]+[A-Za-z0-9 .]{2,40}\b(?:Street|St\.|Road|Rd\.|Lane|Avenue|Ave\.|Nagar|"
                     r"Colony|Sector|Block)\b[^\n]{0,60}", re.IGNORECASE)
NAME_LINE = re.compile(r"^[A-Z][a-zA-Z'.\-]+(?:\s+[A-Z][a-zA-Z'.\-]+){1,3}$")


@dataclass
class Redaction:
    text: str
    found: dict[str, list[str]] = field(default_factory=dict)


def _phone_like(s: str) -> bool:
    digits = re.sub(r"\D", "", s)
    return 10 <= len(digits) <= 15


def redact(text: str) -> Redaction:
    found: dict[str, list[str]] = {"email": [], "phone": [], "url": [], "name": [], "address": []}
    out = EMAIL.sub(lambda m: (found["email"].append(m.group(0)), "[EMAIL]")[1], text)
    out = URL.sub(lambda m: (found["url"].append(m.group(0)), "[URL]")[1], out)

    def _phone(m: re.Match) -> str:
        if _phone_like(m.group(0)):
            found["phone"].append(m.group(0).strip())
            return "[PHONE]"
        return m.group(0)

    out = PHONE.sub(_phone, out)
    out = ADDRESS.sub(lambda m: (found["address"].append(m.group(0)), "[ADDRESS]")[1], out)

    # Name: the first non-empty line, if it looks like a person's name.
    lines = out.split("\n")
    for i, line in enumerate(lines[:3]):
        stripped = line.strip()
        if not stripped:
            continue
        if NAME_LINE.match(stripped) and len(stripped) <= 60:
            found["name"].append(stripped)
            lines[i] = line.replace(stripped, "[NAME]")
        break
    out = "\n".join(lines)
    if found["name"]:
        name = found["name"][0]
        out = re.sub(re.escape(name), "[NAME]", out)
    return Redaction(out, found)
