from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import select, text

from app.ai.gateway import get_gateway
from app.core.config import get_settings
from app.core.db import session_factory
from app.models import Role

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def health():
    s = get_settings()
    gw = get_gateway()
    return {"status": "ok", "version": s.app_version, "env": s.app_env,
            "ai": "enabled" if gw.available else "disabled", "ai_provider": gw.provider.name if gw.provider else None}


def _alembic_head() -> str | None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from app.core.config import BACKEND_ROOT
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return ScriptDirectory.from_config(cfg).get_current_head()


@router.get("/ready")
def ready():
    checks = {"db": "fail", "migrations": "fail", "catalogue": "fail"}
    try:
        with session_factory()() as db:
            db.execute(text("SELECT 1"))
            checks["db"] = "ok"
            current = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
            checks["migrations"] = "ok" if current == _alembic_head() else "pending"
            checks["catalogue"] = "ok" if db.scalar(select(Role.id).limit(1)) else "empty"
    except Exception:
        pass
    ok = all(v == "ok" for v in checks.values())
    if ok:
        return checks
    code = "DB_UNAVAILABLE" if checks["db"] != "ok" else "CATALOGUE_EMPTY" if checks["catalogue"] != "ok" else \
        "MIGRATIONS_PENDING"
    return JSONResponse(status_code=503, content={**checks, "error": {"code": code}})
