"""AI gateway — the single entry point for every LLM call (SRS 8.2).

Steps per call: availability → per-user/global quota → provider call with timeout and one
transient retry → JSON parse → Pydantic validation (extra='forbid') → one repair retry with the
validation errors → return a validated object. Each provider call writes one `ai_requests` row
(metadata only — never prompt or response content) in its own short transaction.
"""
from __future__ import annotations

import json
import logging
import random
import re
import time
import uuid
from datetime import timedelta
from typing import TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select

from app.ai.providers import FakeProvider, LLMProvider, NvidiaProvider, ProviderError
from app.core.config import Settings, get_settings
from app.core.db import session_factory
from app.core.errors import AIQuotaExceeded, AIUnavailableError, AppError
from app.core.security import utcnow
from app.models import AIRequest

log = logging.getLogger("roleready.ai")
T = TypeVar("T", bound=BaseModel)


class AIFailed(AppError):
    """The provider was reached but no valid output was obtained (timeout, errors, invalid JSON)."""
    status_code, code, message = 502, "AI_INVALID_OUTPUT", "The AI service didn't return a usable answer."


def inline_schema(model: type[BaseModel]) -> dict:
    """Pydantic JSON schema with $refs inlined (some providers don't resolve $defs)."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(defs[node["$ref"].split("/")[-1]])
            return {k: resolve(v) for k, v in node.items() if k != "title"}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)


def json_skeleton(schema: dict) -> object:
    """A compact example of the expected JSON shape, derived from the (inlined) Pydantic schema.
    Strings show as "", enums as "a|b|c", nullable fields as null, arrays with one example element."""
    if "anyOf" in schema:
        non_null = [s for s in schema["anyOf"] if s.get("type") != "null"]
        if len(non_null) < len(schema["anyOf"]):
            return None if not non_null or non_null[0].get("type") == "string" else json_skeleton(non_null[0])
        return json_skeleton(non_null[0])
    if "enum" in schema:
        return "|".join(str(v) for v in schema["enum"])
    if "const" in schema:
        return schema["const"]
    t = schema.get("type")
    if t == "object":
        return {k: json_skeleton(v) for k, v in schema.get("properties", {}).items()}
    if t == "array":
        return [json_skeleton(schema.get("items", {}))]
    if t == "integer":
        return 0
    if t == "number":
        return 0.0
    if t == "boolean":
        return False
    return ""


def format_instructions(model: type[BaseModel]) -> str:
    shape = json.dumps(json_skeleton(inline_schema(model)), ensure_ascii=False)
    return ("\n\nOutput format: reply with ONLY one JSON object with exactly these keys (example shape — arrays may "
            "be empty or have many items; \"a|b\" means choose one value; null means unknown):\n" + shape)


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def extract_json(text: str) -> object:
    t = (text or "").strip()
    t = re.sub(r"<think>.*?</think>", "", t, flags=re.DOTALL).strip()
    t = _FENCE.sub("", t).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start, end = t.find("{"), t.rfind("}")
        if start != -1 and end > start:
            return json.loads(t[start:end + 1])
        raise


def escape_untrusted(text: str) -> str:
    return text.replace("</untrusted_document", "&lt;/untrusted_document")


def untrusted(kind: str, text: str) -> str:
    return f'<untrusted_document type="{kind}">\n{escape_untrusted(text)}\n</untrusted_document>'


class AIGateway:
    def __init__(self, provider: LLMProvider | None, settings: Settings | None = None):
        self.provider = provider
        self.settings = settings or get_settings()

    @property
    def available(self) -> bool:
        return self.provider is not None

    @property
    def model_name(self) -> str | None:
        return self.provider.model if self.provider else None

    # ---------------------------------------------------------------- quota
    def _check_quota(self, user_id: uuid.UUID | None) -> None:
        now = utcnow()
        mine = AIRequest.user_id == user_id if user_id is not None else False
        stmt = select(
            func.count(),
            func.count().filter(mine, AIRequest.created_at > now - timedelta(hours=1)),
            func.count().filter(mine),
        ).select_from(AIRequest).where(AIRequest.attempt == 1, AIRequest.outcome != "quota_blocked",
                                       AIRequest.created_at > now - timedelta(days=1))
        with session_factory()() as db:  # one round trip for all three counters
            global_day, hour, day = db.execute(stmt).one()
        if global_day >= self.settings.ai_global_daily_limit:
            raise AIUnavailableError("AI features are paused: the daily AI budget for this deployment is used up.")
        if user_id is None:
            return
        if hour >= self.settings.ai_hourly_limit or day >= self.settings.ai_daily_limit:
            window = "hour" if hour >= self.settings.ai_hourly_limit else "day"
            retry = 3600 if window == "hour" else 86400
            raise AIQuotaExceeded(f"You've used your AI allowance for this {window}. Non-AI features keep working.",
                                  headers={"Retry-After": str(retry)}, details={"window": window})

    def _log(self, *, user_id, workflow, prompt_version, model, latency_ms, outcome, error_code=None,
             input_tokens=None, output_tokens=None, attempt=1) -> None:
        try:
            with session_factory()() as db:
                db.add(AIRequest(user_id=user_id, workflow=workflow, provider=self.provider.name if self.provider
                                 else "none", model=(model or "none")[:120], prompt_version=prompt_version,
                                 input_tokens=input_tokens, output_tokens=output_tokens, latency_ms=latency_ms,
                                 outcome=outcome, error_code=error_code, attempt=attempt))
                db.commit()
        except Exception:  # logging must never break the user flow
            log.warning("ai_request_log_failed", extra={"workflow": workflow})

    # ---------------------------------------------------------------- run
    def run(self, *, workflow: str, prompt_version: str, system: str, user: str, output_model: type[T],
            user_id: uuid.UUID | None, max_tokens: int, temperature: float = 0.2,
            timeout_s: float | None = None) -> T:
        if not self.available:
            raise AIUnavailableError("AI features are not configured (NVIDIA_API_KEY / NVIDIA_MODEL missing).")
        self._check_quota(user_id)
        assert self.provider is not None
        schema = inline_schema(output_model)
        system = system + format_instructions(output_model)
        timeout = timeout_s or self.settings.llm_timeout_seconds
        messages_user = user
        attempt = 0
        # Hosted endpoints occasionally return short bursts of 5xx/429; two spaced retries ride those out.
        repairs_left, transient_left = 1, 2
        last_error = "unknown"
        while True:
            attempt += 1
            t0 = time.monotonic()
            try:
                result = self.provider.complete_json(system=system, user=messages_user, json_schema=schema,
                                                     max_tokens=max_tokens, temperature=temperature,
                                                     timeout_s=timeout, workflow=workflow)
            except ProviderError as exc:
                latency = int((time.monotonic() - t0) * 1000)
                outcome = "timeout" if exc.kind == "timeout" else "provider_error"
                self._log(user_id=user_id, workflow=workflow, prompt_version=prompt_version,
                          model=self.provider.model, latency_ms=latency, outcome=outcome,
                          error_code=f"{exc.kind}:{exc.status or ''}"[:60], attempt=attempt)
                log.warning("ai_provider_error", extra={"workflow": workflow, "kind": exc.kind,
                                                        "status": exc.status, "attempt": attempt})
                if exc.transient and transient_left > 0:
                    transient_left -= 1
                    backoff = (1.0, 3.0) if transient_left == 1 else (3.0, 5.0)
                    delay = min(exc.retry_after, 5.0) if exc.retry_after else random.uniform(*backoff)
                    time.sleep(delay)
                    continue
                if exc.kind == "timeout":
                    raise AIFailed("The AI service took too long to respond. Your input is saved — try again.",
                                   code="AI_TIMEOUT", status_code=504) from exc
                if exc.kind in ("auth", "model_unavailable"):
                    raise AIUnavailableError("The AI provider rejected the configuration (API key or model).",
                                             details={"provider_error": exc.kind}) from exc
                raise AIFailed("The AI service returned an error. Your input is saved — try again.",
                               code="AI_PROVIDER_ERROR", status_code=502) from exc

            latency = int((time.monotonic() - t0) * 1000)
            try:
                parsed = extract_json(result.content)
                obj = output_model.model_validate(parsed)
            except (json.JSONDecodeError, ValidationError, TypeError) as exc:
                last_error = (str(exc) if isinstance(exc, ValidationError) else "Response was not valid JSON.")[:1500]
                self._log(user_id=user_id, workflow=workflow, prompt_version=prompt_version, model=result.model,
                          latency_ms=latency, outcome="invalid_output", error_code=type(exc).__name__[:60],
                          input_tokens=result.input_tokens, output_tokens=result.output_tokens, attempt=attempt)
                if repairs_left > 0:
                    repairs_left -= 1
                    messages_user = (user + "\n\nYour previous reply was invalid. Problems:\n" + last_error +
                                     "\nReply again with ONLY a JSON object that matches the required schema.")
                    continue
                raise AIFailed() from exc

            self._log(user_id=user_id, workflow=workflow, prompt_version=prompt_version, model=result.model,
                      latency_ms=latency, outcome="success", input_tokens=result.input_tokens,
                      output_tokens=result.output_tokens, attempt=attempt)
            return obj


_gateway: AIGateway | None = None


def build_gateway(settings: Settings | None = None) -> AIGateway:
    s = settings or get_settings()
    if s.ai_provider == "fake":
        if s.is_production:
            raise RuntimeError("Fake AI provider refused in production.")
        return AIGateway(FakeProvider(), s)
    if not s.ai_configured:
        return AIGateway(None, s)
    assert s.nvidia_api_key is not None and s.nvidia_model
    return AIGateway(NvidiaProvider(s.nvidia_api_key.get_secret_value().strip(), s.nvidia_base_url, s.nvidia_model,
                                    s.nvidia_enable_thinking, structured_output=s.nvidia_structured_output), s)


def get_gateway() -> AIGateway:
    global _gateway
    if _gateway is None:
        _gateway = build_gateway()
    return _gateway


def set_gateway(gateway: AIGateway | None) -> None:
    """Test hook: inject a gateway (typically wrapping FakeProvider)."""
    global _gateway
    _gateway = gateway
