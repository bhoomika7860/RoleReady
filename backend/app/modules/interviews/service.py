"""Typed mock interviews with rubric feedback (SRS 5.9, FR-090–097)."""
from __future__ import annotations

import json
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import fact_guard, prompts
from app.ai.gateway import AIFailed, AIGateway, untrusted
from app.ai.redaction import redact
from app.ai.schemas import W7InterviewOutput
from app.ai.textcheck import is_verbatim_quote
from app.core import scoring_config as sc
from app.core.errors import AIQuotaExceeded, AIUnavailableError, AppError, Conflict, ValidationFailed
from app.core.security import utcnow
from app.models import (INTERVIEW_DIMENSIONS, InterviewSession, InterviewTurn, Question, ResumeVersion, Role, Skill,
                        SkillEvidence, SkillGap, TargetRole, User)
from app.modules.assessments.scoring import source_label
from app.modules.catalog.matcher import get_matcher
from app.modules.evidence.engine import latest_report, primary_resume
from app.modules.resumes.schemas import ResumeContent
from app.modules.targets.requirements import load_requirements

TEMPLATES = yaml.safe_load((Path(__file__).resolve().parents[2] / "seed" / "interview_templates.yaml")
                           .read_text(encoding="utf-8"))
DISCLAIMER = "AI feedback on answer content only; it cannot judge tone, confidence or body language."


class InterviewError(AppError):
    status_code = 422


def _interview_pool(db: Session, skill_id: uuid.UUID) -> list[Question]:
    qs = db.scalars(select(Question).where(Question.skill_id == skill_id, Question.status == "active",
                                           Question.owner_user_id.is_(None), Question.purpose == "interview")
                    .order_by(Question.slug)).all()
    if not qs:  # fallback: any curated short-answer item for the skill
        qs = db.scalars(select(Question).where(Question.skill_id == skill_id, Question.status == "active",
                                               Question.owner_user_id.is_(None),
                                               Question.type.in_(("short_answer", "approach")))
                        .order_by(Question.slug)).all()
    return list(qs)


def _default_skill(db: Session, user: User, target: TargetRole) -> Skill | None:
    rep = latest_report(db, user, target)
    gaps = db.scalars(select(SkillGap).where(SkillGap.gap_report_id == rep.id, SkillGap.skill_id.is_not(None),
                                             SkillGap.gap_type.in_(("G2", "G3", "G5")))
                      .order_by(SkillGap.rank)).all()
    for g in gaps:
        if _interview_pool(db, g.skill_id):
            return db.get(Skill, g.skill_id)
    for r in load_requirements(db, target, scored_only=True):
        if r.skill_id and _interview_pool(db, r.skill_id):
            return db.get(Skill, r.skill_id)
    return None


def _project_entries(db: Session, user: User) -> tuple[ResumeVersion | None, list[dict]]:
    resume = primary_resume(db, user.id)
    if resume is None or resume.current_version_id is None:
        return None, []
    v = db.get(ResumeVersion, resume.current_version_id)
    c = ResumeContent.model_validate(v.content)
    entries = [{"id": p.id, "name": p.name, "kind": "project", "technologies": p.technologies,
                "bullets": [b.text for b in p.bullets]} for p in c.projects]
    entries += [{"id": e.id, "name": f"your {e.title} role" + (f" at {e.organization}" if e.organization else ""),
                 "kind": "experience", "technologies": e.technologies, "bullets": [b.text for b in e.bullets]}
                for e in c.experience]
    return v, entries


def _roots(db: Session, session: InterviewSession) -> list[InterviewTurn]:
    return db.scalars(select(InterviewTurn).where(InterviewTurn.session_id == session.id,
                                                  InterviewTurn.parent_turn_id.is_(None))
                      .order_by(InterviewTurn.sequence)).all()


def _next_sequence(db: Session, session: InterviewSession) -> int:
    return (db.scalar(select(func.max(InterviewTurn.sequence)).where(InterviewTurn.session_id == session.id)) or 0) + 1


def new_question_turn(db: Session, user: User, session: InterviewSession) -> InterviewTurn:
    roots = _roots(db, session)
    if len(roots) >= session.max_questions:
        raise Conflict(f"This session already has {session.max_questions} questions. End it and start a new one.",
                       code="SESSION_FULL")
    seq = _next_sequence(db, session)
    if session.type == "project":
        version, entries = _project_entries(db, user)
        if not entries:
            raise InterviewError("Add at least one project or experience entry to your resume for project questions.",
                                 code="NO_PROJECTS_ON_RESUME")
        k = len(roots)
        entry = entries[k % len(entries)]
        tpl = TEMPLATES["templates"][k % len(TEMPLATES["templates"])]
        turn = InterviewTurn(session_id=session.id, user_id=user.id, sequence=seq, question_id=None, skill_id=None,
                             question_text=tpl["text"].format(name=entry["name"]), source_type="resume_template",
                             source_label="Built from your resume",
                             project_entry_ref={"resume_version_id": str(version.id), "entry_id": entry["id"],
                                                "template_id": tpl["id"], "template_version": TEMPLATES["version"]})
    else:
        pool = _interview_pool(db, session.skill_id)
        if not pool:
            raise InterviewError("There are no interview questions for this skill yet.", code="INSUFFICIENT_QUESTIONS")
        asked = dict(db.execute(select(InterviewTurn.question_id, func.max(InterviewTurn.created_at))
                                .where(InterviewTurn.user_id == user.id, InterviewTurn.question_id.is_not(None))
                                .group_by(InterviewTurn.question_id)).all())
        in_session = {t.question_id for t in roots}
        cands = [q for q in pool if q.id not in in_session] or pool
        cands.sort(key=lambda q: (0 if q.id not in asked else 1, asked[q.id].timestamp() if q.id in asked else 0,
                                  q.slug or ""))
        q = cands[0]
        label = source_label(q) + (" · repeated question" if q.id in asked else "")
        turn = InterviewTurn(session_id=session.id, user_id=user.id, sequence=seq, question_id=q.id,
                             skill_id=q.skill_id, question_text=q.prompt, source_type=q.source_type,
                             source_label=label[:80])
    db.add(turn)
    session.last_activity_at = utcnow()
    db.commit()
    return turn


def start(db: Session, user: User, target: TargetRole, itype: str, skill_slug: str | None) -> InterviewSession:
    skill = None
    if itype == "technical":
        if skill_slug:
            skill = db.scalar(select(Skill).where(Skill.slug == skill_slug))
            if skill is None or skill.id not in {r.skill_id for r in load_requirements(db, target, scored_only=True)}:
                raise ValidationFailed(details={"fields": {"skill_slug": "Choose a skill from your requirements."}})
        else:
            skill = _default_skill(db, user, target)
        if skill is None or not _interview_pool(db, skill.id):
            raise InterviewError("There are no interview questions for this skill yet.", code="INSUFFICIENT_QUESTIONS")
    elif itype == "project":
        if not _project_entries(db, user)[1]:
            raise InterviewError("Add at least one project or experience entry to your resume for project questions.",
                                 code="NO_PROJECTS_ON_RESUME")
    else:
        raise ValidationFailed(details={"fields": {"type": "Behavioural interviews aren't available yet."}})
    s = InterviewSession(user_id=user.id, target_id=target.id, type=itype, skill_id=skill.id if skill else None,
                         status="open", max_questions=sc.INTERVIEW_MAX_QUESTIONS, rubric_version=sc.RUBRIC_VERSION_INTERVIEW)
    db.add(s)
    db.flush()
    new_question_turn(db, user, s)
    return s


def lazy_abandon(db: Session, session: InterviewSession) -> None:
    if session.status == "open" and session.last_activity_at < utcnow() - timedelta(hours=sc.INTERVIEW_INACTIVITY_HOURS):
        session.status = "abandoned"
        db.commit()


def submit_answer(db: Session, user: User, session: InterviewSession, turn: InterviewTurn, text: str, mode: str,
                  gateway: AIGateway) -> InterviewTurn:
    if turn.answer_text is not None:
        raise Conflict("This question has already been answered. Use Retry to answer it again.",
                       code="TURN_ALREADY_ANSWERED")
    text = (text or "").strip()
    if not 20 <= len(text) <= 12000:
        raise ValidationFailed(details={"fields": {"answer_text": "Answers must be 20–12,000 characters."}})
    if session.status == "abandoned":
        session.status = "open"  # reopening an abandoned session is allowed
    turn.answer_text, turn.input_mode, turn.answered_at = text, mode, utcnow()
    session.last_activity_at = utcnow()
    if len(text.split()) < sc.INTERVIEW_MIN_WORDS:
        turn.evaluation_status = "too_short"
        turn.feedback = {"message": f"Answers need at least {sc.INTERVIEW_MIN_WORDS} words to be evaluated. "
                                    "Try explaining your reasoning in a few more sentences.", "disclaimer": DISCLAIMER}
        db.commit()
        return turn
    turn.evaluation_status = "pending"
    db.commit()  # the answer is durable before the evaluator is called (FR-092)
    evaluate(db, user, session, turn, gateway)
    return turn


def _entry_facts(db: Session, turn: InterviewTurn) -> tuple[dict | None, list[str]]:
    ref = turn.project_entry_ref or {}
    v = db.get(ResumeVersion, uuid.UUID(ref["resume_version_id"])) if ref.get("resume_version_id") else None
    if v is None:
        return None, []
    c = ResumeContent.model_validate(v.content)
    for p in c.projects:
        if p.id == ref.get("entry_id"):
            return {"name": p.name, "technologies": p.technologies, "bullets": [b.text for b in p.bullets]}, \
                [p.name, *p.technologies, *(b.text for b in p.bullets)]
    for e in c.experience:
        if e.id == ref.get("entry_id"):
            return {"title": e.title, "organization": e.organization, "technologies": e.technologies,
                    "bullets": [b.text for b in e.bullets]}, \
                [e.title, e.organization or "", *e.technologies, *(b.text for b in e.bullets)]
    return None, []


def evaluate(db: Session, user: User, session: InterviewSession, turn: InterviewTurn, gateway: AIGateway) -> None:
    target = db.get(TargetRole, session.target_id)
    role = db.get(Role, target.role_id)
    q = db.get(Question, turn.question_id) if turn.question_id else None
    entry, facts = _entry_facts(db, turn) if session.type == "project" else (None, [])
    context = [f"Question:\n{turn.question_text}"]
    if q is not None and q.rubric:
        context.append("Reference key points (for the grader only):\n" +
                       "\n".join(f"- {kp['id']}: {kp['text']}" for kp in q.rubric["key_points"]))
    if entry is not None:
        context.append(untrusted("resume_entry", redact(json.dumps(entry, ensure_ascii=False)).text))
    context.append(untrusted("candidate_answer", turn.answer_text or ""))
    system = prompts.W7I_SYSTEM.format(role_name=role.name, interview_type=session.type,
                                       example_rule=prompts.EXAMPLE_RULE_PROJECT if session.type == "project"
                                       else prompts.EXAMPLE_RULE_TECHNICAL)
    try:
        out = gateway.run(workflow="W-7", prompt_version=prompts.W7I_VERSION, system=system,
                          user="\n\n".join(context), output_model=W7InterviewOutput, user_id=user.id,
                          max_tokens=1600, temperature=0.2)
    except (AIFailed, AIUnavailableError, AIQuotaExceeded) as exc:
        turn.evaluation_status = "failed"  # the answer stays saved; no score is recorded
        turn.feedback = {"error": exc.code, "message": "Feedback unavailable right now — your answer is saved.",
                         "disclaimer": DISCLAIMER}
        db.commit()
        return

    answer = turn.answer_text or ""
    scores: dict[str, dict] = {}
    for dim in INTERVIEW_DIMENSIONS:
        d = getattr(out.dimensions, dim)
        score, quote, verified, note = d.score, d.quote, True, None
        if quote is None:
            if score > 1:
                score, verified, note = min(score, 2), False, "No supporting quote was given, so the score is capped at 2."
        elif not is_verbatim_quote(quote, answer, max_words=25):
            score, quote, verified, note = min(score, 2), None, False, \
                "The evaluator's quote didn't match your answer, so the score is capped at 2."
        scores[dim] = {"score": score, "quote": quote, "quote_verified": verified, "comment": d.comment, "note": note}
    overall = round(sum(v["score"] for v in scores.values()) / len(scores) * 20)

    example = (out.example_answer or "").strip() or None
    example_note = "Example answer — general guidance, not a statement about your own experience."
    if example and session.type == "project":
        report = fact_guard.check(example[:300] if len(example) <= 300 else example, [answer, *facts],
                                  get_matcher(db))
        bad = [v for v in report.violations if v.startswith(("number:", "proper_noun:", "technology:", "claim:"))]
        if bad:
            example = None
            example_note = "An example answer was withheld because it included details you haven't mentioned."
        else:
            example_note = "Example structure using only facts from your answer and resume; fill in the [brackets]."

    turn.rubric_scores = scores
    turn.overall_score = overall
    turn.feedback = {"strengths": out.strengths[:3], "missing_concepts": out.missing_concepts[:5],
                     "improvements": out.improvements[:4], "example_answer": example, "example_note": example_note,
                     "disclaimer": DISCLAIMER, "model": gateway.model_name}
    turn.evaluation_status = "scored"
    turn.prompt_version = prompts.W7I_VERSION
    db.flush()
    if session.type == "technical" and turn.skill_id:
        db.add(SkillEvidence(user_id=user.id, target_id=target.id, skill_id=turn.skill_id, source_type="interview",
                             score=Decimal(str(round(overall / 100, 3))),
                             difficulty_weight=Decimal(str(sc.INTERVIEW_DIFFICULTY_WEIGHT)), item_type="interview",
                             interview_turn_id=turn.id))
    for dim, v in scores.items():
        db.add(SkillEvidence(user_id=user.id, target_id=target.id, interview_dimension=dim, source_type="interview",
                             score=Decimal(str(round(v["score"] / 5, 3))), interview_turn_id=turn.id))
    db.commit()


def retry(db: Session, user: User, session: InterviewSession, turn: InterviewTurn) -> InterviewTurn:
    root_id = turn.parent_turn_id or turn.id
    attempts = db.scalar(select(func.count()).select_from(InterviewTurn).where(
        (InterviewTurn.id == root_id) | (InterviewTurn.parent_turn_id == root_id))) or 0
    if attempts >= sc.INTERVIEW_MAX_ATTEMPTS:
        raise Conflict(f"You can answer a question at most {sc.INTERVIEW_MAX_ATTEMPTS} times per session.",
                       code="RETRY_LIMIT")
    if turn.answer_text is None:
        raise Conflict("Answer this question before retrying it.", code="TURN_NOT_ANSWERED")
    root = db.get(InterviewTurn, root_id)
    new = InterviewTurn(session_id=session.id, user_id=user.id, sequence=_next_sequence(db, session),
                        question_id=root.question_id, skill_id=root.skill_id, question_text=root.question_text,
                        source_type=root.source_type, source_label=root.source_label,
                        project_entry_ref=root.project_entry_ref, parent_turn_id=root.id,
                        attempt_number=attempts + 1)
    db.add(new)
    session.last_activity_at = utcnow()
    if session.status == "abandoned":
        session.status = "open"
    db.commit()
    return new


def previous_attempt(db: Session, turn: InterviewTurn) -> InterviewTurn | None:
    if turn.parent_turn_id is None:
        return None
    root_id = turn.parent_turn_id
    return db.scalar(select(InterviewTurn).where(
        ((InterviewTurn.id == root_id) | (InterviewTurn.parent_turn_id == root_id)),
        InterviewTurn.attempt_number == turn.attempt_number - 1))


def delta(prev: InterviewTurn | None, turn: InterviewTurn, session: InterviewSession) -> dict | None:
    """Per-dimension change — only between attempts of the same question under the same rubric (SRS 9.6)."""
    if prev is None or prev.evaluation_status != "scored" or turn.evaluation_status != "scored":
        return None
    if prev.question_text != turn.question_text:
        return None
    dims = {d: turn.rubric_scores[d]["score"] - prev.rubric_scores[d]["score"] for d in INTERVIEW_DIMENSIONS}
    return {"overall": turn.overall_score - prev.overall_score, "dimensions": dims,
            "previous_overall": prev.overall_score, "rubric_version": session.rubric_version,
            "comparable": True, "note": "Same question and rubric — this compares your two answers, not your "
                                        "overall skill."}


def end(db: Session, session: InterviewSession) -> dict:
    turns = db.scalars(select(InterviewTurn).where(InterviewTurn.session_id == session.id,
                                                   InterviewTurn.evaluation_status == "scored")).all()
    summary = {"questions": len(_roots(db, session)), "evaluated_answers": len(turns),
               "best_overall": max((t.overall_score for t in turns), default=None),
               "mean_by_dimension": {d: round(sum(t.rubric_scores[d]["score"] for t in turns) / len(turns), 2)
                                     for d in INTERVIEW_DIMENSIONS} if turns else {}}
    session.status, session.ended_at, session.summary = "completed", utcnow(), summary
    db.commit()
    return summary
