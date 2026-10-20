"""Domain errors and the standard error envelope (SRS 11.2).

Services raise `AppError` subclasses; the handlers below turn them into
{"error": {code, message, details, request_id, retryable}} without leaking internals.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("roleready.errors")

RETRYABLE_STATUSES = {429, 502, 503, 504}


class AppError(Exception):
    status_code = 400
    code = "BAD_REQUEST"
    message = "The request could not be processed."

    def __init__(self, message: str | None = None, *, code: str | None = None, status_code: int | None = None,
                 details: dict[str, Any] | None = None, headers: dict[str, str] | None = None):
        super().__init__(message or self.message)
        self.message = message or self.message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details or {}
        self.headers = headers or {}


class NotFound(AppError):
    status_code, code, message = 404, "NOT_FOUND", "Not found."


class Unauthenticated(AppError):
    status_code, code, message = 401, "UNAUTHENTICATED", "Please log in to continue."


class Forbidden(AppError):
    status_code, code, message = 403, "FORBIDDEN", "You can't do that."


class Conflict(AppError):
    status_code, code, message = 409, "CONFLICT", "That conflicts with the current state."


class ValidationFailed(AppError):
    status_code, code, message = 422, "VALIDATION_ERROR", "Some fields are invalid."


class RateLimited(AppError):
    status_code, code, message = 429, "RATE_LIMITED", "Too many requests. Please wait and try again."


class AIUnavailableError(AppError):
    status_code, code, message = 503, "AI_UNAVAILABLE", "AI features are not available right now."


class AIQuotaExceeded(AppError):
    status_code, code, message = 429, "AI_QUOTA_EXCEEDED", "You've reached the AI usage limit for now."


def _envelope(request: Request, status: int, code: str, message: str, details: dict | None = None,
              headers: dict | None = None) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    body = {"error": {"code": code, "message": message, "details": details or {}, "request_id": request_id,
                      "retryable": status in RETRYABLE_STATUSES}}
    return JSONResponse(status_code=status, content=body, headers=headers)


def _field_path(loc: tuple) -> str:
    parts = [str(p) for p in loc if p not in ("body", "query", "path")]
    return ".".join(parts) or "request"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        return _envelope(request, exc.status_code, exc.code, exc.message, exc.details, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        fields: dict[str, str] = {}
        for err in exc.errors():
            msg = err.get("msg", "Invalid value")
            fields[_field_path(tuple(err.get("loc", ())))] = msg.removeprefix("Value error, ")
        return _envelope(request, 422, "VALIDATION_ERROR", "Some fields are invalid.", {"fields": fields})

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 413: "PAYLOAD_TOO_LARGE"}.get(exc.status_code,
                                                                                            "BAD_REQUEST")
        message = "Not found." if exc.status_code == 404 else (exc.detail if isinstance(exc.detail, str)
                                                               else "Request failed.")
        return _envelope(request, exc.status_code, code, message)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.exception("unhandled_error", extra={"request_id": getattr(request.state, "request_id", None),
                                                "error_type": type(exc).__name__})
        return _envelope(request, 500, "INTERNAL_ERROR", "Something went wrong on our side. Please try again.")
