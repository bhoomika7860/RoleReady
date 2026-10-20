"""Pydantic output models for each AI workflow (extra='forbid', bounded lengths)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- W-1 resume structuring
class W1Education(Strict):
    institution: str = Field(max_length=200)
    degree: str | None = Field(default=None, max_length=150)
    field: str | None = Field(default=None, max_length=150)
    start: str | None = Field(default=None, max_length=20)
    end: str | None = Field(default=None, max_length=20)
    score: str | None = Field(default=None, max_length=40)
    details: list[str] = Field(default_factory=list, max_length=10)


class W1Experience(Strict):
    title: str = Field(max_length=150)
    organization: str | None = Field(default=None, max_length=150)
    location: str | None = Field(default=None, max_length=100)
    start: str | None = Field(default=None, max_length=20)
    end: str | None = Field(default=None, max_length=20)
    is_current: bool = False
    technologies: list[str] = Field(default_factory=list, max_length=30)
    bullets: list[str] = Field(default_factory=list, max_length=12)


class W1Project(Strict):
    name: str = Field(max_length=150)
    role: str | None = Field(default=None, max_length=100)
    start: str | None = Field(default=None, max_length=20)
    end: str | None = Field(default=None, max_length=20)
    technologies: list[str] = Field(default_factory=list, max_length=30)
    bullets: list[str] = Field(default_factory=list, max_length=12)


class W1Certification(Strict):
    name: str = Field(max_length=200)
    issuer: str | None = Field(default=None, max_length=150)
    date: str | None = Field(default=None, max_length=20)


class W1Output(Strict):
    summary: str | None = Field(default=None, max_length=1500)
    education: list[W1Education] = Field(default_factory=list, max_length=8)
    skills: list[str] = Field(default_factory=list, max_length=80)
    experience: list[W1Experience] = Field(default_factory=list, max_length=12)
    projects: list[W1Project] = Field(default_factory=list, max_length=12)
    certifications: list[W1Certification] = Field(default_factory=list, max_length=20)
    achievements: list[str] = Field(default_factory=list, max_length=20)
    unparsed_text: list[str] = Field(default_factory=list, max_length=60)
    notes: list[str] = Field(default_factory=list, max_length=10)


# ---------------------------------------------------------------- W-2 job description
class W2Requirement(Strict):
    phrase: str = Field(max_length=200)
    level: Literal["required", "preferred"]
    category: Literal["skill", "experience", "education", "other"]
    skill_slug: str | None = Field(default=None, max_length=50)
    evidence: str = Field(default="", max_length=400)


class W2Output(Strict):
    requirements: list[W2Requirement] = Field(default_factory=list, max_length=50)
    responsibilities: list[str] = Field(default_factory=list, max_length=20)
    experience_expectations: list[str] = Field(default_factory=list, max_length=10)
    collaboration: list[str] = Field(default_factory=list, max_length=10)
    tools: list[str] = Field(default_factory=list, max_length=30)
    notes: list[str] = Field(default_factory=list, max_length=10)


# ---------------------------------------------------------------- W-3 bullet rewrite
class W3Suggestion(Strict):
    text: str = Field(max_length=400)
    rationale: str = Field(default="", max_length=300)
    facts_used: list[str] = Field(default_factory=list, max_length=20)


class W3Question(Strict):
    id: str = Field(max_length=10)
    text: str = Field(max_length=200)


class W3Output(Strict):
    suggestions: list[W3Suggestion] = Field(default_factory=list, max_length=3)
    questions: list[W3Question] = Field(default_factory=list, max_length=4)
    notes: list[str] = Field(default_factory=list, max_length=5)


# ---------------------------------------------------------------- W-7 evaluation
class KeyPointJudgement(Strict):
    id: str = Field(max_length=20)
    credit: Literal["covered", "partial", "missing"]
    quote: str | None = Field(default=None, max_length=400)


class W7ShortOutput(Strict):
    key_points: list[KeyPointJudgement] = Field(max_length=12)
    feedback: str = Field(default="", max_length=800)
    notes: list[str] = Field(default_factory=list, max_length=5)


class DimensionScore(Strict):
    score: int = Field(ge=1, le=5)
    quote: str | None = Field(default=None, max_length=400)
    comment: str = Field(default="", max_length=400)


class W7Dimensions(Strict):
    relevance: DimensionScore
    correctness: DimensionScore
    completeness: DimensionScore
    reasoning: DimensionScore
    clarity: DimensionScore


class W7InterviewOutput(Strict):
    dimensions: W7Dimensions
    key_points: list[KeyPointJudgement] = Field(default_factory=list, max_length=12)
    strengths: list[str] = Field(default_factory=list, max_length=4)
    missing_concepts: list[str] = Field(default_factory=list, max_length=6)
    improvements: list[str] = Field(default_factory=list, max_length=5)
    example_answer: str | None = Field(default=None, max_length=2000)
    notes: list[str] = Field(default_factory=list, max_length=5)
