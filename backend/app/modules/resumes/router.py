from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.gateway import get_gateway
from app.core import ratelimit
from app.core.config import get_settings
from app.core.db import get_db
from app.core.deps import current_user, owned
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.security import utcnow
from app.files.pdf import extract_text, sanitise_filename, validate_upload
from app.models import Resume, ResumeAnalysis, ResumeVersion, RewriteSuggestion, TargetRole, User
from app.modules import hooks
from app.modules.resumes import coverage, service
from app.modules.resumes.schemas import ResumeContent
from app.modules.targets.requirements import load_requirements, requirements_hash

router = APIRouter(tags=["resumes"])


class FromTextIn(BaseModel):
    text: str = Field(min_length=300, max_length=30000)
    title: str | None = Field(default=None, max_length=100)


class ScratchIn(BaseModel):
    title: str = Field(default="My resume", max_length=100)
    content: ResumeContent


class VersionIn(BaseModel):
    content: ResumeContent
    base_version_id: uuid.UUID
    change_summary: str | None = Field(default=None, max_length=300)
    mark_reviewed: bool = False


class AnalysisIn(BaseModel):
    target_id: uuid.UUID
    version_id: uuid.UUID | None = None


class RewriteIn(BaseModel):
    version_id: uuid.UUID
    bullet_id: str = Field(max_length=12)
    target_id: uuid.UUID | None = None


class Answer(BaseModel):
    question_id: str = Field(max_length=10)
    question: str = Field(default="", max_length=200)
    answer: str = Field(max_length=300)


class DecisionIn(BaseModel):
    action: str = Field(pattern="^(accept|reject|answer)$")
    edited_text: str | None = Field(default=None, max_length=300)
    answers: list[Answer] | None = Field(default=None, max_length=4)


def version_out(v: ResumeVersion) -> dict:
    return {"id": str(v.id), "version_number": v.version_number, "created_by": v.created_by,
            "change_summary": v.change_summary, "created_at": v.created_at.isoformat(), "content": v.content}


def resume_out(db: Session, r: Resume, include_raw: bool = True) -> dict:
    v = db.get(ResumeVersion, r.current_version_id) if r.current_version_id else None
    out = {"id": str(r.id), "title": r.title, "source": r.source, "original_filename": r.original_filename,
           "extraction_status": r.extraction_status, "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at
           else None, "updated_at": r.updated_at.isoformat(), "created_at": r.created_at.isoformat(),
           "current_version": version_out(v) if v else None}
    if include_raw:
        out["raw_text"] = r.raw_text
    return out


def suggestion_out(s: RewriteSuggestion) -> dict:
    return {"id": str(s.id), "status": s.status, "original": s.original_text, "suggested": s.suggested_text,
            "rationale": s.rationale, "facts_used": s.facts_used, "guard_report": s.guard_report,
            "questions": s.questions, "user_answers": s.user_answers, "bullet_ref": s.bullet_ref,
            "resume_version_id": str(s.resume_version_id), "ai_generated": True,
            "applied_version_id": str(s.applied_version_id) if s.applied_version_id else None}


def analysis_out(a: ResumeAnalysis, stale: bool, requirements_changed: bool) -> dict:
    return {"id": str(a.id), "coverage_score": a.coverage_score, "pe_score": a.pe_score, **a.result,
            "resume_version_id": str(a.resume_version_id), "created_at": a.created_at.isoformat(),
            "scoring_version": a.scoring_version, "stale": stale, "requirements_changed": requirements_changed,
            "disclaimer": "Requirement coverage shows what your resume visibly evidences. It is not an ATS score "
                          "and doesn't predict shortlisting."}


def _import_response(db: Session, resume: Resume, version: ResumeVersion, result) -> dict:
    return {"resume_id": str(resume.id), "version_id": str(version.id), "content": version.content,
            "extraction_status": resume.extraction_status, "warnings": result.warnings,
            "unparsed_text": result.unparsed, "raw_text": resume.raw_text, "model": result.model}


@router.post("/resumes/upload", status_code=201)
async def upload(request: Request, file: UploadFile = File(...), title: str | None = Form(default=None),
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    ratelimit.check("upload", str(user.id), limit=10, window_s=3600)
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    validate_upload(data, file.filename, file.content_type)
    service.check_limit(db, user)
    text, warnings = extract_text(data)
    del data  # original bytes are never stored
    filename = sanitise_filename(file.filename)
    default_title = filename[:-4] if filename and filename.lower().endswith(".pdf") else "Resume"
    resume, version, result = service.import_text(db, user, text, title=(title or default_title).strip()[:100],
                                                  source="upload", filename=filename, gateway=get_gateway())
    result.warnings = warnings + result.warnings
    return _import_response(db, resume, version, result)


@router.post("/resumes/from-text", status_code=201)
def from_text(body: FromTextIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ratelimit.check("upload", str(user.id), limit=10, window_s=3600)
    text = body.text.strip()
    resume, version, result = service.import_text(db, user, text, title=body.title or "Pasted resume",
                                                  source="paste", filename=None, gateway=get_gateway())
    return _import_response(db, resume, version, result)


@router.post("/resumes", status_code=201)
def create_scratch(body: ScratchIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    resume, version = service.create_from_scratch(db, user, body.title, body.content)
    hooks.resume_changed(db, user, resume)
    return {"resume_id": str(resume.id), "version_id": str(version.id), "content": version.content}


@router.get("/resumes")
def list_resumes(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Resume).where(Resume.user_id == user.id).order_by(Resume.updated_at.desc())).all()
    return [resume_out(db, r, include_raw=False) for r in rows]


@router.get("/resumes/{resume_id}")
def get_resume(resume_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return resume_out(db, owned(db, Resume, resume_id, user.id))


@router.delete("/resumes/{resume_id}", status_code=204)
def delete_resume(resume_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = owned(db, Resume, resume_id, user.id)
    r.current_version_id = None
    db.flush()
    db.delete(r)
    db.commit()
    hooks.resume_deleted(db, user)


@router.get("/resumes/{resume_id}/versions")
def list_versions(resume_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = owned(db, Resume, resume_id, user.id)
    rows = db.scalars(select(ResumeVersion).where(ResumeVersion.resume_id == r.id)
                      .order_by(ResumeVersion.version_number.desc())).all()
    return [{k: v for k, v in version_out(x).items() if k != "content"} for x in rows]


@router.get("/resumes/{resume_id}/versions/{version_id}")
def get_version(resume_id: str, version_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = owned(db, Resume, resume_id, user.id)
    v = owned(db, ResumeVersion, version_id, user.id)
    if v.resume_id != r.id:
        raise NotFound()
    return version_out(v)


@router.post("/resumes/{resume_id}/versions", status_code=201)
def save_version(resume_id: str, body: VersionIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = owned(db, Resume, resume_id, user.id)
    v = service.save_version(db, user, r, body.content, body.base_version_id,
                             change_summary=body.change_summary, mark_reviewed=body.mark_reviewed)
    hooks.resume_changed(db, user, r)
    return version_out(v)


@router.post("/resumes/{resume_id}/analyses", status_code=201)
def run_analysis(resume_id: str, body: AnalysisIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = owned(db, Resume, resume_id, user.id)
    t = owned(db, TargetRole, body.target_id, user.id)
    version = owned(db, ResumeVersion, body.version_id, user.id) if body.version_id else None
    if version is not None and version.resume_id != r.id:
        raise NotFound()
    a = coverage.run_analysis(db, user.id, t, r, version)
    hooks.evidence_changed(db, user, t, trigger="resume_analysis")
    warnings = [] if t.requirements_confirmed_at else ["REQUIREMENTS_UNCONFIRMED"]
    return {**analysis_out(a, False, False), "warnings": warnings}


@router.get("/resumes/{resume_id}/analyses/latest")
def latest_analysis(resume_id: str, target_id: uuid.UUID = Query(...), user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    r = owned(db, Resume, resume_id, user.id)
    t = owned(db, TargetRole, target_id, user.id)
    a = db.scalar(select(ResumeAnalysis).where(ResumeAnalysis.resume_id == r.id, ResumeAnalysis.target_id == t.id)
                  .order_by(ResumeAnalysis.created_at.desc()).limit(1))
    if a is None:
        raise NotFound("No analysis yet for this resume and target.", code="NO_ANALYSIS")
    current_hash = requirements_hash(load_requirements(db, t, scored_only=True))
    return analysis_out(a, a.resume_version_id != r.current_version_id, a.requirements_hash != current_hash)


@router.post("/resumes/{resume_id}/rewrite-suggestions", status_code=201)
def rewrite(resume_id: str, body: RewriteIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = owned(db, Resume, resume_id, user.id)
    v = owned(db, ResumeVersion, body.version_id, user.id)
    if v.resume_id != r.id:
        raise NotFound()
    t = owned(db, TargetRole, body.target_id, user.id) if body.target_id else None
    rows = service.request_rewrite(db, user, r, v, body.bullet_id, t, get_gateway())
    return {"suggestions": [suggestion_out(s) for s in rows],
            "questions": rows[0].questions if rows else []}


@router.get("/resumes/{resume_id}/rewrite-suggestions")
def list_suggestions(resume_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = owned(db, Resume, resume_id, user.id)
    rows = db.scalars(select(RewriteSuggestion).where(RewriteSuggestion.resume_id == r.id,
                                                      RewriteSuggestion.resume_version_id == r.current_version_id,
                                                      RewriteSuggestion.status.in_(("pending", "flagged")))
                      .order_by(RewriteSuggestion.created_at.desc())).all()
    return [suggestion_out(s) for s in rows]


@router.patch("/rewrite-suggestions/{suggestion_id}")
def decide(suggestion_id: str, body: DecisionIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = owned(db, RewriteSuggestion, suggestion_id, user.id)
    if s.status not in ("pending", "flagged"):
        raise Conflict("This suggestion has already been decided or expired.", code="SUGGESTION_CLOSED")
    new_version_id = None
    if body.action == "reject":
        s.status, s.decided_at = "rejected", utcnow()
        db.commit()
    elif body.action == "answer":
        if not body.answers:
            raise ValidationFailed(details={"fields": {"answers": "Provide at least one answer."}})
        s.user_answers = [a.model_dump() for a in body.answers]
        db.commit()
    else:
        v = service.apply_suggestion(db, user, s, body.edited_text)
        new_version_id = str(v.id)
        resume = db.get(Resume, s.resume_id)
        hooks.resume_changed(db, user, resume)
    db.refresh(s)
    return {"suggestion": suggestion_out(s), "new_version_id": new_version_id}


@router.post("/rewrite-suggestions/{suggestion_id}/regenerate", status_code=201)
def regenerate(suggestion_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = owned(db, RewriteSuggestion, suggestion_id, user.id)
    if s.status not in ("pending", "flagged"):
        raise Conflict("This suggestion has already been decided or expired.", code="SUGGESTION_CLOSED")
    r = db.get(Resume, s.resume_id)
    v = db.get(ResumeVersion, s.resume_version_id)
    t = db.get(TargetRole, s.target_id) if s.target_id else None
    answers, questions = s.user_answers, s.questions
    rows = service.request_rewrite(db, user, r, v, s.bullet_ref["bullet_id"], t, get_gateway(), answers=answers,
                                   previous_questions=questions)
    s = db.get(RewriteSuggestion, s.id)
    s.status = "discarded"
    db.commit()
    return {"suggestions": [suggestion_out(x) for x in rows], "questions": rows[0].questions if rows else []}
