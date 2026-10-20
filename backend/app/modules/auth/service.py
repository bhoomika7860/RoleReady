"""Identifier-only DEMO authentication.

This mode lets anyone who types an identifier act as that account. It exists because the hackathon
brief asks for password-free access; it is NOT identity verification. The `AuthMethod` boundary
below keeps the rest of the app independent of how identity is proven, so email OTP / magic links
can replace `DemoIdentifierAuth` without touching sessions or any other module.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ValidationFailed
from app.core.security import hash_session_token, new_session_token, session_expiry, utcnow
from app.models import User, UserSession

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")
USERNAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{1,30})[a-z0-9]$")

AUTH_MODE = "demo_identifier"


@dataclass(frozen=True)
class NormalisedIdentifier:
    value: str
    kind: str  # "email" | "username"


def normalise_identifier(raw: str) -> NormalisedIdentifier:
    value = (raw or "").strip()
    if not value:
        raise ValidationFailed("Enter a username or email address.", details={"fields": {
            "identifier": "Enter a username or email address."}})
    if "@" in value:
        value = value.lower()
        if len(value) > 254 or not EMAIL_RE.match(value) or ".." in value:
            raise ValidationFailed("That doesn't look like a valid email address.", details={"fields": {
                "identifier": "That doesn't look like a valid email address."}})
        return NormalisedIdentifier(value, "email")
    value = value.lower()
    if not USERNAME_RE.match(value) or ".." in value:
        msg = ("Usernames are 3–32 characters: letters, numbers, dots, dashes or underscores, "
               "starting and ending with a letter or number.")
        raise ValidationFailed(msg, details={"fields": {"identifier": msg}})
    return NormalisedIdentifier(value, "username")


class AuthMethod(Protocol):
    def authenticate(self, db: Session, credential: dict) -> tuple[User, bool]: ...


class DemoIdentifierAuth:
    """Find-or-create a user by normalised identifier. Returns (user, created)."""

    def authenticate(self, db: Session, credential: dict) -> tuple[User, bool]:
        ident = normalise_identifier(credential.get("identifier", ""))
        user = db.scalar(select(User).where(User.identifier == ident.value))
        if user is not None:
            return user, False
        user = User(identifier=ident.value, identifier_kind=ident.kind)
        db.add(user)
        try:
            db.flush()
        except IntegrityError:  # concurrent first login with the same identifier
            db.rollback()
            user = db.scalar(select(User).where(User.identifier == ident.value))
            assert user is not None
            return user, False
        return user, True


def start_session(db: Session, user: User, user_agent: str | None) -> str:
    token = new_session_token()
    now = utcnow()
    db.add(UserSession(user_id=user.id, token_hash=hash_session_token(token), expires_at=session_expiry(now),
                       user_agent=(user_agent or "")[:200] or None, last_seen_at=now))
    user.last_login_at = now
    # lazy cleanup of this user's long-dead sessions
    db.execute(update(UserSession).where(UserSession.user_id == user.id, UserSession.expires_at < now,
                                         UserSession.revoked_at.is_(None)).values(revoked_at=now))
    return token


def login(db: Session, identifier: str, user_agent: str | None,
          method: AuthMethod | None = None) -> tuple[User, str, bool]:
    user, created = (method or DemoIdentifierAuth()).authenticate(db, {"identifier": identifier})
    token = start_session(db, user, user_agent)
    db.commit()
    return user, token, created


def logout(db: Session, token: str | None) -> None:
    if not token or len(token) > 100:
        return
    db.execute(update(UserSession).where(UserSession.token_hash == hash_session_token(token),
                                         UserSession.revoked_at.is_(None)).values(revoked_at=utcnow()))
    db.commit()
