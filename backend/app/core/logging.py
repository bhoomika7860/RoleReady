"""Structured JSON logs to stdout. Request bodies are never logged (SRS NFR-034)."""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

_RESERVED = set(vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()) | {"message", "asctime"}
_SENSITIVE_KEYS = {"password", "token", "cookie", "authorization", "api_key", "database_url", "session_secret",
                   "resume_text", "raw_text", "answer_text", "jd_text", "prompt", "response_body"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            payload[key] = "[REDACTED]" if key.lower() in _SENSITIVE_KEYS else value
        if record.exc_info and record.exc_info[0] is not None:
            payload["error_type"] = record.exc_info[0].__name__
            payload["trace"] = self.formatException(record.exc_info)[-2000:]
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "pdfminer", "pdfplumber", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
