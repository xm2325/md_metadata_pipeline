from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import httpx
from pydantic import BaseModel, ConfigDict, Field


class StructuredBackendError(RuntimeError):
    """Base error for structured LLM requests."""


class StructuredBackendHTTPError(StructuredBackendError):
    """Raised when the inference server returns a non-success response."""


class StructuredBackendProtocolError(StructuredBackendError):
    """Raised when a successful response does not match the API contract."""


class CompletionAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: str = "openai_compatible_chat_completions"
    model_id: str
    endpoint: str
    started_at: datetime
    latency_ms: float = Field(ge=0)
    attempt_count: int = Field(ge=1)
    completion_id: str | None = None
    request_id: str | None = None
    finish_reason: str | None = None
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _object_without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise StructuredBackendProtocolError(f"model JSON contains duplicate key: {key}")
        result[key] = value
    return result


def _boolean(name: str, value: str) -> bool:
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


@dataclass(frozen=True)
class OpenAICompatibleSettings:
    base_url: str = "http://127.0.0.1:8000/v1"
    model_id: str = "Qwen/Qwen3.6-27B"
    api_key: str | None = None
    timeout_seconds: float = 180.0
    max_output_tokens: int = 4096
    max_retries: int = 2
    retry_backoff_seconds: float = 1.0
    disable_thinking: bool = True
    seed: int | None = 0

    @classmethod
    def from_env(cls) -> "OpenAICompatibleSettings":
        api_key = os.getenv("MDMETA_LLM_API_KEY")
        timeout = float(os.getenv("MDMETA_LLM_TIMEOUT_SECONDS", "180"))
        max_tokens = int(os.getenv("MDMETA_LLM_MAX_OUTPUT_TOKENS", "4096"))
        retries = int(os.getenv("MDMETA_LLM_MAX_RETRIES", "2"))
        backoff = float(os.getenv("MDMETA_LLM_RETRY_BACKOFF_SECONDS", "1"))
        if timeout <= 0:
            raise ValueError("MDMETA_LLM_TIMEOUT_SECONDS must be positive")
        if max_tokens < 1:
            raise ValueError("MDMETA_LLM_MAX_OUTPUT_TOKENS must be positive")
        if retries < 0:
            raise ValueError("MDMETA_LLM_MAX_RETRIES must be non-negative")
        if backoff < 0:
            raise ValueError("MDMETA_LLM_RETRY_BACKOFF_SECONDS must be non-negative")
        seed_value = os.getenv("MDMETA_LLM_SEED", "0").strip()
        seed = None if seed_value.casefold() == "none" else int(seed_value)
        return cls(
            base_url=os.getenv("MDMETA_LLM_BASE_URL", cls.base_url).rstrip("/"),
            model_id=os.getenv("MDMETA_LLM_MODEL", cls.model_id).strip(),
            api_key=api_key if api_key else None,
            timeout_seconds=timeout,
            max_output_tokens=max_tokens,
            max_retries=retries,
            retry_backoff_seconds=backoff,
            disable_thinking=_boolean(
                "MDMETA_LLM_DISABLE_THINKING",
                os.getenv("MDMETA_LLM_DISABLE_THINKING", "true"),
            ),
            seed=seed,
        )


class OpenAICompatibleStructuredBackend:
    """JSON-Schema backend for vLLM, SGLang, Transformers Serve, or compatible APIs."""

    def __init__(
        self,
        settings: OpenAICompatibleSettings,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not settings.base_url:
            raise ValueError("base_url must not be empty")
        if not settings.model_id:
            raise ValueError("model_id must not be empty")
        self.settings = settings
        self.model_id = settings.model_id
        self.endpoint = f"{settings.base_url.rstrip('/')}/chat/completions"
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=settings.timeout_seconds)
        self._sleep = sleep
        self.last_audit: CompletionAudit | None = None

    @classmethod
    def from_env(cls) -> "OpenAICompatibleStructuredBackend":
        return cls(OpenAICompatibleSettings.from_env())

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "OpenAICompatibleStructuredBackend":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.settings.api_key is not None:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"
        return headers

    def _request_payload(self, prompt: str, json_schema: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model_id,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You extract molecular-dynamics protocol metadata. Return only data that "
                        "is explicitly supported by the supplied text and conforms to the JSON Schema."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "top_p": 1,
            "max_tokens": self.settings.max_output_tokens,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "md_protocol_events",
                    "strict": True,
                    "schema": json_schema,
                },
            },
        }
        if self.settings.seed is not None:
            payload["seed"] = self.settings.seed
        if self.settings.disable_thinking:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        return payload

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        value = response.headers.get("Retry-After")
        if value is None:
            return None
        try:
            return min(max(float(value), 0.0), 30.0)
        except ValueError:
            return None

    def complete(self, prompt: str, json_schema: dict[str, Any]) -> dict[str, Any]:
        request_payload = self._request_payload(prompt, json_schema)
        started_at = datetime.now(timezone.utc)
        started = time.monotonic()
        response: httpx.Response | None = None
        retryable_statuses = {429, 500, 502, 503, 504}
        attempt_count = 0

        for attempt in range(self.settings.max_retries + 1):
            attempt_count = attempt + 1
            try:
                response = self._client.post(
                    self.endpoint,
                    headers=self._headers(),
                    json=request_payload,
                    timeout=self.settings.timeout_seconds,
                )
            except httpx.TransportError as exc:
                if attempt >= self.settings.max_retries:
                    raise StructuredBackendHTTPError(
                        f"LLM transport failed after {attempt_count} attempt(s): {type(exc).__name__}"
                    ) from exc
                self._sleep(self.settings.retry_backoff_seconds * (2**attempt))
                continue

            if response.status_code < 400:
                break
            if response.status_code not in retryable_statuses or attempt >= self.settings.max_retries:
                raise StructuredBackendHTTPError(
                    f"LLM server returned HTTP {response.status_code} after {attempt_count} attempt(s)"
                )
            delay = self._retry_after(response)
            if delay is None:
                delay = self.settings.retry_backoff_seconds * (2**attempt)
            self._sleep(delay)

        if response is None:
            raise StructuredBackendHTTPError("LLM request did not produce a response")

        try:
            envelope = response.json()
        except ValueError as exc:
            raise StructuredBackendProtocolError("LLM server returned invalid JSON") from exc
        if not isinstance(envelope, dict):
            raise StructuredBackendProtocolError("LLM response envelope must be an object")
        choices = envelope.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise StructuredBackendProtocolError("LLM response must contain exactly one choice")
        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, dict):
            raise StructuredBackendProtocolError("LLM response choice is missing a message object")
        refusal = message.get("refusal")
        if refusal:
            raise StructuredBackendProtocolError("LLM refused the structured extraction request")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise StructuredBackendProtocolError("LLM response message has no JSON content")
        try:
            parsed = json.loads(content, object_pairs_hook=_object_without_duplicate_keys)
        except json.JSONDecodeError as exc:
            raise StructuredBackendProtocolError("LLM message content is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise StructuredBackendProtocolError("LLM structured output must be a JSON object")

        usage = envelope.get("usage") if isinstance(envelope.get("usage"), dict) else {}
        response_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        self.last_audit = CompletionAudit(
            model_id=str(envelope.get("model") or self.model_id),
            endpoint=self.endpoint,
            started_at=started_at,
            latency_ms=(time.monotonic() - started) * 1000,
            attempt_count=attempt_count,
            completion_id=str(envelope["id"]) if envelope.get("id") is not None else None,
            request_id=response.headers.get("x-request-id"),
            finish_reason=str(choice["finish_reason"])
            if choice.get("finish_reason") is not None
            else None,
            prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            schema_sha256=hashlib.sha256(_canonical_json(json_schema)).hexdigest(),
            response_sha256=response_hash,
            input_tokens=int(usage["prompt_tokens"])
            if usage.get("prompt_tokens") is not None
            else None,
            output_tokens=int(usage["completion_tokens"])
            if usage.get("completion_tokens") is not None
            else None,
            total_tokens=int(usage["total_tokens"])
            if usage.get("total_tokens") is not None
            else None,
        )
        return parsed
