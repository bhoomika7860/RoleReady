"""Deterministic scoring + AI-assisted short-answer evaluation (SRS 5.4, FR-043, FR-044)."""
from __future__ import annotations

import uuid

from app.ai import prompts
from app.ai.gateway import AIGateway, untrusted
from app.ai.schemas import W7ShortOutput
from app.ai.textcheck import is_verbatim_quote
from app.core import scoring_config as sc
from app.core.errors import ValidationFailed
from app.models import OBJECTIVE_TYPES, Question


def source_label(q: Question) -> str:
    if q.source_type == "ai_generated":
        return "AI-generated practice — may contain errors"
    if q.source_type == "curated_general":
        return "Curated practice question" + ("" if q.reviewed_by else " · AI-assisted draft")
    if q.source_type == "candidate_reported":
        return "Reported by candidates — not verified by the company"
    return "From published employer material"


def validate_response(q_type: str, options: list | None, response: dict) -> dict:
    if not isinstance(response, dict):
        raise ValidationFailed(details={"fields": {"response": "Invalid response."}})
    if q_type in OBJECTIVE_TYPES:
        selected = response.get("selected")
        if not isinstance(selected, list) or any(not isinstance(s, str) for s in selected):
            raise ValidationFailed(details={"fields": {"response.selected": "Choose an option."}})
        ids = {o["id"] for o in (options or [])}
        if any(s not in ids for s in selected):
            raise ValidationFailed(details={"fields": {"response.selected": "Unknown option."}})
        if q_type != "mcq_multi" and len(selected) > 1:
            raise ValidationFailed(details={"fields": {"response.selected": "Choose one option."}})
        return {"selected": sorted(set(selected))}
    text = response.get("text")
    if not isinstance(text, str):
        raise ValidationFailed(details={"fields": {"response.text": "Type an answer."}})
    if len(text) > 4000:
        raise ValidationFailed(details={"fields": {"response.text": "Answers can be up to 4,000 characters."}})
    return {"text": text}


def is_answered(q_type: str, response: dict | None) -> bool:
    if not response:
        return False
    if q_type in OBJECTIVE_TYPES:
        return bool(response.get("selected"))
    return bool((response.get("text") or "").strip())


def score_objective(q_type: str, correct: dict, response: dict | None) -> float:
    picked = set((response or {}).get("selected") or [])
    right = set((correct or {}).get("selected") or [])
    if q_type == "mcq_multi":
        if not right:
            return 0.0
        return max(0.0, (len(picked & right) - len(picked - right)) / len(right))
    return 1.0 if picked and picked == right else 0.0


def word_count(text: str) -> int:
    return len((text or "").split())


def evaluate_short(gateway: AIGateway, q: Question, answer: str, user_id: uuid.UUID | None,
                   role_name: str) -> dict:
    """Returns {score, evaluation}; raises AI errors for the caller to record as failed (never as zero)."""
    rubric = q.rubric or {"key_points": []}
    kps = rubric["key_points"]
    if word_count(answer) < sc.SHORT_ANSWER_MIN_WORDS:
        return {"score": 0.0, "evaluation": {
            "too_short": True, "key_points": [{**kp, "credit": "missing", "quote": None, "quote_verified": False}
                                              for kp in kps],
            "feedback": f"Answers need at least {sc.SHORT_ANSWER_MIN_WORDS} words to be evaluated. "
                        "Explain the idea in a few sentences.", "method": "deterministic"}}
    rubric_text = "\n".join(f"- {kp['id']}: {kp['text']}" for kp in kps)
    user_msg = (f"Role: {role_name}\nQuestion:\n{q.prompt}\n\nRubric key points:\n{rubric_text}\n\n"
                f"Reference answer (for the grader only):\n{q.reference_answer or ''}\n\n"
                + untrusted("candidate_answer", answer))
    out = gateway.run(workflow="W-7", prompt_version=prompts.W7S_VERSION, system=prompts.W7S_SYSTEM, user=user_msg,
                      output_model=W7ShortOutput, user_id=user_id, max_tokens=900, temperature=0.2)
    judged = {j.id: j for j in out.key_points}
    points = []
    total = 0.0
    for kp in kps:
        j = judged.get(kp["id"])
        credit, quote, verified = "missing", None, False
        if j is not None and j.credit != "missing":
            if is_verbatim_quote(j.quote, answer):
                credit, quote, verified = j.credit, j.quote, True
            # credit without a verifiable quote is downgraded to missing (prompt-injection defence)
        total += kp["weight"] * sc.KEY_POINT_CREDIT[credit]
        points.append({**kp, "credit": credit, "quote": quote, "quote_verified": verified})
    return {"score": round(min(1.0, total), 3), "evaluation": {
        "key_points": points, "feedback": out.feedback, "method": "ai_rubric", "model": gateway.model_name,
        "rubric_version": rubric.get("version", sc.RUBRIC_VERSION_SHORT)}}
