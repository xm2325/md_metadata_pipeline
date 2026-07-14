import json

import httpx
import pytest

from mdmeta.openai_backend import (
    OpenAICompatibleSettings,
    OpenAICompatibleStructuredBackend,
    StructuredBackendHTTPError,
    StructuredBackendProtocolError,
)


def _success(content='{"events":[]}'):
    return {
        "id": "chatcmpl-test",
        "model": "Qwen/Qwen3.6-27B",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
    }


def test_qwen_structured_request_and_audit():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        captured["authorization"] = request.headers.get("Authorization")
        return httpx.Response(
            200,
            json=_success(),
            headers={"x-request-id": "request-123"},
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    backend = OpenAICompatibleStructuredBackend(
        OpenAICompatibleSettings(api_key="secret", max_retries=0),
        client=client,
    )
    result = backend.complete("extract", {"type": "object", "properties": {}})

    assert result == {"events": []}
    assert captured["authorization"] == "Bearer secret"
    payload = captured["payload"]
    assert payload["model"] == "Qwen/Qwen3.6-27B"
    assert payload["temperature"] == 0
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert backend.last_audit is not None
    assert backend.last_audit.request_id == "request-123"
    assert backend.last_audit.input_tokens == 12
    assert backend.last_audit.output_tokens == 4
    assert len(backend.last_audit.prompt_sha256) == 64
    assert len(backend.last_audit.schema_sha256) == 64
    assert "secret" not in backend.last_audit.model_dump_json()
    client.close()


def test_retries_transient_status_then_succeeds():
    attempts = 0
    delays = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, request=request)
        return httpx.Response(200, json=_success(), request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    backend = OpenAICompatibleStructuredBackend(
        OpenAICompatibleSettings(max_retries=1),
        client=client,
        sleep=delays.append,
    )
    assert backend.complete("extract", {"type": "object"}) == {"events": []}
    assert attempts == 2
    assert delays == [0.0]
    assert backend.last_audit is not None
    assert backend.last_audit.attempt_count == 2
    client.close()


def test_non_retryable_status_fails_without_leaking_body():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda incoming: httpx.Response(
                401,
                text="sensitive upstream response",
                request=incoming,
            )
        )
    )
    backend = OpenAICompatibleStructuredBackend(
        OpenAICompatibleSettings(base_url="http://test/v1", max_retries=0),
        client=client,
    )
    with pytest.raises(StructuredBackendHTTPError, match="HTTP 401") as error:
        backend.complete("extract", {"type": "object"})
    assert "sensitive upstream response" not in str(error.value)
    client.close()


def test_duplicate_keys_in_model_content_are_rejected():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=_success('{"events":[],"events":[]}'),
                request=request,
            )
        )
    )
    backend = OpenAICompatibleStructuredBackend(
        OpenAICompatibleSettings(max_retries=0),
        client=client,
    )
    with pytest.raises(StructuredBackendProtocolError, match="duplicate key"):
        backend.complete("extract", {"type": "object"})
    client.close()


def test_settings_default_to_latest_open_qwen(monkeypatch):
    for name in (
        "MDMETA_LLM_BASE_URL",
        "MDMETA_LLM_MODEL",
        "MDMETA_LLM_API_KEY",
        "MDMETA_LLM_TIMEOUT_SECONDS",
        "MDMETA_LLM_MAX_OUTPUT_TOKENS",
        "MDMETA_LLM_MAX_RETRIES",
        "MDMETA_LLM_RETRY_BACKOFF_SECONDS",
        "MDMETA_LLM_DISABLE_THINKING",
        "MDMETA_LLM_SEED",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = OpenAICompatibleSettings.from_env()
    assert settings.model_id == "Qwen/Qwen3.6-27B"
    assert settings.base_url == "http://127.0.0.1:8000/v1"
    assert settings.disable_thinking is True
