from pydantic import BaseModel
from sqlalchemy import select

from app.ai.gateway import AIFailed, AIGateway
from app.ai.providers import FakeProvider, ProviderError
from app.core.config import get_settings
from app.core.errors import AIQuotaExceeded, AIUnavailableError
from app.models import AIRequest
from app.seed.loader import SeedError, seed, validate_question


class Out(BaseModel):
    ok: bool


def gw(handler):
    return AIGateway(FakeProvider(handlers={"T": handler}), get_settings())


def run(g, user_id=None):
    return g.run(workflow="T", prompt_version="t1", system="s", user="u", output_model=Out, user_id=user_id,
                 max_tokens=10)


def test_repair_retry_then_success_logs_metadata_only(db):
    calls = iter(["not json at all", '```json\n{"ok": true}\n```'])
    assert run(gw(lambda s, u: next(calls))).ok is True
    rows = db.scalars(select(AIRequest).order_by(AIRequest.attempt)).all()
    assert [r.outcome for r in rows] == ["invalid_output", "success"]
    assert not hasattr(AIRequest, "prompt") and not hasattr(AIRequest, "response")


def test_invalid_twice_raises(db):
    try:
        run(gw(lambda s, u: '{"ok": "maybe", "extra": 1}'))
        raise AssertionError("expected failure")
    except AIFailed:
        pass


def test_transient_error_retried_once(db, monkeypatch):
    monkeypatch.setattr("app.ai.gateway.time.sleep", lambda s: None)
    calls = iter([ProviderError("rate_limited", 429, "slow down", retry_after=1), {"ok": True}])
    assert run(gw(lambda s, u: next(calls))).ok is True


def test_timeout_twice_is_reported_not_faked(db, monkeypatch):
    monkeypatch.setattr("app.ai.gateway.time.sleep", lambda s: None)
    try:
        run(gw(lambda s, u: ProviderError("timeout")))
        raise AssertionError("expected failure")
    except AIFailed as exc:
        assert exc.code == "AI_TIMEOUT"


def test_missing_key_means_unavailable_not_fake():
    g = AIGateway(None, get_settings())
    assert g.available is False
    try:
        run(g)
        raise AssertionError("expected failure")
    except AIUnavailableError:
        pass


def test_per_user_quota(login, db, monkeypatch):
    c = login("quota@example.com")
    uid = c.get("/api/v1/auth/me").json()["user"]["id"]
    monkeypatch.setattr(get_settings(), "ai_hourly_limit", 2)
    g = gw(lambda s, u: {"ok": True})
    run(g, uid)
    run(g, uid)
    try:
        run(g, uid)
        raise AssertionError("expected quota error")
    except AIQuotaExceeded as exc:
        assert exc.headers.get("Retry-After")


def test_fake_provider_refused_in_production(monkeypatch):
    from app.core.config import ConfigError, Settings
    try:
        Settings(app_env="production", ai_provider="fake", session_secret="x" * 40)
        raise AssertionError("expected ConfigError")
    except (ConfigError, ValueError):
        pass


def test_error_envelope_and_status_codes(client):
    r = client.get("/api/v1/targets/not-a-uuid")
    assert r.status_code == 404 and set(r.json()["error"]) >= {"code", "message", "request_id", "retryable"}
    r = client.post("/api/v1/targets", json={"role_slug": "backend-dev", "daily_minutes": 17})
    assert r.status_code == 422 and "daily_minutes" in r.json()["error"]["details"]["fields"]
    r = client.post("/api/v1/targets", json={"role_slug": "astronaut", "daily_minutes": 60})
    assert r.status_code == 404 and r.json()["error"]["code"] == "ROLE_NOT_FOUND"
    assert client.get("/api/v1/does-not-exist").status_code == 404
    r = client.get("/api/v1/health")
    assert r.headers["X-Request-ID"] and "default-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_second_target_requires_archive_confirmation(client, target):
    r = client.post("/api/v1/targets", json={"role_slug": "frontend-dev", "daily_minutes": 60})
    assert r.status_code == 409 and r.json()["error"]["code"] == "ACTIVE_TARGET_EXISTS"
    r = client.post("/api/v1/targets", json={"role_slug": "frontend-dev", "daily_minutes": 60,
                                             "archive_current": True})
    assert r.status_code == 201
    old = client.get(f"/api/v1/targets/{target['id']}").json()
    assert old["status"] == "archived"
    assert client.patch(f"/api/v1/targets/{target['id']}", json={"daily_minutes": 90}).status_code == 409


def test_seed_is_idempotent_and_validates(db):
    from app.models import Question
    before = len(db.scalars(select(Question)).all())
    counts = seed(db)
    assert len(db.scalars(select(Question)).all()) == before
    assert counts["questions"] >= 120 and counts["skills"] == 40 and counts["roles"] == 4
    bad = {"slug": "x", "skill": "sql", "topic": "t", "type": "mcq_single", "difficulty": "easy", "purpose": "any",
           "prompt": "p", "explanation": "e", "options": [{"id": "a", "text": "1"}, {"id": "b", "text": "2"}],
           "answer": "a"}
    try:
        validate_question(bad, "test.yaml", {"sql"})
        raise AssertionError("expected SeedError")
    except SeedError as exc:
        assert "3–6 options" in str(exc)


def test_unverified_resources_are_not_served(client):
    r = client.get("/api/v1/resources", params={"page_size": 50}).json()
    assert r["total"] > 0 and all(i["last_verified_at"] for i in r["items"])
    urls = {i["url"] for i in r["items"]}
    assert "https://leetcode.com/explore/" not in urls  # failed the link check
