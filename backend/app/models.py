"""ORM models — the relational schema (SRS Section 10, adapted for identifier-only demo login).

Conventions: UUID primary keys, timestamptz (UTC) created_at/updated_at, enums as CHECK
constraints on varchar, `user_id` denormalised onto every user-owned table and cascading on
user deletion. JSONB only for document-shaped data (resume content, evaluations, blueprints).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
                         server_default=text("gen_random_uuid()"))


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


def _updated() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(),
                         onupdate=func.now())


def _user_fk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
                         nullable=False, index=True)


def _check_in(col: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    joined = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{col} IN ({joined})", name=name)


# --------------------------------------------------------------------------- identity
class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        _check_in("identifier_kind", ("email", "username"), "ck_users_identifier_kind"),
        _check_in("experience_level", ("student", "fresher", "early_career"), "ck_users_experience"),
        CheckConstraint("identifier = lower(identifier)", name="ck_users_identifier_normalised"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    identifier: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    identifier_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    preferred_name: Mapped[str | None] = mapped_column(String(100))
    experience_level: Mapped[str | None] = mapped_column(String(20))
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="Asia/Kolkata",
                                          default="Asia/Kolkata")
    onboarding_step: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1", default=1)
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", default=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class UserSession(Base):
    __tablename__ = "user_sessions"
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created()


# --------------------------------------------------------------------------- catalogue
class Role(Base):
    __tablename__ = "roles"
    id: Mapped[uuid.UUID] = _uuid_pk()
    slug: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    dimension_config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true", default=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


SKILL_CATEGORIES = ("language", "framework", "database", "web", "cs_fundamentals", "tooling", "data",
                    "practices")


class Skill(Base):
    __tablename__ = "skills"
    __table_args__ = (_check_in("category", SKILL_CATEGORIES, "ck_skills_category"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    slug: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}", default=list)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true", default=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class SkillPrerequisite(Base):
    __tablename__ = "skill_prerequisites"
    __table_args__ = (CheckConstraint("skill_id <> prerequisite_skill_id", name="ck_skill_prereq_self"),)
    skill_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("skills.id", ondelete="CASCADE"),
                                                primary_key=True)
    prerequisite_skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True)


IMPORTANCE = ("core", "required", "preferred")


class RoleSkill(Base):
    __tablename__ = "role_skills"
    __table_args__ = (_check_in("importance", IMPORTANCE, "ck_role_skills_importance"),)
    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"),
                                               primary_key=True)
    skill_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("skills.id", ondelete="CASCADE"),
                                                primary_key=True)
    importance: Mapped[str] = mapped_column(String(10), nullable=False)
    weight: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)


# --------------------------------------------------------------------------- targets
class TargetRole(Base):
    __tablename__ = "target_roles"
    __table_args__ = (
        _check_in("status", ("active", "archived"), "ck_target_status"),
        CheckConstraint("daily_minutes BETWEEN 30 AND 240", name="ck_target_daily_minutes"),
        Index("uq_target_one_active", "user_id", unique=True, postgresql_where=text("status = 'active'")),
        Index("ix_target_user_created", "user_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("roles.id", ondelete="RESTRICT"),
                                               nullable=False)
    job_title: Mapped[str] = mapped_column(String(120), nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(120))
    deadline_date: Mapped[date] = mapped_column(Date, nullable=False)
    daily_minutes: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active")
    requirements_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class JobDescription(Base):
    __tablename__ = "job_descriptions"
    __table_args__ = (
        _check_in("status", ("processing", "extracted", "fallback", "failed"), "ck_jd_status"),
        CheckConstraint("char_length(raw_text) <= 15000", name="ck_jd_length"),
        Index("ix_jd_current", "target_id", postgresql_where=text("superseded_at IS NULL")),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),
                                                 ForeignKey("target_roles.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = _user_fk()
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    analysis: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}", default=dict)
    warnings: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]", default=list)
    prompt_version: Mapped[str | None] = mapped_column(String(20))
    model: Mapped[str | None] = mapped_column(String(120))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class JobRequirement(Base):
    __tablename__ = "job_requirements"
    __table_args__ = (
        _check_in("category", ("skill", "experience", "education", "other"), "ck_req_category"),
        _check_in("requirement_level", ("required", "preferred"), "ck_req_level"),
        _check_in("importance", IMPORTANCE, "ck_req_importance"),
        _check_in("origin", ("role_default", "jd_extracted", "user_added"), "ck_req_origin"),
        Index("ix_req_target_active", "target_id", postgresql_where=text("is_active")),
        Index("uq_req_target_skill", "target_id", "skill_id", unique=True,
              postgresql_where=text("skill_id IS NOT NULL AND is_active")),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),
                                                 ForeignKey("target_roles.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = _user_fk()
    job_description_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("job_descriptions.id", ondelete="SET NULL"))
    skill_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True),
                                                       ForeignKey("skills.id", ondelete="RESTRICT"))
    raw_phrase: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(12), nullable=False, default="skill")
    requirement_level: Mapped[str] = mapped_column(String(10), nullable=False)
    importance: Mapped[str] = mapped_column(String(10), nullable=False)
    origin: Mapped[str] = mapped_column(String(12), nullable=False)
    evidence_snippet: Mapped[str | None] = mapped_column(String(300))
    is_inferred: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true", default=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


# --------------------------------------------------------------------------- resumes
class Resume(Base):
    __tablename__ = "resumes"
    __table_args__ = (
        _check_in("source", ("upload", "scratch", "paste"), "ck_resume_source"),
        _check_in("extraction_status", ("complete", "partial", "manual"), "ck_resume_extraction"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(100))
    raw_text: Mapped[str | None] = mapped_column(Text)
    extraction_status: Mapped[str] = mapped_column(String(10), nullable=False)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("resume_versions.id", ondelete="SET NULL", use_alter=True, name="fk_resumes_current_version"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class ResumeVersion(Base):
    __tablename__ = "resume_versions"
    __table_args__ = (
        UniqueConstraint("resume_id", "version_number", name="uq_resume_version_number"),
        _check_in("created_by", ("import", "user", "ai_tailor"), "ck_resume_version_created_by"),
        CheckConstraint("version_number >= 1", name="ck_resume_version_positive"),
        CheckConstraint("pg_column_size(content) <= 65536", name="ck_resume_version_size"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    resume_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("resumes.id", ondelete="CASCADE"),
                                                 nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = _user_fk()
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resume_versions.id", ondelete="SET NULL"))
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1", default=1)
    created_by: Mapped[str] = mapped_column(String(10), nullable=False)
    change_summary: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = _created()


class ResumeAnalysis(Base):
    __tablename__ = "resume_analyses"
    __table_args__ = (
        CheckConstraint("coverage_score BETWEEN 0 AND 100", name="ck_analysis_coverage"),
        Index("ix_analysis_target_created", "target_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),
                                                 ForeignKey("target_roles.id", ondelete="CASCADE"), nullable=False)
    resume_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("resumes.id", ondelete="CASCADE"),
                                                 nullable=False)
    resume_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resume_versions.id", ondelete="CASCADE"), nullable=False)
    requirements_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    coverage_score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    pe_score: Mapped[int | None] = mapped_column(SmallInteger)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False)
    scoring_version: Mapped[str] = mapped_column(String(10), nullable=False)
    created_at: Mapped[datetime] = _created()


class RewriteSuggestion(Base):
    __tablename__ = "rewrite_suggestions"
    __table_args__ = (
        _check_in("status", ("pending", "accepted", "rejected", "expired", "discarded", "flagged"),
                  "ck_rewrite_status"),
        Index("ix_rewrite_version_status", "resume_version_id", "status"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    resume_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("resumes.id", ondelete="CASCADE"),
                                                 nullable=False)
    resume_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resume_versions.id", ondelete="CASCADE"), nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True),
                                                        ForeignKey("target_roles.id", ondelete="SET NULL"))
    bullet_ref: Mapped[dict] = mapped_column(JSONB, nullable=False)
    original_text: Mapped[str] = mapped_column(String(300), nullable=False)
    suggested_text: Mapped[str | None] = mapped_column(String(300))
    rationale: Mapped[str | None] = mapped_column(String(300))
    facts_used: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]", default=list)
    guard_report: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}", default=dict)
    questions: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]", default=list)
    user_answers: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]", default=list)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")
    applied_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resume_versions.id", ondelete="SET NULL"))
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


# --------------------------------------------------------------------------- question bank
QUESTION_TYPES = ("mcq_single", "mcq_multi", "code_output", "short_answer", "approach")
OBJECTIVE_TYPES = ("mcq_single", "mcq_multi", "code_output")


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (
        _check_in("type", QUESTION_TYPES, "ck_question_type"),
        _check_in("difficulty", ("easy", "medium", "hard"), "ck_question_difficulty"),
        _check_in("purpose", ("assessment", "practice", "interview", "any"), "ck_question_purpose"),
        _check_in("source_type", ("official", "candidate_reported", "curated_general", "ai_generated"),
                  "ck_question_source"),
        _check_in("authoring", ("human", "ai_assisted", "ai_runtime"), "ck_question_authoring"),
        _check_in("status", ("draft", "active", "flagged", "retired"), "ck_question_status"),
        CheckConstraint("source_type <> 'ai_generated' OR owner_user_id IS NOT NULL",
                        name="ck_question_generated_owner"),
        Index("ix_question_pool", "skill_id", "status", "purpose", "difficulty",
              postgresql_where=text("owner_user_id IS NULL")),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    slug: Mapped[str | None] = mapped_column(String(80), unique=True)
    skill_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("skills.id", ondelete="RESTRICT"),
                                                nullable=False)
    topic: Mapped[str] = mapped_column(String(80), nullable=False)
    type: Mapped[str] = mapped_column(String(15), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(6), nullable=False)
    purpose: Mapped[str] = mapped_column(String(12), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list | None] = mapped_column(JSONB)
    correct_answer: Mapped[Any | None] = mapped_column(JSONB)
    reference_answer: Mapped[str | None] = mapped_column(Text)
    rubric: Mapped[dict | None] = mapped_column(JSONB)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    authoring: Mapped[str] = mapped_column(String(12), nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(80))
    reviewed_at: Mapped[date | None] = mapped_column(Date)
    bank_version: Mapped[str] = mapped_column(String(20), nullable=False, server_default="v1", default="v1")
    status: Mapped[str] = mapped_column(String(8), nullable=False, default="active")
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True),
                                                            ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


# --------------------------------------------------------------------------- measurement
class Assessment(Base):
    __tablename__ = "assessments"
    __table_args__ = (
        _check_in("kind", ("diagnostic", "checkpoint"), "ck_assessment_kind"),
        _check_in("status", ("in_progress", "scoring", "scored", "scored_partial", "abandoned"),
                  "ck_assessment_status"),
        CheckConstraint("(kind = 'checkpoint') = (skill_id IS NOT NULL)", name="ck_assessment_checkpoint_skill"),
        Index("ix_assessment_user_target", "user_id", "target_id", "created_at"),
        Index("uq_assessment_one_open_diagnostic", "target_id", unique=True,
              postgresql_where=text("kind = 'diagnostic' AND status = 'in_progress'")),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),
                                                 ForeignKey("target_roles.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    skill_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("skills.id"))
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="in_progress")
    blueprint: Mapped[dict] = mapped_column(JSONB, nullable=False)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    scoring_version: Mapped[str] = mapped_column(String(10), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    items_total: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0", default=0)
    items_scored: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0", default=0)
    score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


EVAL_STATUS = ("not_required", "pending", "scored", "failed")


class AssessmentItem(Base):
    __tablename__ = "assessment_items"
    __table_args__ = (
        UniqueConstraint("assessment_id", "position", name="uq_assessment_item_position"),
        _check_in("evaluation_status", EVAL_STATUS, "ck_assessment_item_eval"),
        CheckConstraint("score IS NULL OR (score >= 0 AND score <= 1)", name="ck_assessment_item_score"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = _user_fk()
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    question_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("questions.id"), nullable=False,
                                                   index=True)
    skill_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("skills.id"), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(6), nullable=False)
    type: Mapped[str] = mapped_column(String(15), nullable=False)
    response: Mapped[dict | None] = mapped_column(JSONB)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unanswered: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", default=False)
    score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    evaluation: Mapped[dict | None] = mapped_column(JSONB)
    evaluation_status: Mapped[str] = mapped_column(String(12), nullable=False, default="not_required")
    rubric_version: Mapped[str | None] = mapped_column(String(20))
    prompt_version: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class PracticeAttempt(Base):
    __tablename__ = "practice_attempts"
    __table_args__ = (
        _check_in("evaluation_status", EVAL_STATUS, "ck_practice_eval"),
        Index("ix_practice_user_question", "user_id", "question_id", "created_at"),
        Index("ix_practice_user_target", "user_id", "target_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),
                                                 ForeignKey("target_roles.id", ondelete="CASCADE"), nullable=False)
    question_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("questions.id"), nullable=False)
    skill_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("skills.id"), nullable=False)
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("preparation_tasks.id", ondelete="SET NULL"))
    attempt_number: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    response: Mapped[dict] = mapped_column(JSONB, nullable=False)
    score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    is_correct: Mapped[bool | None] = mapped_column(Boolean)
    evaluation: Mapped[dict | None] = mapped_column(JSONB)
    evaluation_status: Mapped[str] = mapped_column(String(12), nullable=False, default="not_required")
    rubric_version: Mapped[str | None] = mapped_column(String(20))
    prompt_version: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class InterviewSession(Base):
    __tablename__ = "interview_sessions"
    __table_args__ = (
        _check_in("type", ("technical", "project", "behavioural"), "ck_interview_type"),
        _check_in("status", ("open", "completed", "abandoned"), "ck_interview_status"),
        Index("ix_interview_user_target", "user_id", "target_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),
                                                 ForeignKey("target_roles.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(12), nullable=False)
    skill_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("skills.id"))
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="open")
    max_questions: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=5)
    rubric_version: Mapped[str] = mapped_column(String(10), nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                       server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class InterviewTurn(Base):
    __tablename__ = "interview_turns"
    __table_args__ = (
        UniqueConstraint("session_id", "sequence", name="uq_interview_turn_sequence"),
        _check_in("evaluation_status", ("awaiting_answer", "pending", "scored", "failed", "too_short"),
                  "ck_turn_eval"),
        _check_in("input_mode", ("typed", "voice"), "ck_turn_input_mode"),
        CheckConstraint("attempt_number BETWEEN 1 AND 3", name="ck_turn_attempts"),
        CheckConstraint("overall_score IS NULL OR overall_score BETWEEN 0 AND 100", name="ck_turn_overall"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = _user_fk()
    sequence: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    question_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("questions.id"))
    skill_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("skills.id"))
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_label: Mapped[str] = mapped_column(String(80), nullable=False)
    project_entry_ref: Mapped[dict | None] = mapped_column(JSONB)
    parent_turn_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("interview_turns.id", ondelete="SET NULL"), index=True)
    attempt_number: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    answer_text: Mapped[str | None] = mapped_column(Text)
    input_mode: Mapped[str] = mapped_column(String(6), nullable=False, default="typed")
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evaluation_status: Mapped[str] = mapped_column(String(18), nullable=False, default="awaiting_answer")
    rubric_scores: Mapped[dict | None] = mapped_column(JSONB)
    overall_score: Mapped[int | None] = mapped_column(SmallInteger)
    feedback: Mapped[dict | None] = mapped_column(JSONB)
    prompt_version: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


# --------------------------------------------------------------------------- evidence & gaps
INTERVIEW_DIMENSIONS = ("relevance", "correctness", "completeness", "reasoning", "clarity")


class SkillEvidence(Base):
    __tablename__ = "skill_evidence"
    __table_args__ = (
        _check_in("source_type", ("resume", "assessment", "practice", "interview"), "ck_evidence_source"),
        CheckConstraint("num_nonnulls(resume_analysis_id, assessment_item_id, practice_attempt_id, "
                        "interview_turn_id) = 1", name="ck_evidence_one_source"),
        CheckConstraint("skill_id IS NOT NULL OR interview_dimension IS NOT NULL", name="ck_evidence_subject"),
        CheckConstraint("interview_dimension IS NULL OR interview_dimension IN "
                        "('relevance','correctness','completeness','reasoning','clarity')",
                        name="ck_evidence_dimension"),
        Index("ix_evidence_user_skill", "user_id", "skill_id", "observed_at"),
        Index("ix_evidence_user_dimension", "user_id", "interview_dimension", "observed_at"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True),
                                                        ForeignKey("target_roles.id", ondelete="CASCADE"))
    skill_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("skills.id"))
    interview_dimension: Mapped[str | None] = mapped_column(String(12))
    source_type: Mapped[str] = mapped_column(String(10), nullable=False)
    score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    resume_level: Mapped[int | None] = mapped_column(SmallInteger)
    difficulty_weight: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False, default=Decimal("1"))
    item_type: Mapped[str | None] = mapped_column(String(15))
    incomplete_attempt: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", default=False)
    resume_analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resume_analyses.id", ondelete="CASCADE"))
    assessment_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assessment_items.id", ondelete="CASCADE"))
    practice_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("practice_attempts.id", ondelete="CASCADE"))
    interview_turn_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("interview_turns.id", ondelete="CASCADE"))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = _created()


class GapReport(Base):
    __tablename__ = "gap_reports"
    __table_args__ = (Index("ix_gap_report_target_created", "target_id", "created_at"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),
                                                 ForeignKey("target_roles.id", ondelete="CASCADE"), nullable=False)
    trigger: Mapped[str] = mapped_column(String(30), nullable=False)
    skill_states: Mapped[list] = mapped_column(JSONB, nullable=False)
    dimension_scores: Mapped[dict] = mapped_column(JSONB, nullable=False)
    readiness_index: Mapped[int | None] = mapped_column(SmallInteger)
    resolved: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]", default=list)
    unassessable: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]", default=list)
    requirements_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scoring_version: Mapped[str] = mapped_column(String(10), nullable=False)
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", default=False)
    created_at: Mapped[datetime] = _created()


class SkillGap(Base):
    __tablename__ = "skill_gaps"
    __table_args__ = (
        _check_in("gap_type", ("G1", "G2", "G3", "G4", "G5", "G6"), "ck_gap_type"),
        CheckConstraint("skill_id IS NOT NULL OR interview_dimension IS NOT NULL", name="ck_gap_subject"),
        CheckConstraint("priority_score BETWEEN 0 AND 100", name="ck_gap_priority"),
        Index("ix_gap_report_rank", "gap_report_id", "rank"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    gap_report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gap_reports.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = _user_fk()
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),
                                                 ForeignKey("target_roles.id", ondelete="CASCADE"), nullable=False)
    skill_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("skills.id"))
    interview_dimension: Mapped[str | None] = mapped_column(String(12))
    gap_type: Mapped[str] = mapped_column(String(3), nullable=False)
    importance: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    severity: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    confidence_multiplier: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    priority_score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    rank: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    inputs: Mapped[dict] = mapped_column(JSONB, nullable=False)
    explanation: Mapped[dict] = mapped_column(JSONB, nullable=False)
    next_action: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _created()


# --------------------------------------------------------------------------- plans & resources
class LearningResource(Base):
    __tablename__ = "learning_resources"
    __table_args__ = (
        _check_in("format", ("doc", "article", "video", "course", "interactive", "notes"), "ck_resource_format"),
        _check_in("difficulty", ("beginner", "intermediate", "advanced"), "ck_resource_difficulty"),
        CheckConstraint("est_minutes BETWEEN 5 AND 180", name="ck_resource_minutes"),
        CheckConstraint("url LIKE 'https://%'", name="ck_resource_https"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    format: Mapped[str] = mapped_column(String(12), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(12), nullable=False)
    est_minutes: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_free: Mapped[bool] = mapped_column(Boolean, nullable=False)
    description: Mapped[str | None] = mapped_column(String(300))
    last_verified_at: Mapped[date | None] = mapped_column(Date)
    verification_note: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true", default=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class ResourceSkill(Base):
    __tablename__ = "resource_skills"
    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("learning_resources.id", ondelete="CASCADE"), primary_key=True)
    skill_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("skills.id", ondelete="CASCADE"),
                                                primary_key=True)
    topic: Mapped[str | None] = mapped_column(String(80))


class PreparationPlan(Base):
    __tablename__ = "preparation_plans"
    __table_args__ = (
        _check_in("status", ("active", "superseded"), "ck_plan_status"),
        Index("uq_plan_one_active", "target_id", unique=True, postgresql_where=text("status = 'active'")),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),
                                                 ForeignKey("target_roles.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    daily_minutes: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    horizon_days: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    generated_from_gap_report_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gap_reports.id", ondelete="SET NULL"))
    change_summary: Mapped[str | None] = mapped_column(Text)
    unscheduled: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]", default=list)
    last_rollover_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


TASK_TYPES = ("assess", "learn", "practice", "reassess", "resume", "interview")


class PreparationTask(Base):
    __tablename__ = "preparation_tasks"
    __table_args__ = (
        _check_in("task_type", TASK_TYPES, "ck_task_type"),
        _check_in("status", ("pending", "done", "skipped", "missed"), "ck_task_status"),
        CheckConstraint("estimated_minutes BETWEEN 5 AND 90", name="ck_task_minutes"),
        Index("ix_task_plan_date", "plan_id", "scheduled_date", "position"),
        Index("ix_task_user_status", "user_id", "status", "scheduled_date"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("preparation_plans.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = _user_fk()
    plan_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    task_type: Mapped[str] = mapped_column(String(10), nullable=False)
    skill_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("skills.id"))
    interview_dimension: Mapped[str | None] = mapped_column(String(12))
    gap_type: Mapped[str | None] = mapped_column(String(3))
    sequence_key: Mapped[str] = mapped_column(String(80), nullable=False)
    step_index: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("learning_resources.id", ondelete="SET NULL"))
    estimated_minutes: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(String(400))
    rationale: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(8), nullable=False, default="pending")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    linked_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


# --------------------------------------------------------------------------- AI usage
class AIRequest(Base):
    """Metadata about each provider call. Never stores prompt or response content."""
    __tablename__ = "ai_requests"
    __table_args__ = (
        _check_in("outcome", ("success", "invalid_output", "timeout", "provider_error", "quota_blocked",
                              "unavailable"), "ck_ai_outcome"),
        Index("ix_ai_user_created", "user_id", "created_at"),
        Index("ix_ai_created", "created_at"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    workflow: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(60))
    attempt: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = _created()
