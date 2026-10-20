"""Practice Lab (SRS 5.8): curated items, immediate feedback, evidence written per scored answer."""
from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.gateway import AIFailed, get_gateway
from app.core import scoring_config as sc
from app.core.db import get_db
from app.core.deps import current_user, owned
from app.core.errors import AIQuotaExceeded, AIUnavailableError, Conflict, NotFound, ValidationFailed
from app.models import (OBJECTIVE_TYPES, Assessment, AssessmentItem, PracticeAttempt, PreparationTask, Question,
                        Role, Skill, SkillEvidence, TargetRole, User)
from app.modules import hooks
from app.modules.assessments.scoring import evaluate_short, score_objective, source_label, validate_response
from app.modules.evidence.engine import compute_states

router = APIRouter(prefix="/practice", tags=["practice"])


class AttemptIn(BaseModel):
    question_id: uuid.UUID
    target_id: uuid.UUID
    response: dict
    task_id: uuid.UUID | None = None


def _question_out(q: Question, skill: Skill) -> dict:
    return {"question_id": str(q.id), "type": q.type, "difficulty": q.difficulty, "topic": q.topic,
            "skill": {"slug": skill.slug, "name": skill.name}, "prompt": q.prompt, "options": q.options,
            "source_label": source_label(q), "has_rubric": q.type not in OBJECTIVE_TYPES}


@router.get("/questions")
def practice_questions(target_id: uuid.UUID, skill: str = Query(max_length=50),
                       difficulty: str | None = Query(default=None, pattern="^(easy|medium|hard)$"),
                       type: str | None = Query(default=None, max_length=15), limit: int = Query(default=5, ge=1, le=10),
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = owned(db, TargetRole, target_id, user.id)
    s = db.scalar(select(Skill).where(Skill.slug == skill))
    if s is None:
        raise ValidationFailed(details={"fields": {"skill": "Unknown skill."}})
    state = next((x for x in compute_states(db, user, t) if x.slug == skill), None)
    D = state.D if state else None
    if difficulty:
        wanted = [difficulty]
    elif D is None or D < 0.4:
        wanted = ["easy", "medium"]
    elif D <= 0.7:
        wanted = ["medium"]
    else:
        wanted = ["medium", "hard"]
    pool = db.scalars(select(Question).where(Question.skill_id == s.id, Question.status == "active",
                                             Question.purpose.in_(("practice", "any")),
                                             (Question.owner_user_id.is_(None)) | (Question.owner_user_id == user.id))
                      .order_by(Question.slug)).all()
    if type:
        pool = [q for q in pool if q.type == type]
    frozen = set(db.scalars(select(AssessmentItem.question_id).join(Assessment, Assessment.id ==
                                                                    AssessmentItem.assessment_id)
                            .where(Assessment.user_id == user.id, Assessment.status == "in_progress")).all())
    in_checkpoints = set(db.scalars(select(AssessmentItem.question_id).join(Assessment, Assessment.id ==
                                                                            AssessmentItem.assessment_id)
                                    .where(Assessment.user_id == user.id, Assessment.kind == "checkpoint")).all())
    last_seen = dict(db.execute(select(PracticeAttempt.question_id, func.max(PracticeAttempt.created_at))
                                .where(PracticeAttempt.user_id == user.id)
                                .group_by(PracticeAttempt.question_id)).all())
    pool = [q for q in pool if q.id not in frozen]
    fair = [q for q in pool if q.id not in in_checkpoints]
    if len(fair) >= limit:
        pool = fair

    def rank(q: Question):
        seen = last_seen.get(q.id)
        return (0 if q.difficulty in wanted else 1, 0 if seen is None else 1, seen.timestamp() if seen else 0, q.slug)
    chosen = sorted(pool, key=rank)[:limit]
    hint = None
    if not chosen:
        hint = "POOL_EXHAUSTED"
    elif all(q.id in last_seen for q in chosen):
        hint = "REPEATS"
    return {"items": [_question_out(q, s) for q in chosen], "hint": hint, "target_difficulty": wanted,
            "skill": {"slug": s.slug, "name": s.name, "D": D, "n": state.n if state else 0},
            "note": "Coding practice here is conceptual (output prediction, complexity, approach) — no code is run."}


def _attempt_out(a: PracticeAttempt, q: Question) -> dict:
    return {"attempt_id": str(a.id), "question_id": str(q.id), "score": float(a.score) if a.score is not None else None,
            "correct": a.is_correct, "evaluation_status": a.evaluation_status, "evaluation": a.evaluation,
            "correct_answer": q.correct_answer, "reference_answer": q.reference_answer, "explanation": q.explanation,
            "feedback_kind": "deterministic" if q.type in OBJECTIVE_TYPES else "ai_rubric",
            "attempt_number": a.attempt_number, "created_at": a.created_at.isoformat()}


def _write_evidence(db: Session, a: PracticeAttempt, q: Question) -> None:
    db.add(SkillEvidence(user_id=a.user_id, target_id=a.target_id, skill_id=a.skill_id, source_type="practice",
                         score=a.score, difficulty_weight=Decimal(str(sc.DIFFICULTY_WEIGHT[q.difficulty])),
                         item_type=q.type, practice_attempt_id=a.id))


def _after_attempt(db: Session, user: User, t: TargetRole, a: PracticeAttempt) -> None:
    from app.modules.plans.service import complete_linked_tasks
    complete_linked_tasks(db, user, t, "practice", a.skill_id, a.id)
    n = db.scalar(select(func.count()).select_from(PracticeAttempt).where(
        PracticeAttempt.user_id == user.id, PracticeAttempt.target_id == t.id,
        PracticeAttempt.evaluation_status.in_(("not_required", "scored")))) or 0
    if n % sc.PRACTICE_SET_SIZE == 0:
        hooks.evidence_changed(db, user, t, trigger="practice_set")


@router.post("/attempts", status_code=201)
def submit_attempt(body: AttemptIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = owned(db, TargetRole, body.target_id, user.id)
    q = db.get(Question, body.question_id)
    if q is None or q.status != "active" or q.purpose not in ("practice", "any") or \
            (q.owner_user_id is not None and q.owner_user_id != user.id):
        raise NotFound()
    if body.task_id is not None:
        owned(db, PreparationTask, body.task_id, user.id)
    response = validate_response(q.type, q.options, body.response)
    n_prev = db.scalar(select(func.count()).select_from(PracticeAttempt).where(
        PracticeAttempt.user_id == user.id, PracticeAttempt.question_id == q.id)) or 0
    a = PracticeAttempt(user_id=user.id, target_id=t.id, question_id=q.id, skill_id=q.skill_id, task_id=body.task_id,
                        attempt_number=n_prev + 1, response=response)
    if q.type in OBJECTIVE_TYPES:
        score = score_objective(q.type, q.correct_answer, response)
        a.score, a.is_correct, a.evaluation_status = Decimal(str(round(score, 3))), score >= 0.999, "not_required"
        db.add(a)
        db.flush()
        _write_evidence(db, a, q)
        db.commit()
    else:
        a.evaluation_status = "pending"
        db.add(a)
        db.commit()  # the answer is saved before the AI call
        _evaluate(db, user, t, a, q)
    if a.evaluation_status in ("scored", "not_required"):
        _after_attempt(db, user, t, a)
    return _attempt_out(a, q)


def _evaluate(db: Session, user: User, t: TargetRole, a: PracticeAttempt, q: Question) -> None:
    role = db.get(Role, t.role_id)
    try:
        r = evaluate_short(get_gateway(), q, a.response.get("text", ""), user.id, role.name)
    except (AIFailed, AIUnavailableError, AIQuotaExceeded) as exc:
        a.evaluation_status, a.evaluation = "failed", {"error": exc.code}
        db.commit()  # no evidence is written for a failed evaluation
        return
    a.score = Decimal(str(r["score"]))
    a.is_correct = r["score"] >= 0.7
    a.evaluation, a.evaluation_status = r["evaluation"], "scored"
    a.rubric_version, a.prompt_version = (q.rubric or {}).get("version"), "w7s.v1"
    db.flush()
    _write_evidence(db, a, q)
    db.commit()


@router.post("/attempts/{attempt_id}/retry-evaluation")
def retry_evaluation(attempt_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = owned(db, PracticeAttempt, attempt_id, user.id)
    if a.evaluation_status not in ("failed", "pending"):
        raise Conflict("This answer doesn't need re-evaluation.", code="NOT_RETRYABLE")
    q = db.get(Question, a.question_id)
    t = db.get(TargetRole, a.target_id)
    _evaluate(db, user, t, a, q)
    if a.evaluation_status == "scored":
        _after_attempt(db, user, t, a)
    return _attempt_out(a, q)


@router.get("/attempts")
def history(target_id: uuid.UUID, skill: str | None = Query(default=None, max_length=50),
            page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=50),
            user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = owned(db, TargetRole, target_id, user.id)
    stmt = select(PracticeAttempt, Question, Skill).join(Question, Question.id == PracticeAttempt.question_id) \
        .join(Skill, Skill.id == PracticeAttempt.skill_id) \
        .where(PracticeAttempt.user_id == user.id, PracticeAttempt.target_id == t.id)
    if skill:
        stmt = stmt.where(Skill.slug == skill)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.order_by(PracticeAttempt.created_at.desc()).offset((page - 1) * page_size)
                      .limit(page_size)).all()
    items = [{**_attempt_out(a, q), "prompt": q.prompt[:200], "type": q.type, "difficulty": q.difficulty,
              "skill": {"slug": s.slug, "name": s.name}, "response": a.response} for a, q, s in rows]
    return {"items": items, "page": page, "page_size": page_size, "total": total}


@router.get("/summary")
def summary(target_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Per-skill practice counts since the last assessment of that skill (drives 'Ready for a checkpoint?')."""
    t = owned(db, TargetRole, target_id, user.id)
    states = compute_states(db, user, t)
    ids = [uuid.UUID(s.skill_id) for s in states]
    last_by_skill = dict(db.execute(
        select(AssessmentItem.skill_id, func.max(Assessment.scored_at))
        .join(Assessment, Assessment.id == AssessmentItem.assessment_id)
        .where(Assessment.user_id == user.id, Assessment.status.in_(("scored", "scored_partial")),
               AssessmentItem.skill_id.in_(ids)).group_by(AssessmentItem.skill_id)).all()) if ids else {}
    attempts_all = db.execute(select(PracticeAttempt.skill_id, PracticeAttempt.created_at, PracticeAttempt.is_correct)
                              .where(PracticeAttempt.user_id == user.id, PracticeAttempt.skill_id.in_(ids),
                                     PracticeAttempt.evaluation_status.in_(("not_required", "scored")))).all() \
        if ids else []
    pools = dict(db.execute(select(Question.skill_id, func.count()).where(
        Question.skill_id.in_(ids), Question.status == "active", Question.purpose.in_(("practice", "any")),
        Question.owner_user_id.is_(None)).group_by(Question.skill_id)).all()) if ids else {}
    out = []
    for s in states:
        sid = uuid.UUID(s.skill_id)
        last_assess = last_by_skill.get(sid)
        attempts = [a for a in attempts_all if a.skill_id == sid and (last_assess is None or a.created_at > last_assess)]
        correct = sum(1 for a in attempts if a.is_correct)
        pool = pools.get(sid, 0)
        out.append({"skill": {"slug": s.slug, "name": s.name}, "importance": s.importance, "D": s.D, "n": s.n,
                    "demonstrated_state": s.demonstrated_state, "since_last_assessment": len(attempts),
                    "correct_since_last_assessment": correct, "pool_size": pool,
                    "ready_for_checkpoint": len(attempts) >= sc.READY_TO_REASSESS_PRACTICE})
    return {"skills": out}
