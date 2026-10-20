"""LLM provider adapters.

NvidiaProvider talks to NVIDIA's hosted, OpenAI-compatible Chat Completions API
(POST {NVIDIA_BASE_URL}/chat/completions, `Authorization: Bearer <key>`). Optional request
features are capability-detected: `response_format: json_schema` (structured output) and
`chat_template_kwargs.enable_thinking` (reasoning on/off for Nemotron-style models). If the
selected model rejects either, the adapter drops it for that model and relies on the gateway's
parse/validate/repair path instead.

FakeProvider is for automated tests only (refused when APP_ENV=production).
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

import httpx


@dataclass
class ProviderResult:
    content: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None


class ProviderError(Exception):
    """kind: timeout | rate_limited | server_error | bad_request | auth | model_unavailable | network"""

    def __init__(self, kind: str, status: int | None = None, message: str = "", retry_after: float | None = None):
        super().__init__(f"{kind} ({status}): {message}")
        self.kind = kind
        self.status = status
        self.message = message
        self.retry_after = retry_after

    @property
    def transient(self) -> bool:
        return self.kind in ("timeout", "rate_limited", "server_error", "network")


class LLMProvider(Protocol):
    name: str
    model: str

    def complete_json(self, *, system: str, user: str, json_schema: dict, max_tokens: int, temperature: float,
                      timeout_s: float, workflow: str) -> ProviderResult: ...


def _sanitize(text: str, secret: str) -> str:
    if secret:
        text = text.replace(secret, "[REDACTED]")
    return text[:300]


class NvidiaProvider:
    name = "nvidia"

    def __init__(self, api_key: str, base_url: str, model: str, enable_thinking: bool = False,
                 client: httpx.Client | None = None, structured_output: str = "json_object"):
        self._api_key = api_key  # never logged, never serialised
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.enable_thinking = enable_thinking
        self._client = client or httpx.Client(timeout=None)
        # "json_object" (default): JSON mode + the expected shape in the prompt, validated by Pydantic on our side.
        # In testing, NVIDIA's schema-constrained decoding ("json_schema") intermittently returned HTTP 500 and could
        # silently omit resume sections, so it is opt-in via NVIDIA_STRUCTURED_OUTPUT=json_schema.
        self.structured_output = structured_output
        self._supports_schema = structured_output == "json_schema"
        self._supports_json_mode = structured_output in ("json_object", "json_schema")
        self._supports_thinking_toggle = True

    def __repr__(self) -> str:
        return f"NvidiaProvider(model={self.model!r})"

    def _body(self, system: str, user: str, json_schema: dict, max_tokens: int, temperature: float) -> dict:
        body: dict = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": max_tokens + (1500 if self.enable_thinking else 0),
            "temperature": temperature,
            "stream": False,
        }
        if self._supports_schema:
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "output", "schema": json_schema}}
        elif self._supports_json_mode:
            body["response_format"] = {"type": "json_object"}
        if self._supports_thinking_toggle:
            body["chat_template_kwargs"] = {"enable_thinking": self.enable_thinking}
        return body

    def complete_json(self, *, system: str, user: str, json_schema: dict, max_tokens: int, temperature: float,
                      timeout_s: float, workflow: str) -> ProviderResult:
        for _ in range(3):  # at most two capability downgrades
            body = self._body(system, user, json_schema, max_tokens, temperature)
            try:
                resp = self._client.post(f"{self.base_url}/chat/completions", json=body, timeout=timeout_s,
                                         headers={"Authorization": f"Bearer {self._api_key}",
                                                  "Accept": "application/json"})
            except httpx.TimeoutException as exc:
                raise ProviderError("timeout", None, "request timed out") from exc
            except httpx.HTTPError as exc:
                raise ProviderError("network", None, type(exc).__name__) from exc

            if resp.status_code == 200:
                data = resp.json()
                choice = (data.get("choices") or [{}])[0]
                message = choice.get("message") or {}
                usage = data.get("usage") or {}
                return ProviderResult(content=message.get("content") or "", model=data.get("model") or self.model,
                                      input_tokens=usage.get("prompt_tokens"),
                                      output_tokens=usage.get("completion_tokens"),
                                      finish_reason=choice.get("finish_reason"))

            text = _sanitize(resp.text, self._api_key)
            lowered = text.lower()
            if resp.status_code in (400, 422):
                if self._supports_schema and ("response_format" in lowered or "json_schema" in lowered):
                    self._supports_schema = False
                    continue
                if self._supports_json_mode and ("response_format" in lowered or "json_object" in lowered):
                    self._supports_json_mode = False
                    continue
                if self._supports_thinking_toggle and ("chat_template_kwargs" in lowered
                                                       or "enable_thinking" in lowered):
                    self._supports_thinking_toggle = False
                    continue
                raise ProviderError("bad_request", resp.status_code, text)
            if resp.status_code in (401, 403):
                raise ProviderError("auth", resp.status_code, "the API key was rejected")
            if resp.status_code == 404:
                raise ProviderError("model_unavailable", 404, "model or endpoint not found")
            if resp.status_code == 429:
                retry_after = None
                try:
                    retry_after = float(resp.headers.get("retry-after", ""))
                except ValueError:
                    pass
                raise ProviderError("rate_limited", 429, "rate limited by provider", retry_after)
            if resp.status_code >= 500:
                raise ProviderError("server_error", resp.status_code, text)
            raise ProviderError("bad_request", resp.status_code, text)
        raise ProviderError("bad_request", None, "model rejected the request format")


@dataclass
class FakeProvider:
    """Deterministic, scripted provider for tests. Each workflow maps to a handler that receives
    (system, user) and returns either a JSON-able object, a raw string, or raises ProviderError."""

    handlers: dict[str, Callable[[str, str], object]] = field(default_factory=dict)
    name: str = "fake"
    model: str = "fake-model"
    calls: list[dict] = field(default_factory=list)

    def complete_json(self, *, system: str, user: str, json_schema: dict, max_tokens: int, temperature: float,
                      timeout_s: float, workflow: str) -> ProviderResult:
        self.calls.append({"workflow": workflow, "system": system, "user": user})
        handler = self.handlers.get(workflow)
        if handler is None:
            raise ProviderError("server_error", 500, f"no fake handler for {workflow}")
        out = handler(system, user)
        if isinstance(out, ProviderError):
            raise out
        content = out if isinstance(out, str) else json.dumps(out)
        time.sleep(0)
        return ProviderResult(content=content, model=self.model, input_tokens=len(user) // 4,
                              output_tokens=len(content) // 4, finish_reason="stop")
