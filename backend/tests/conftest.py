"""Test harness: an isolated embedded PostgreSQL (pgserver) per test session — never Supabase — and an
explicitly injected FakeProvider for every AI call."""
from __future__ import annotations

import os
import re
import tempfile

import pytest

_PG_DIR = tempfile.mkdtemp(prefix="roleready-test-pg-")
import pgserver  # noqa: E402

_SERVER = pgserver.get_server(_PG_DIR, cleanup_mode="delete")
TEST_DB_URL = _SERVER.get_uri()

# Environment variables override .env, so the real DATABASE_URL / provider are never used by tests.
os.environ.update({
    "APP_ENV": "test", "DATABASE_URL": TEST_DB_URL, "AI_PROVIDER": "fake", "RATE_LIMIT_ENABLED": "false",
    "SESSION_SECRET": "test-session-secret-0123456789abcdef0123456789", "LOG_LEVEL": "WARNING",
    "NVIDIA_API_KEY": "", "STATIC_DIR": "/nonexistent",
})

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.ai.gateway import AIGateway, set_gateway  # noqa: E402
from app.ai.providers import FakeProvider, ProviderError  # noqa: E402
from app.core.config import BACKEND_ROOT, get_settings  # noqa: E402
from app.core.db import get_engine, init_engine, session_factory  # noqa: E402

get_settings.cache_clear()
assert "supabase" not in get_settings().sqlalchemy_url(), "tests must never use the real database"
init_engine()

_cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
_cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
command.upgrade(_cfg, "head")

from app.seed.loader import seed  # noqa: E402

with session_factory()() as _db:
    SEED_COUNTS = seed(_db)

from app.main import create_app  # noqa: E402

USER_TABLES = ["users", "ai_requests"]


# ------------------------------------------------------------------ fake AI
def _between(user: str, tag: str) -> str:
    m = re.search(rf'<untrusted_document type="{tag}">\n(.*)\n</untrusted_document>', user, re.DOTALL)
    return m.group(1) if m else ""


def default_w1(system: str, user: str):
    text_ = _between(user, "resume")
    lines = [ln.strip() for ln in text_.split("\n") if ln.strip()]
    bullets = [ln.lstrip("•- ").strip() for ln in lines if ln.startswith(("•", "-"))]
    return {"summary": None, "education": [{"institution": "Example Institute of Technology", "degree": "B.Tech",
                                            "field": "Computer Science", "start": "2022", "end": "2026",
                                            "score": None, "details": []}],
            "skills": ["Python", "SQL", "Git"],
            "experience": [],
            "projects": [{"name": "Campus Events API", "role": None, "start": None, "end": None,
                          "technologies": ["Python", "FastAPI", "PostgreSQL"], "bullets": bullets[:3]}],
            "certifications": [], "achievements": [], "unparsed_text": [], "notes": []}


def default_w2(system: str, user: str):
    jd = _between(user, "job_description")
    reqs = []
    for slug, phrase in (("python", "Python"), ("postgresql", "PostgreSQL"), ("rest-api", "REST APIs"),
                         ("docker", "Docker")):
        if phrase.lower() in jd.lower():
            level = "preferred" if slug == "docker" and "nice to have" in jd.lower() else "required"
            reqs.append({"phrase": phrase, "level": level, "category": "skill", "skill_slug": slug,
                         "evidence": phrase})
    return {"requirements": reqs, "responsibilities": ["Build backend services"], "experience_expectations": [],
            "collaboration": ["Work with a small team"], "tools": [], "notes": []}


def default_w7(system: str, user: str):
    answer = _between(user, "candidate_answer")
    words = answer.split()
    quote = " ".join(words[:6]) if words else None
    if "Score five dimensions" in system:
        dim = {"score": 4, "quote": quote, "comment": "Clear and relevant."}
        return {"dimensions": {k: dim for k in ("relevance", "correctness", "completeness", "reasoning", "clarity")},
                "key_points": [], "strengths": ["Direct", "Accurate"], "missing_concepts": ["Trade-offs"],
                "improvements": ["Add an example"], "example_answer": "A strong answer explains the idea and why.",
                "notes": []}
    kp_ids = re.findall(r"^- (kp\d+):", user, re.MULTILINE)
    return {"key_points": [{"id": k, "credit": "covered", "quote": quote} for k in kp_ids],
            "feedback": "Good coverage.", "notes": []}


def default_w3(system: str, user: str):
    return {"suggestions": [{"text": "Built a FastAPI backend with PostgreSQL for campus event registration",
                             "rationale": "Stronger verb", "facts_used": ["FastAPI", "PostgreSQL"]}],
            "questions": [{"id": "q1", "text": "About how many students used it?"}], "notes": []}


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch):
    monkeypatch.setattr("app.ai.gateway.time.sleep", lambda s: None)


@pytest.fixture
def fake_ai():
    provider = FakeProvider(handlers={"W-1": default_w1, "W-2": default_w2, "W-3": default_w3, "W-7": default_w7})
    set_gateway(AIGateway(provider, get_settings()))
    yield provider
    set_gateway(None)


@pytest.fixture
def no_ai():
    set_gateway(AIGateway(None, get_settings()))
    yield
    set_gateway(None)


@pytest.fixture
def failing_ai():
    def boom(system, user):
        return ProviderError("server_error", 503, "unavailable")
    provider = FakeProvider(handlers={k: boom for k in ("W-1", "W-2", "W-3", "W-7")})
    set_gateway(AIGateway(provider, get_settings()))
    yield provider
    set_gateway(None)


# ------------------------------------------------------------------ app + db
@pytest.fixture(scope="session")
def app():
    return create_app()


@pytest.fixture(autouse=True)
def clean_db():
    yield
    # DELETE (not TRUNCATE … CASCADE, which would also empty catalogue tables that merely reference users)
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM ai_requests"))
        conn.execute(text("DELETE FROM users"))
    from app.core import ratelimit
    ratelimit.reset()


@pytest.fixture
def db():
    s = session_factory()()
    yield s
    s.close()


def make_client(app) -> TestClient:
    c = TestClient(app, base_url="https://testserver")
    c.headers.update({"X-RoleReady-Client": "web"})
    return c


@pytest.fixture
def client(app, fake_ai):
    """A logged-in client for the default test user."""
    c = make_client(app)
    assert c.post("/api/v1/auth/login", json={"identifier": "student@example.com"}).status_code == 200
    return c


@pytest.fixture
def login(app):
    def _login(identifier: str = "priya@example.com") -> TestClient:
        c = make_client(app)
        r = c.post("/api/v1/auth/login", json={"identifier": identifier})
        assert r.status_code == 200, r.text
        return c
    return _login


SAMPLE_JD = (
    "Backend Engineer (Fresher) at a fictional fintech. You will build and maintain REST APIs in Python and "
    "design PostgreSQL schemas for payments data. Requirements: Python, PostgreSQL, REST APIs, Git, and solid "
    "data structures. Docker (nice to have). You will collaborate with product and QA in a small team and "
    "write tests for your code. Good communication skills are expected."
)


@pytest.fixture
def target(client):
    r = client.post("/api/v1/targets", json={"role_slug": "backend-dev", "daily_minutes": 60})
    assert r.status_code == 201, r.text
    return r.json()["target"]
