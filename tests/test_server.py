from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import Response
from fastapi.testclient import TestClient

from mdmeta.api import _public_record, create_app
from mdmeta.observability import JSONLogFormatter
from mdmeta.server import ServerSettings, create_server_app, main
from mdmeta.storage import SQLiteRecordStore
from mdmeta.verify import verify_database


def test_server_settings_and_factory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    database = tmp_path / "server" / "records.sqlite"
    monkeypatch.setenv("MDMETA_DATABASE_PATH", str(database))
    monkeypatch.setenv("MDMETA_DATABASE_READ_ONLY", "false")
    monkeypatch.setenv("MDMETA_HOST", "0.0.0.0")
    monkeypatch.setenv("MDMETA_PORT", "8080")
    monkeypatch.setenv("MDMETA_WORKERS", "2")
    monkeypatch.setenv("MDMETA_LOG_LEVEL", "warning")
    monkeypatch.setenv("MDMETA_DATASET_SHA256", "a" * 64)
    monkeypatch.setenv("MDMETA_BUILD_SHA", "b" * 40)

    settings = ServerSettings.from_env()
    assert settings.database_path == database
    assert settings.database_read_only is False
    assert settings.host == "0.0.0.0"
    assert settings.port == 8080
    assert settings.workers == 2
    assert settings.log_level == "warning"
    assert settings.dataset_sha256 == "a" * 64
    assert settings.build_sha == "b" * 40
    assert settings.environment == "development"
    assert settings.allowed_hosts == ("*",)
    assert settings.limit_concurrency == 100
    assert settings.timeout_graceful_shutdown == 25
    assert settings.docs_enabled is True

    client = TestClient(create_server_app())
    assert client.get("/readyz").json()["status"] == "ready"
    assert client.get("/metadata").json()["article_count"] == 0


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("MDMETA_PORT", "0", "MDMETA_PORT must be positive"),
        ("MDMETA_PORT", "65536", "MDMETA_PORT must be at most 65535"),
        ("MDMETA_WORKERS", "many", "MDMETA_WORKERS must be an integer"),
        (
            "MDMETA_LIMIT_CONCURRENCY",
            "0",
            "MDMETA_LIMIT_CONCURRENCY must be positive",
        ),
        ("MDMETA_ENV", "staging", "MDMETA_ENV must be development or production"),
        ("MDMETA_LOG_LEVEL", "verbose", "MDMETA_LOG_LEVEL must be one of"),
        (
            "MDMETA_DATABASE_READ_ONLY",
            "sometimes",
            "MDMETA_DATABASE_READ_ONLY must be true or false",
        ),
        (
            "MDMETA_DATASET_SHA256",
            "not-a-digest",
            "MDMETA_DATASET_SHA256 must be unversioned or a hexadecimal digest",
        ),
        (
            "MDMETA_BUILD_SHA",
            "short",
            "MDMETA_BUILD_SHA must be unknown or a hexadecimal digest",
        ),
    ],
)
def test_server_settings_reject_invalid_environment(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
    message: str,
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=message):
        ServerSettings.from_env()


def test_read_only_server_verifies_declared_database_digest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "records.sqlite"
    store = SQLiteRecordStore(database)
    store.checkpoint()
    digest = verify_database(database)["sha256"]
    monkeypatch.setenv("MDMETA_DATABASE_PATH", str(database))
    monkeypatch.setenv("MDMETA_DATABASE_READ_ONLY", "true")
    monkeypatch.setenv("MDMETA_DATASET_SHA256", str(digest))

    assert TestClient(create_server_app()).get("/readyz").status_code == 200

    monkeypatch.setenv("MDMETA_DATASET_SHA256", "0" * 64)
    with pytest.raises(RuntimeError, match="does not match"):
        create_server_app()


def _production_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MDMETA_ENV", "production")
    monkeypatch.setenv("MDMETA_DATABASE_READ_ONLY", "true")
    monkeypatch.setenv("MDMETA_DATASET_SHA256", "a" * 64)
    monkeypatch.setenv("MDMETA_BUILD_SHA", "b" * 40)
    monkeypatch.setenv("MDMETA_WORKERS", "1")
    monkeypatch.setenv("MDMETA_ALLOWED_HOSTS", "api.example.org")
    monkeypatch.setenv("MDMETA_FORWARDED_ALLOW_IPS", "127.0.0.1")
    monkeypatch.setenv("MDMETA_ENABLE_DOCS", "false")


def test_production_settings_are_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _production_environment(monkeypatch)

    settings = ServerSettings.from_env()

    assert settings.environment == "production"
    assert settings.database_read_only is True
    assert settings.allowed_hosts == ("api.example.org",)
    assert settings.forwarded_allow_ips == "127.0.0.1"
    assert settings.workers == 1
    assert settings.docs_enabled is False


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        (
            "MDMETA_DATABASE_READ_ONLY",
            "false",
            "production requires MDMETA_DATABASE_READ_ONLY=true",
        ),
        (
            "MDMETA_DATASET_SHA256",
            "unversioned",
            "production requires MDMETA_DATASET_SHA256",
        ),
        ("MDMETA_BUILD_SHA", "unknown", "production requires MDMETA_BUILD_SHA"),
        (
            "MDMETA_BUILD_SHA",
            "abcdef0",
            "production requires a full 40- or 64-character MDMETA_BUILD_SHA",
        ),
        ("MDMETA_WORKERS", "2", "production requires one worker per container"),
        (
            "MDMETA_ALLOWED_HOSTS",
            "*",
            "production requires explicit MDMETA_ALLOWED_HOSTS",
        ),
        (
            "MDMETA_ALLOWED_HOSTS",
            "*.",
            "host wildcards are supported only as",
        ),
        (
            "MDMETA_ALLOWED_HOSTS",
            "https://api.example.org",
            "allowed host patterns must contain hostnames only",
        ),
        (
            "MDMETA_ALLOWED_HOSTS",
            "api.example.org:443",
            "allowed host patterns must not include a scheme or port",
        ),
        (
            "MDMETA_ALLOWED_HOSTS",
            "attacker@api.example.org",
            "allowed host patterns must contain hostnames only",
        ),
        (
            "MDMETA_ALLOWED_HOSTS",
            "api.example.org,API.EXAMPLE.ORG",
            "allowed_hosts must not contain duplicate patterns",
        ),
        (
            "MDMETA_ALLOWED_HOSTS",
            "api.example.org,*",
            "the unrestricted Host wildcard must be the only pattern",
        ),
        (
            "MDMETA_FORWARDED_ALLOW_IPS",
            "127.0.0.1,*",
            "production forbids trusting forwarded headers from every address",
        ),
        (
            "MDMETA_ENABLE_DOCS",
            "true",
            "production requires MDMETA_ENABLE_DOCS=false",
        ),
    ],
)
def test_production_settings_reject_unsafe_values(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
    message: str,
) -> None:
    _production_environment(monkeypatch)
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=message):
        ServerSettings.from_env()


@pytest.mark.parametrize("length", [40, 64])
def test_production_settings_accept_full_build_sha(
    monkeypatch: pytest.MonkeyPatch,
    length: int,
) -> None:
    _production_environment(monkeypatch)
    monkeypatch.setenv("MDMETA_BUILD_SHA", "c" * length)

    assert ServerSettings.from_env().build_sha == "c" * length


def test_production_settings_accept_normalized_hosts_and_ipv6(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _production_environment(monkeypatch)
    monkeypatch.setenv(
        "MDMETA_ALLOWED_HOSTS",
        "API.EXAMPLE.ORG, *.internal.example.org, ::1",
    )

    assert ServerSettings.from_env().allowed_hosts == (
        "api.example.org",
        "*.internal.example.org",
        "::1",
    )


@pytest.mark.parametrize(
    ("dataset_sha", "build_sha", "message"),
    [
        (
            "not-a-digest",
            "b" * 40,
            "production requires a versioned dataset SHA-256",
        ),
        (
            "a" * 64,
            "abcdef0",
            "production requires a full 40- or 64-character build SHA",
        ),
    ],
)
def test_direct_production_app_rejects_incomplete_provenance(
    tmp_path: Path,
    dataset_sha: str,
    build_sha: str,
    message: str,
) -> None:
    with pytest.raises(
        ValueError,
        match=message,
    ):
        create_app(
            tmp_path / "missing.sqlite",
            read_only=True,
            dataset_sha256=dataset_sha,
            build_sha=build_sha,
            environment="production",
            allowed_hosts=("api.example.org",),
            docs_enabled=False,
        )


def test_api_contract_request_correlation_security_and_metrics(tmp_path: Path) -> None:
    database = tmp_path / "records.sqlite"
    SQLiteRecordStore(database)
    client = TestClient(create_app(database))

    missing = client.get(
        "/records/MISSING",
        headers={"X-Request-ID": "caller-request-123"},
    )
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("application/problem+json")
    assert missing.headers["x-request-id"] == "caller-request-123"
    assert missing.headers["x-content-type-options"] == "nosniff"
    assert missing.headers["x-frame-options"] == "DENY"
    assert missing.headers["referrer-policy"] == "no-referrer"
    assert missing.headers["permissions-policy"] == (
        "accelerometer=(), camera=(), geolocation=(), microphone=()"
    )
    assert "frame-ancestors 'none'" in missing.headers["content-security-policy"]
    assert missing.json() == {
        "type": "urn:mdmeta:error:record-not-found",
        "title": "Not Found",
        "status": 404,
        "detail": "record not found",
        "instance": "/records/MISSING",
        "code": "record-not-found",
        "request_id": "caller-request-123",
    }

    invalid = client.get("/search", params={"pdb_id": "BAD", "limit": 0})
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "request-validation-error"
    assert {tuple(issue["location"]) for issue in invalid.json()["errors"]} == {
        ("query", "pdb_id"),
        ("query", "limit"),
    }

    no_filter = client.get("/search", headers={"X-Request-ID": "not valid"})
    assert no_filter.status_code == 400
    assert no_filter.json()["code"] == "missing-search-filter"
    assert no_filter.headers["x-request-id"] != "not valid"
    assert len(no_filter.headers["x-request-id"]) == 32

    assert client.request("CUSTOM-METHOD-123", "/livez").status_code == 405
    metrics = client.get("/metrics").text
    assert "mdmeta_build_info" in metrics
    assert "mdmeta_dataset_articles 0.0" in metrics
    assert 'route="/records/{document_id}"' in metrics
    assert 'status="404"' in metrics
    assert 'method="OTHER"' in metrics
    assert "CUSTOM-METHOD-123" not in metrics
    assert "MISSING" not in metrics


def test_openapi_uses_public_response_and_problem_models(tmp_path: Path) -> None:
    database = tmp_path / "records.sqlite"
    SQLiteRecordStore(database)

    document = TestClient(create_app(database)).get("/openapi.json").json()

    record_operation = document["paths"]["/records/{document_id}"]["get"]
    record_schema = record_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ]
    assert record_schema["$ref"].endswith("/PublicIntegratedMDRecord")
    problem_schema = record_operation["responses"]["404"]["content"][
        "application/problem+json"
    ]["schema"]
    assert problem_schema["$ref"].endswith("/ProblemDetail")
    search_schema = document["paths"]["/search"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert search_schema["$ref"].endswith("/SearchResponse")
    assert "ProblemDetail" in document["components"]["schemas"]


def test_unhandled_errors_are_correlated_without_detail_leak(tmp_path: Path) -> None:
    database = tmp_path / "records.sqlite"
    SQLiteRecordStore(database)
    app = create_app(database)

    @app.get("/explode")
    def explode() -> None:
        raise RuntimeError("private database detail")

    response = TestClient(app, raise_server_exceptions=False).get(
        "/explode",
        headers={"X-Request-ID": "failure-123"},
    )

    assert response.status_code == 500
    assert response.headers["x-request-id"] == "failure-123"
    assert response.json()["code"] == "internal-server-error"
    assert response.json()["detail"] == "an unexpected server error occurred"
    assert "private database detail" not in response.text


@pytest.mark.parametrize(
    "malicious_host",
    [
        "attacker.example",
        "attacker@api.example.org",
        "api.example.org@attacker.example",
        "api.example.org:invalid-port",
        "api.example.org:65536",
        "api.example.org:",
    ],
)
def test_trusted_hosts_reject_unexpected_host_with_security_headers(
    tmp_path: Path,
    malicious_host: str,
) -> None:
    database = tmp_path / "records.sqlite"
    SQLiteRecordStore(database)
    client = TestClient(create_app(database, allowed_hosts=("api.example.org",)))

    accepted = client.get("/livez", headers={"Host": "api.example.org"})
    accepted_with_port = client.get("/livez", headers={"Host": "api.example.org:8443"})
    rejected = client.get("/livez", headers={"Host": malicious_host})

    assert accepted.status_code == 200
    assert accepted_with_port.status_code == 200
    assert rejected.status_code == 400
    assert rejected.headers["content-type"].startswith("application/problem+json")
    assert rejected.json()["code"] == "invalid-host"
    assert rejected.headers["x-request-id"]
    assert rejected.headers["x-content-type-options"] == "nosniff"
    assert rejected.headers["permissions-policy"] == (
        "accelerometer=(), camera=(), geolocation=(), microphone=()"
    )


def test_unrestricted_development_hosts_still_reject_malformed_userinfo(
    tmp_path: Path,
) -> None:
    database = tmp_path / "records.sqlite"
    SQLiteRecordStore(database)

    response = TestClient(create_app(database)).get(
        "/livez",
        headers={"Host": "attacker@api.example.org"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid-host"


def test_security_middleware_overrides_weaker_route_headers(tmp_path: Path) -> None:
    database = tmp_path / "records.sqlite"
    SQLiteRecordStore(database)
    app = create_app(database)

    @app.get("/weak-headers")
    def weak_headers() -> Response:
        return Response(
            headers={
                "Content-Security-Policy": "default-src *",
                "Permissions-Policy": "camera=(*)",
                "X-Content-Type-Options": "off",
                "X-Frame-Options": "SAMEORIGIN",
                "Referrer-Policy": "unsafe-url",
            }
        )

    response = TestClient(app).get("/weak-headers")

    assert response.headers["content-security-policy"] == (
        "frame-ancestors 'none'; base-uri 'none'"
    )
    assert response.headers["permissions-policy"] == (
        "accelerometer=(), camera=(), geolocation=(), microphone=()"
    )
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_public_record_redacts_case_insensitive_file_uris_without_mutation() -> None:
    source = {
        "article": {"source_uri": "FILE:///srv/private/article.xml"},
        "provenance": {
            "assets": [
                {
                    "local_path": "/srv/private/input.pdb",
                    "source_uri": "FiLe:///srv/private/input.pdb",
                }
            ],
            "workflow_steps": [
                {
                    "inputs": ["FILE:///srv/private/input.pdb"],
                    "outputs": ["C:\\private\\output.pdb"],
                }
            ],
        },
    }

    public = _public_record(source)

    assert public["article"]["source_uri"] is None
    assert public["provenance"]["assets"][0]["local_path"] is None
    assert public["provenance"]["assets"][0]["source_uri"] is None
    assert public["provenance"]["workflow_steps"][0]["inputs"] == [
        "<redacted-local-path>"
    ]
    assert public["provenance"]["workflow_steps"][0]["outputs"] == [
        "<redacted-local-path>"
    ]
    assert source["article"]["source_uri"].startswith("FILE:")


def test_json_log_formatter_emits_machine_readable_access_fields() -> None:
    formatter = JSONLogFormatter()
    record = logging.LogRecord(
        name="mdmeta.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="http_request_complete",
        args=(),
        exc_info=None,
    )
    record.event = "http_request_complete"
    record.request_id = "request-123"
    record.method = "GET"
    record.route = "/records/{document_id}"
    record.status = 200
    record.duration_ms = 1.25

    payload = json.loads(formatter.format(record))

    assert payload["message"] == "http_request_complete"
    assert payload["request_id"] == "request-123"
    assert payload["route"] == "/records/{document_id}"
    assert payload["status"] == 200


def test_server_entrypoint_passes_resource_and_proxy_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def run(target: str, **kwargs: object) -> None:
        captured["target"] = target
        captured.update(kwargs)

    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=run))
    monkeypatch.setenv("MDMETA_PROXY_HEADERS", "false")
    monkeypatch.setenv("MDMETA_FORWARDED_ALLOW_IPS", "10.0.0.1,10.0.0.2")
    monkeypatch.setenv("MDMETA_LIMIT_CONCURRENCY", "75")
    monkeypatch.setenv("MDMETA_BACKLOG", "96")
    monkeypatch.setenv("MDMETA_TIMEOUT_KEEP_ALIVE", "4")
    monkeypatch.setenv("MDMETA_TIMEOUT_GRACEFUL_SHUTDOWN", "20")

    main()

    assert captured["target"] == "mdmeta.server:create_server_app"
    assert captured["proxy_headers"] is False
    assert captured["forwarded_allow_ips"] == "10.0.0.1,10.0.0.2"
    assert captured["limit_concurrency"] == 75
    assert captured["backlog"] == 96
    assert captured["timeout_keep_alive"] == 4
    assert captured["timeout_graceful_shutdown"] == 20
    assert captured["server_header"] is False
    assert captured["access_log"] is False
