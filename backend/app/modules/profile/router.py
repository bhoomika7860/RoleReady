from __future__ import annotations

from zoneinfo import available_timezones

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import current_user
from app.core.errors import ValidationFailed
from app.core.security import utcnow
from app.models import User
from app.modules.auth.router import UserOut, user_out

router = APIRouter(prefix="/profile", tags=["profile"])


class ProfilePatch(BaseModel):
    preferred_name: str | None = Field(default=None, max_length=100)
    experience_level: str | None = Field(default=None, pattern="^(student|fresher|early_career)$")
    timezone: str | None = Field(default=None, max_length=64)
    onboarding_step: int | None = Field(default=None, ge=1, le=5)
    complete_onboarding: bool | None = None

    @field_validator("preferred_name")
    @classmethod
    def _name(cls, v):
        if v is None:
            return v
        v = " ".join(v.split())
        if not v:
            raise ValueError("Enter a name, or leave it empty.")
        return v


@router.get("", response_model=UserOut)
def get_profile(user: User = Depends(current_user)):
    return user_out(user)


@router.patch("", response_model=UserOut)
def patch_profile(body: ProfilePatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    data = body.model_dump(exclude_unset=True)
    if "timezone" in data and data["timezone"] not in available_timezones():
        raise ValidationFailed(details={"fields": {"timezone": "Unknown timezone."}})
    for key in ("preferred_name", "experience_level", "timezone"):
        if key in data and data[key] is not None:
            setattr(user, key, data[key])
    if data.get("onboarding_step"):
        user.onboarding_step = max(user.onboarding_step, data["onboarding_step"])  # only moves forward
    if data.get("complete_onboarding"):
        user.onboarding_step = 5
        user.onboarding_completed_at = user.onboarding_completed_at or utcnow()
    db.commit()
    return user_out(user)
