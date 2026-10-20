from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.gateway import get_gateway
from app.core.db import get_db
from app.core.deps import current_user, owned
from app.core.errors import Conflict, NotFound
from app.models import InterviewSession, InterviewTurn, Skill, TargetRole, User
from app.modules import hooks
from app.modules.interviews import service

router = APIRouter(tags=["interviews"])


class StartIn(BaseModel):
    type: str = Field(pattern="^(technical|project|behavioural)$")
    skill_slug: str | None = Field(default=None, max_length=50)


class AnswerIn(BaseModel):
    answer_text: str = Field(max_length=12000)
    input_mode: str = Field(default="typed", pattern="^(typed|voice)$")


def turn_out(db: Session, session: InterviewSession, t: InterviewTurn) -> dict:
    prev = service.previous_attempt(db, t)
    return {"id": str(t.id), "sequence": t.sequence, "question_text": t.question_text, "source_label": t.source_label,
            "attempt_number": t.attempt_number, "parent_turn_id": str(t.parent_turn_id) if t.parent_turn_id else None,
            "answer_text": t.answer_text, "input_mode": t.input_mode,
            "answered_at": t.answered_at.isoformat() if t.answered_at else None,
            "evaluation_status": t.evaluation_status, "rubric_scores": t.rubric_scores,
            "overall_score": t.overall_score, "feedback": t.feedback,
            "delta": service.delta(prev, t, session), "disclaimer": service.DISCLAIMER,
            "guidance": "Aim for 120–300 words: answer directly, explain why, and mention trade-offs."}


def session_out(db: Session, s: InterviewSession, with_turns: bool = True) -> dict:
    skill = db.get(Skill, s.skill_id) if s.skill_id else None
    out = {"id": str(s.id), "type": s.type, "status": s.status, "skill": {"slug": skill.slug, "name": skill.name}
           if skill else None, "max_questions": s.max_questions, "rubric_version": s.rubric_version,
           "created_at": s.created_at.isoformat(), "ended_at": s.ended_at.isoformat() if s.ended_at else None,
           "summary": s.summary}
    turns = db.scalars(select(InterviewTurn).where(InterviewTurn.session_id == s.id)
                       .order_by(InterviewTurn.sequence)).all()
    out["questions_asked"] = sum(1 for t in turns if t.parent_turn_id is None)
    scored = [t.overall_score for t in turns if t.evaluation_status == "scored"]
    out["mean_overall"] = round(sum(scored) / len(scored)) if scored else None
    if with_turns:
        out["turns"] = [turn_out(db, s, t) for t in turns]
    return out


def _after_evaluation(db: Session, user: User, s: InterviewSession, t: InterviewTurn) -> None:
    if t.evaluation_status != "scored":
        return
    from app.modules.plans.service import complete_linked_tasks
    target = db.get(TargetRole, s.target_id)
    weakest = min(t.rubric_scores, key=lambda d: t.rubric_scores[d]["score"])
    complete_linked_tasks(db, user, target, "interview", t.skill_id, t.id, dimension=weakest)
    hooks.evidence_changed(db, user, target, trigger="interview")


def _turn_in_session(db: Session, user: User, session_id: str, turn_id: str) -> tuple[InterviewSession, InterviewTurn]:
    s = owned(db, InterviewSession, session_id, user.id)
    t = owned(db, InterviewTurn, turn_id, user.id)
    if t.session_id != s.id:
        raise NotFound()
    return s, t


@router.post("/targets/{target_id}/interviews", status_code=201)
def start(target_id: str, body: StartIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = owned(db, TargetRole, target_id, user.id)
    s = service.start(db, user, t, body.type, body.skill_slug)
    return session_out(db, s)


@router.get("/targets/{target_id}/interviews")
def history(target_id: str, page: int = Query(default=1, ge=1), user: User = Depends(current_user),
            db: Session = Depends(get_db)):
    t = owned(db, TargetRole, target_id, user.id)
    stmt = select(InterviewSession).where(InterviewSession.target_id == t.id, InterviewSession.user_id == user.id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(InterviewSession.created_at.desc()).offset((page - 1) * 20).limit(20)).all()
    for s in rows:
        service.lazy_abandon(db, s)
    return {"items": [session_out(db, s, with_turns=False) for s in rows], "page": page, "page_size": 20,
            "total": total}


@router.get("/interviews/{session_id}")
def get_session(session_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = owned(db, InterviewSession, session_id, user.id)
    service.lazy_abandon(db, s)
    return session_out(db, s)


@router.post("/interviews/{session_id}/turns/{turn_id}/answer")
def answer(session_id: str, turn_id: str, body: AnswerIn, user: User = Depends(current_user),
           db: Session = Depends(get_db)):
    s, t = _turn_in_session(db, user, session_id, turn_id)
    if s.status == "completed":
        raise Conflict("This session has ended. Start a new one.", code="SESSION_CLOSED")
    service.submit_answer(db, user, s, t, body.answer_text, body.input_mode, get_gateway())
    _after_evaluation(db, user, s, t)
    return turn_out(db, s, t)


@router.post("/interviews/{session_id}/turns/{turn_id}/evaluate")
def evaluate(session_id: str, turn_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s, t = _turn_in_session(db, user, session_id, turn_id)
    if t.evaluation_status not in ("failed", "pending") or not t.answer_text:
        raise Conflict("This answer doesn't need re-evaluation.", code="NOT_RETRYABLE")
    service.evaluate(db, user, s, t, get_gateway())
    _after_evaluation(db, user, s, t)
    return turn_out(db, s, t)


@router.post("/interviews/{session_id}/turns/{turn_id}/retry", status_code=201)
def retry(session_id: str, turn_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s, t = _turn_in_session(db, user, session_id, turn_id)
    if s.status == "completed":
        raise Conflict("This session has ended. Start a new one.", code="SESSION_CLOSED")
    return turn_out(db, s, service.retry(db, user, s, t))


@router.post("/interviews/{session_id}/next", status_code=201)
def next_question(session_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = owned(db, InterviewSession, session_id, user.id)
    if s.status == "completed":
        raise Conflict("This session has ended. Start a new one.", code="SESSION_CLOSED")
    if s.status == "abandoned":
        s.status = "open"
    return turn_out(db, s, service.new_question_turn(db, user, s))


@router.post("/interviews/{session_id}/end")
def end(session_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = owned(db, InterviewSession, session_id, user.id)
    summary = service.end(db, s)
    return {"summary": summary, "session": session_out(db, s, with_turns=False)}
