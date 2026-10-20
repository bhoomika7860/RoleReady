from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.gateway import get_gateway
from app.core.db import get_db
from app.core.deps import current_user, owned
from app.core.errors import Conflict, NotFound
from app.core.security import utcnow
from app.models import Assessment, AssessmentItem, Question, Skill, TargetRole, User
from app.modules import hooks
from app.modules.assessments import service
from app.modules.assessments.scoring import source_label, validate_response

router = APIRouter(tags=["assessments"])


class StartIn(BaseModel):
    kind: str = Field(pattern="^(diagnostic|checkpoint)$")
    skill_slug: str | None = Field(default=None, max_length=50)


class ResponseIn(BaseModel):
    response: dict


def _summary(db: Session, a: Assessment) -> dict:
    skill = db.get(Skill, a.skill_id) if a.skill_id else None
    return {"id": str(a.id), "kind": a.kind, "status": a.status, "target_id": str(a.target_id),
            "skill": {"slug": skill.slug, "name": skill.name} if skill else None,
            "score": round(float(a.score) * 100) if a.score is not None else None,
            "items_total": a.items_total, "items_scored": a.items_scored,
            "created_at": a.created_at.isoformat(), "expires_at": a.expires_at.isoformat(),
            "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
            "scored_at": a.scored_at.isoformat() if a.scored_at else None,
            "includes_repeats": bool(a.blueprint.get("includes_repeats")),
            "difficulty_mix": a.blueprint.get("difficulty_mix"), "scoring_version": a.scoring_version}


def _state(db: Session, a: Assessment) -> dict:
    items = []
    for item, q, skill in service.items_with_questions(db, a):
        items.append({"position": item.position, "question_id": str(q.id), "type": q.type,
                      "difficulty": q.difficulty, "skill": {"slug": skill.slug, "name": skill.name},
                      "topic": q.topic, "prompt": q.prompt,
                      "options": q.options, "source_label": source_label(q), "response": item.response,
                      "answered": item.response is not None})
    first_unanswered = next((i["position"] for i in items if not i["answered"]), None)
    return {**_summary(db, a), "items": items, "first_unanswered": first_unanswered,
            "blueprint": {k: v for k, v in a.blueprint.items() if k not in ("seed",)}}


@router.post("/targets/{target_id}/assessments", status_code=201)
def start(target_id: str, body: StartIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = owned(db, TargetRole, target_id, user.id)
    a = service.start(db, user, t, body.kind, body.skill_slug)
    return _state(db, a)


@router.get("/targets/{target_id}/assessments")
def list_assessments(target_id: str, kind: str | None = Query(default=None, pattern="^(diagnostic|checkpoint)$"),
                     user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = owned(db, TargetRole, target_id, user.id)
    service.expire_stale(db, user)
    stmt = select(Assessment).where(Assessment.target_id == t.id, Assessment.user_id == user.id) \
        .order_by(Assessment.created_at.desc()).limit(50)
    if kind:
        stmt = stmt.where(Assessment.kind == kind)
    return [_summary(db, a) for a in db.scalars(stmt).all()]


@router.get("/assessments/{assessment_id}")
def get_assessment(assessment_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    service.expire_stale(db, user)
    return _state(db, owned(db, Assessment, assessment_id, user.id))


@router.put("/assessments/{assessment_id}/items/{position}/response")
def autosave(assessment_id: str, position: int, body: ResponseIn, user: User = Depends(current_user),
             db: Session = Depends(get_db)):
    a = owned(db, Assessment, assessment_id, user.id)
    if a.status != "in_progress" or a.expires_at <= utcnow():
        raise Conflict("This assessment is closed.", code="ASSESSMENT_CLOSED", details={"status": a.status})
    item = db.scalar(select(AssessmentItem).where(AssessmentItem.assessment_id == a.id,
                                                  AssessmentItem.position == position))
    if item is None:
        raise NotFound()
    q = db.get(Question, item.question_id)
    item.response = validate_response(item.type, q.options, body.response)
    item.answered_at = utcnow()
    db.commit()
    return {"position": position, "saved_at": item.answered_at.isoformat()}


def _after_scoring(db: Session, user: User, a: Assessment) -> None:
    from app.modules.plans.service import complete_linked_tasks
    t = db.get(TargetRole, a.target_id)
    complete_linked_tasks(db, user, t, "assess" if a.kind == "diagnostic" else "reassess", a.skill_id, a.id)
    hooks.evidence_changed(db, user, t, trigger="assessment_scored")


@router.post("/assessments/{assessment_id}/submit")
def submit(assessment_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = owned(db, Assessment, assessment_id, user.id)
    a = service.submit(db, user, a, get_gateway())
    _after_scoring(db, user, a)
    return {**_summary(db, a), "result_url": f"/app/results?assessment={a.id}"}


@router.get("/assessments/{assessment_id}/result")
def result(assessment_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = owned(db, Assessment, assessment_id, user.id)
    if a.status in ("in_progress", "scoring"):
        return JSONResponse(status_code=202, content={"status": a.status}, headers={"Retry-After": "2"})
    skills: dict[str, dict] = {}
    items = []
    warnings = []
    from app.core.scoring_config import DIFFICULTY_WEIGHT
    for item, q, skill in service.items_with_questions(db, a):
        s = skills.setdefault(skill.slug, {"slug": skill.slug, "name": skill.name, "items_total": 0,
                                           "items_scored": 0, "_w": 0.0, "_ws": 0.0, "correct": 0})
        s["items_total"] += 1
        if item.score is not None:
            w = DIFFICULTY_WEIGHT[item.difficulty]
            s["items_scored"] += 1
            s["_w"] += w
            s["_ws"] += w * float(item.score)
            if float(item.score) >= 0.999:
                s["correct"] += 1
        if item.evaluation_status == "failed":
            warnings.append({"code": "SCORING_FAILED", "position": item.position})
        items.append({
            "position": item.position, "type": q.type, "difficulty": q.difficulty, "topic": q.topic,
            "skill": {"slug": skill.slug, "name": skill.name}, "prompt": q.prompt, "options": q.options,
            "response": item.response, "unanswered": item.unanswered,
            "score": float(item.score) if item.score is not None else None,
            "correct_answer": q.correct_answer, "reference_answer": q.reference_answer, "explanation": q.explanation,
            "evaluation": item.evaluation, "evaluation_status": item.evaluation_status,
            "source_label": source_label(q)})
    skill_rows = []
    for s in skills.values():
        score = round(100 * s["_ws"] / s["_w"]) if s["_w"] else None
        skill_rows.append({k: v for k, v in s.items() if not k.startswith("_")} | {"score": score})
    return {**_summary(db, a), "skills": skill_rows, "items": items, "warnings": warnings,
            "unanswered": sum(1 for i in items if i["unanswered"]),
            "note": "Objective questions are scored by code. Short answers are judged against a published rubric by "
                    "AI; each credited point quotes your answer."}


@router.post("/assessments/{assessment_id}/items/{position}/retry-evaluation")
def retry(assessment_id: str, position: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = owned(db, Assessment, assessment_id, user.id)
    item = service.retry_evaluation(db, user, a, position, get_gateway())
    hooks.evidence_changed(db, user, db.get(TargetRole, a.target_id), trigger="assessment_scored")
    return {"position": item.position, "score": float(item.score) if item.score is not None else None,
            "evaluation": item.evaluation, "evaluation_status": item.evaluation_status,
            "assessment": _summary(db, a)}
