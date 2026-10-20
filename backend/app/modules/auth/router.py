from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import ratelimit
from app.core.db import get_db
from app.core.deps import current_user
from app.core.security import SESSION_COOKIE, cookie_params
from app.models import TargetRole, User
from app.modules.auth import service

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    identifier: str = Field(max_length=300)


class UserOut(BaseModel):
    id: str
    identifier: str
    identifier_kind: str
    preferred_name: str | None
    experience_level: str | None
    timezone: str
    onboarding_step: int
    onboarding_completed: bool
    is_demo: bool


class MeOut(BaseModel):
    user: UserOut
    active_target_id: str | None
    auth_mode: str = service.AUTH_MODE


class LoginOut(MeOut):
    is_new_user: bool
    redirect_to: str


def user_out(u: User) -> UserOut:
    return UserOut(id=str(u.id), identifier=u.identifier, identifier_kind=u.identifier_kind,
                   preferred_name=u.preferred_name, experience_level=u.experience_level, timezone=u.timezone,
                   onboarding_step=u.onboarding_step, onboarding_completed=u.onboarding_completed_at is not None,
                   is_demo=u.is_demo)


def active_target_id(db: Session, user_id) -> str | None:
    tid = db.scalar(select(TargetRole.id).where(TargetRole.user_id == user_id, TargetRole.status == "active"))
    return str(tid) if tid else None


@router.post("/login", response_model=LoginOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    ratelimit.check("login_ip", ip, limit=10, window_s=60)
    user, token, created = service.login(db, body.identifier, request.headers.get("user-agent"))
    response.set_cookie(value=token, **cookie_params())
    completed = user.onboarding_completed_at is not None
    return LoginOut(user=user_out(user), active_target_id=active_target_id(db, user.id), is_new_user=created,
                    redirect_to="/app/dashboard" if completed else "/app/onboarding")


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    service.logout(db, request.cookies.get(SESSION_COOKIE))
    params = cookie_params()
    response.delete_cookie(key=SESSION_COOKIE, path="/", secure=params["secure"], httponly=True, samesite="lax")
    response.status_code = 204
    return response


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return MeOut(user=user_out(user), active_target_id=active_target_id(db, user.id))
