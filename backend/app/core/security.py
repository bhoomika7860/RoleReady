"""Session tokens and CSRF protection.

DEMO-ONLY AUTHENTICATION: login accepts a username or email without proving ownership of it.
Sessions themselves are conventional and server-validated:
  * the cookie holds 32 random bytes (URL-safe base64);
  * the database stores only HMAC-SHA256(SESSION_SECRET, token), so a leaked table cannot be
    replayed and tokens cannot be forged without the server secret;
  * expiry is 7 days, sliding, capped at 30 days from creation; logout revokes server-side.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings

SESSION_COOKIE = "rr_session"
CSRF_HEADER = "X-RoleReady-Client"
CSRF_VALUE = "web"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> bytes:
    secret = get_settings().require_session_secret()
    return hmac.new(secret, token.encode(), hashlib.sha256).digest()


def session_expiry(created_at: datetime | None = None) -> datetime:
    s = get_settings()
    now = utcnow()
    return min(now + timedelta(days=s.session_ttl_days),
               (created_at or now) + timedelta(days=s.session_max_age_days))


def should_renew(expires_at: datetime) -> bool:
    return expires_at - utcnow() < timedelta(hours=24)


def cookie_params() -> dict:
    s = get_settings()
    return {
        "key": SESSION_COOKIE,
        "httponly": True,
        "secure": s.secure_cookies,
        "samesite": "lax",
        "path": "/",
        "max_age": s.session_ttl_days * 86400,
    }
