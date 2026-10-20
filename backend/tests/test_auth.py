from datetime import timedelta

from sqlalchemy import select, update

from app.core.security import SESSION_COOKIE, hash_session_token, utcnow
from app.models import User, UserSession
from tests.conftest import make_client


def test_login_with_email_creates_user_and_secure_session(app, db, fake_ai):
    c = make_client(app)
    r = c.post("/api/v1/auth/login", json={"identifier": "  Priya.S@Example.COM "})
    assert r.status_code == 200
    body = r.json()
    assert body["is_new_user"] is True and body["redirect_to"] == "/app/onboarding"
    assert body["user"]["identifier"] == "priya.s@example.com"
    assert body["auth_mode"] == "demo_identifier"
    cookie = r.headers["set-cookie"]
    assert SESSION_COOKIE in cookie and "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
    # only a hash of the token is stored
    token = c.cookies.get(SESSION_COOKIE)
    sess = db.scalar(select(UserSession))
    assert sess.token_hash == hash_session_token(token) and token.encode() != sess.token_hash
    assert c.get("/api/v1/auth/me").json()["user"]["identifier"] == "priya.s@example.com"


def test_login_with_username_and_returning_user(app, fake_ai):
    c1 = make_client(app)
    first = c1.post("/api/v1/auth/login", json={"identifier": "Riya_K"}).json()
    c2 = make_client(app)
    second = c2.post("/api/v1/auth/login", json={"identifier": "riya_k"}).json()
    assert first["is_new_user"] is True and second["is_new_user"] is False
    assert first["user"]["id"] == second["user"]["id"]
    assert second["user"]["identifier_kind"] == "username"


def test_returning_onboarded_user_goes_to_dashboard(app, db, fake_ai):
    c = make_client(app)
    c.post("/api/v1/auth/login", json={"identifier": "arjun@example.com"})
    c.patch("/api/v1/profile", json={"complete_onboarding": True})
    r = make_client(app).post("/api/v1/auth/login", json={"identifier": "ARJUN@example.com"})
    assert r.json()["redirect_to"] == "/app/dashboard"


def test_invalid_identifiers_are_rejected(app, fake_ai):
    c = make_client(app)
    for bad in ["", "   ", "a", "no spaces allowed", "x@y", "bad..dots@example.com", "-start", "a" * 40,
                "user@@example.com"]:
        r = c.post("/api/v1/auth/login", json={"identifier": bad})
        assert r.status_code == 422, bad
        err = r.json()["error"]
        assert err["code"] == "VALIDATION_ERROR" and "identifier" in err["details"]["fields"]
    assert c.get("/api/v1/auth/me").status_code == 401


def test_client_supplied_user_id_is_not_trusted(app, fake_ai):
    c = make_client(app)
    c.cookies.set(SESSION_COOKIE, "made-up-token")
    r = c.get("/api/v1/auth/me", headers={"X-User-Id": "00000000-0000-0000-0000-000000000001"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"


def test_logout_revokes_session_even_if_cookie_replayed(app, fake_ai):
    c = make_client(app)
    c.post("/api/v1/auth/login", json={"identifier": "meera@example.com"})
    token = c.cookies.get(SESSION_COOKIE)
    assert c.post("/api/v1/auth/logout").status_code == 204
    replay = make_client(app)
    replay.cookies.set(SESSION_COOKIE, token)
    assert replay.get("/api/v1/auth/me").status_code == 401
    assert replay.get("/api/v1/dashboard").status_code == 401


def test_expired_session_is_rejected(app, db, fake_ai):
    c = make_client(app)
    c.post("/api/v1/auth/login", json={"identifier": "expired@example.com"})
    db.execute(update(UserSession).values(expires_at=utcnow() - timedelta(minutes=1)))
    db.commit()
    assert c.get("/api/v1/auth/me").status_code == 401


def test_session_slides_when_close_to_expiry(app, db, fake_ai):
    c = make_client(app)
    c.post("/api/v1/auth/login", json={"identifier": "slide@example.com"})
    soon = utcnow() + timedelta(hours=2)
    db.execute(update(UserSession).values(expires_at=soon))
    db.commit()
    assert c.get("/api/v1/auth/me").status_code == 200
    db.expire_all()
    assert db.scalar(select(UserSession.expires_at)) > soon + timedelta(days=1)


def test_mutations_require_csrf_header(app, fake_ai):
    c = make_client(app)
    c.post("/api/v1/auth/login", json={"identifier": "csrf@example.com"})
    r = c.patch("/api/v1/profile", json={"preferred_name": "X"}, headers={"X-RoleReady-Client": ""})
    assert r.status_code == 403 and r.json()["error"]["code"] == "CSRF_HEADER_MISSING"


def test_login_rate_limit(app, fake_ai, monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "rate_limit_enabled", True)
    c = make_client(app)
    codes = [c.post("/api/v1/auth/login", json={"identifier": f"u{i}@example.com"}).status_code for i in range(12)]
    assert codes[:10] == [200] * 10 and codes[-1] == 429


def test_profile_update_and_onboarding_moves_forward_only(login, fake_ai):
    c = login("profile@example.com")
    r = c.patch("/api/v1/profile", json={"preferred_name": "  Priya   S ", "experience_level": "fresher",
                                         "onboarding_step": 3})
    assert r.json()["preferred_name"] == "Priya S" and r.json()["onboarding_step"] == 3
    r = c.patch("/api/v1/profile", json={"onboarding_step": 2})
    assert r.json()["onboarding_step"] == 3
    assert c.patch("/api/v1/profile", json={"timezone": "Mars/Base"}).status_code == 422
