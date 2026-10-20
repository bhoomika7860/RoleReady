"""FastAPI application factory: API under /api/v1 plus the built React SPA from the same origin."""
from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.security import CSRF_HEADER, CSRF_VALUE

log = logging.getLogger("roleready.http")

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")


def api_router() -> APIRouter:
    from app.modules.assessments.router import router as assessments
    from app.modules.auth.router import router as auth
    from app.modules.catalog.router import router as catalog
    from app.modules.dashboard.router import router as dashboard
    from app.modules.evidence.router import router as evidence
    from app.modules.health.router import router as health
    from app.modules.interviews.router import router as interviews
    from app.modules.plans.router import router as plans
    from app.modules.practice.router import router as practice
    from app.modules.profile.router import router as profile
    from app.modules.resources.router import router as resources
    from app.modules.resumes.router import router as resumes
    from app.modules.targets.router import router as targets

    api = APIRouter(prefix="/api/v1")
    for r in (health, auth, profile, catalog, targets, resumes, assessments, evidence, plans, resources, practice,
              interviews, dashboard):
        api.include_router(r)
    return api


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    settings.require_session_secret()  # fail fast and clearly if the secret is missing
    app = FastAPI(title="RoleReady API", version=settings.app_version,
                  docs_url=None if settings.is_production else "/api/docs", redoc_url=None,
                  openapi_url=None if settings.is_production else "/api/openapi.json")
    install_error_handlers(app)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        start = time.perf_counter()
        path = request.url.path
        if (path.startswith("/api/") and request.method in ("POST", "PUT", "PATCH", "DELETE")
                and request.headers.get(CSRF_HEADER) != CSRF_VALUE):
            response = JSONResponse(status_code=403, content={"error": {
                "code": "CSRF_HEADER_MISSING", "message": "Missing request header.", "details": {},
                "request_id": request_id, "retryable": False}})
        else:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), geolocation=(), microphone=(self)"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = CSP
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
            log.info("request", extra={"request_id": request_id, "method": request.method, "route": path,
                                       "status": response.status_code,
                                       "latency_ms": int((time.perf_counter() - start) * 1000),
                                       "user_id": getattr(request.state, "user_id", None)})
        return response

    app.include_router(api_router())
    _mount_spa(app, Path(settings.static_dir))
    return app


def _mount_spa(app: FastAPI, dist: Path) -> None:
    index = dist / "index.html"
    if not index.exists():
        @app.get("/", include_in_schema=False)
        def _no_frontend():
            return JSONResponse({"message": "Frontend not built. Run `npm run build` in frontend/ or use the Vite dev "
                                            "server on :5173."})
        return
    if (dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"error": {"code": "NOT_FOUND", "message": "Not found.",
                                                                    "details": {}, "retryable": False}})
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_file() and dist.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


app = create_app()
