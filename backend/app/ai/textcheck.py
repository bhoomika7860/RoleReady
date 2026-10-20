"""Deterministic text checks used to validate AI output (verbatim quotes, near-verbatim extraction)."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w%+#.]+")


def normalise(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").lower()
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = t.replace("–", "-").replace("—", "-").replace("•", " ")
    return _WS.sub(" ", t).strip()


def tokens(text: str) -> list[str]:
    """Word tokens; dots are kept only inside a token (node.js, 3.5), not at its edges."""
    out = []
    for t in _PUNCT.sub(" ", normalise(text)).split(" "):
        t = t.strip(".")
        if t:
            out.append(t)
    return out


def is_verbatim_quote(quote: str | None, source: str, max_words: int = 25) -> bool:
    """Quote must appear in the source (case/whitespace/punctuation-normalised) and be <= max_words."""
    if not quote:
        return False
    q = tokens(quote)
    if not q or len(q) > max_words:
        return False
    return " " + " ".join(q) + " " in " " + " ".join(tokens(source)) + " "


def near_verbatim(span: str, source_tokens: list[str], threshold: float = 0.85) -> bool:
    """True if `span` matches some window of the source with similarity >= threshold (SRS FR-022)."""
    s = tokens(span)
    if not s:
        return False
    joined_src = " " + " ".join(source_tokens) + " "
    if " " + " ".join(s) + " " in joined_src:
        return True
    n = len(s)
    starts = {s[0], s[1] if n > 1 else s[0], s[-1]}
    best = 0.0
    for i, tok in enumerate(source_tokens):
        if tok not in starts:
            continue
        for begin in (i, i - n + 1, i - 1):
            if begin < 0:
                continue
            window = source_tokens[begin:begin + n + 2]
            ratio = SequenceMatcher(None, s, window, autojunk=False).ratio()
            if ratio > best:
                best = ratio
                if best >= threshold:
                    return True
    return best >= threshold
