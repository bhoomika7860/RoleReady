"""Request dependencies: current user resolution and user-scoped lookups (SRS FR-006, 10.4)."""
from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TypeVar

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import NotFound, Unauthenticated
from app.core.security import SESSION_COOKIE, hash_session_token, session_expiry, should_renew, utcnow
from app.models import Base, User, UserSession

M = TypeVar("M", bound=Base)


def resolve_session(db: Session, token: str | None) -> tuple[User, UserSession] | None:
    if not token or len(token) > 100:
        return None
    row = db.execute(select(UserSession, User).join(User, User.id == UserSession.user_id)
                     .where(UserSession.token_hash == hash_session_token(token))).first()
    now = utcnow()
    if row is None:
        return None
    sess, user = row
    if sess.revoked_at is not None or sess.expires_at <= now:
        return None
    # Write only when something meaningful changes (renewal, or last_seen older than 5 minutes).
    if should_renew(sess.expires_at):
        sess.expires_at = session_expiry(sess.created_at)
        sess.last_seen_at = now
        db.commit()
    elif sess.last_seen_at is None or now - sess.last_seen_at > timedelta(minutes=5):
        sess.last_seen_at = now
        db.commit()
    return user, sess


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    resolved = resolve_session(db, request.cookies.get(SESSION_COOKIE))
    if resolved is None:
        raise Unauthenticated()
    user, _ = resolved
    request.state.user_id = str(user.id)
    return user


def owned(db: Session, model: type[M], obj_id: uuid.UUID | str, user_id: uuid.UUID) -> M:
    """Fetch a row by ID only if it belongs to `user_id`; foreign rows look exactly like missing ones."""
    try:
        oid = obj_id if isinstance(obj_id, uuid.UUID) else uuid.UUID(str(obj_id))
    except ValueError as exc:
        raise NotFound() from exc
    row = db.scalar(select(model).where(model.id == oid, model.user_id == user_id))  # type: ignore[attr-defined]
    if row is None:
        raise NotFound()
    return row
