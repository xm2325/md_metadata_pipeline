from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI

from .api import create_app
from .observability import configure_json_logging, validate_allowed_hosts
from .verify import verify_database


_LOG_LEVELS = {"critical", "error", "warning", "info", "debug", "trace"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{7,64}$")
_FULL_GIT_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def _positive_int(name: str, value: str) -> int:
    try:
        parsed = int(value.strip())
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed < 1:
        raise ValueError(f"{name} must be positive")
    return parsed


def _boolean(name: str, value: str) -> bool:
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def _provenance_value(
    name: str,
    value: str,
    *,
    placeholder: str,
    pattern: re.Pattern[str],
) -> str:
    normalized = value.strip().casefold()
    if normalized == placeholder or pattern.fullmatch(normalized):
        return normalized
    raise ValueError(f"{name} must be {placeholder} or a hexadecimal digest")


def _port(value: str) -> int:
    parsed = _positive_int("MDMETA_PORT", value)
    if parsed > 65535:
        raise ValueError("MDMETA_PORT must be at most 65535")
    return parsed


def _environment(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized not in {"development", "production"}:
        raise ValueError("MDMETA_ENV must be development or production")
    return normalized


def _comma_separated(name: str, value: str) -> tuple[str, ...]:
    entries = tuple(item.strip() for item in value.split(",") if item.strip())
    if not entries:
        raise ValueError(f"{name} must contain at least one value")
    return entries


@dataclass(frozen=True)
class ServerSettings:
    database_path: Path
    environment: str = "development"
    database_read_only: bool = True
    host: str = "127.0.0.1"
    port: int = 8000
    workers: int = 1
    log_level: str = "info"
    dataset_sha256: str = "unversioned"
    build_sha: str = "unknown"
    allowed_hosts: tuple[str, ...] = ("*",)
    proxy_headers: bool = True
    forwarded_allow_ips: str = "127.0.0.1"
    limit_concurrency: int = 100
    backlog: int = 128
    timeout_keep_alive: int = 5
    timeout_graceful_shutdown: int = 25
    docs_enabled: bool = True

    def _validate_production(self) -> None:
        if self.environment != "production":
            return
        if not self.database_read_only:
            raise ValueError("production requires MDMETA_DATABASE_READ_ONLY=true")
        if self.dataset_sha256 == "unversioned":
            raise ValueError("production requires MDMETA_DATASET_SHA256")
        if self.build_sha == "unknown":
            raise ValueError("production requires MDMETA_BUILD_SHA")
        if not _FULL_GIT_SHA.fullmatch(self.build_sha):
            raise ValueError(
                "production requires a full 40- or 64-character MDMETA_BUILD_SHA"
            )
        if self.workers != 1:
            raise ValueError("production requires one worker per container")
        if "*" in self.allowed_hosts:
            raise ValueError("production requires explicit MDMETA_ALLOWED_HOSTS")
        if "*" in self.forwarded_allow_ips.split(","):
            raise ValueError("production forbids trusting forwarded headers from every address")
        if self.docs_enabled:
            raise ValueError("production requires MDMETA_ENABLE_DOCS=false")

    @classmethod
    def from_env(cls) -> "ServerSettings":
        environment = _environment(os.getenv("MDMETA_ENV", "development"))
        log_level = os.getenv("MDMETA_LOG_LEVEL", "info").strip().casefold()
        if log_level not in _LOG_LEVELS:
            raise ValueError(
                "MDMETA_LOG_LEVEL must be one of " + ", ".join(sorted(_LOG_LEVELS))
            )
        host = os.getenv("MDMETA_HOST", "127.0.0.1").strip()
        if not host:
            raise ValueError("MDMETA_HOST must not be empty")
        allowed_hosts = validate_allowed_hosts(
            _comma_separated(
                "MDMETA_ALLOWED_HOSTS",
                os.getenv("MDMETA_ALLOWED_HOSTS", "*"),
            )
        )
        forwarded_allow_ips = ",".join(
            _comma_separated(
                "MDMETA_FORWARDED_ALLOW_IPS",
                os.getenv("MDMETA_FORWARDED_ALLOW_IPS", "127.0.0.1"),
            )
        )
        settings = cls(
            database_path=Path(
                os.getenv("MDMETA_DATABASE_PATH", "data/records.sqlite")
            ).expanduser(),
            environment=environment,
            database_read_only=_boolean(
                "MDMETA_DATABASE_READ_ONLY",
                os.getenv("MDMETA_DATABASE_READ_ONLY", "true"),
            ),
            host=host,
            port=_port(os.getenv("MDMETA_PORT", "8000")),
            workers=_positive_int("MDMETA_WORKERS", os.getenv("MDMETA_WORKERS", "1")),
            log_level=log_level,
            dataset_sha256=_provenance_value(
                "MDMETA_DATASET_SHA256",
                os.getenv("MDMETA_DATASET_SHA256", "unversioned"),
                placeholder="unversioned",
                pattern=_SHA256,
            ),
            build_sha=_provenance_value(
                "MDMETA_BUILD_SHA",
                os.getenv("MDMETA_BUILD_SHA", "unknown"),
                placeholder="unknown",
                pattern=_GIT_SHA,
            ),
            allowed_hosts=allowed_hosts,
            proxy_headers=_boolean(
                "MDMETA_PROXY_HEADERS",
                os.getenv("MDMETA_PROXY_HEADERS", "true"),
            ),
            forwarded_allow_ips=forwarded_allow_ips,
            limit_concurrency=_positive_int(
                "MDMETA_LIMIT_CONCURRENCY",
                os.getenv("MDMETA_LIMIT_CONCURRENCY", "100"),
            ),
            backlog=_positive_int(
                "MDMETA_BACKLOG",
                os.getenv("MDMETA_BACKLOG", "128"),
            ),
            timeout_keep_alive=_positive_int(
                "MDMETA_TIMEOUT_KEEP_ALIVE",
                os.getenv("MDMETA_TIMEOUT_KEEP_ALIVE", "5"),
            ),
            timeout_graceful_shutdown=_positive_int(
                "MDMETA_TIMEOUT_GRACEFUL_SHUTDOWN",
                os.getenv("MDMETA_TIMEOUT_GRACEFUL_SHUTDOWN", "25"),
            ),
            docs_enabled=_boolean(
                "MDMETA_ENABLE_DOCS",
                os.getenv(
                    "MDMETA_ENABLE_DOCS",
                    "false" if environment == "production" else "true",
                ),
            ),
        )
        settings._validate_production()
        return settings


def create_server_app() -> FastAPI:
    """Uvicorn factory configured exclusively through environment variables."""

    settings = ServerSettings.from_env()
    configure_json_logging(settings.log_level)
    if settings.database_read_only and settings.dataset_sha256 != "unversioned":
        verification = verify_database(settings.database_path)
        if not verification["valid"]:
            raise RuntimeError("database snapshot failed integrity verification")
        if verification["sha256"] != settings.dataset_sha256:
            raise RuntimeError(
                "MDMETA_DATASET_SHA256 does not match the mounted database snapshot"
            )
    return create_app(
        settings.database_path,
        read_only=settings.database_read_only,
        dataset_sha256=settings.dataset_sha256,
        build_sha=settings.build_sha,
        environment=settings.environment,
        allowed_hosts=settings.allowed_hosts,
        docs_enabled=settings.docs_enabled,
    )


def main() -> None:
    """Run the query API; ingestion remains an offline, single-writer workflow."""

    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - exercised by packaging smoke tests
        raise SystemExit("install the 'api' extra to run mdmeta-serve") from exc

    settings = ServerSettings.from_env()
    configure_json_logging(settings.log_level)
    uvicorn.run(
        "mdmeta.server:create_server_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        workers=settings.workers,
        log_level=settings.log_level,
        proxy_headers=settings.proxy_headers,
        forwarded_allow_ips=settings.forwarded_allow_ips,
        limit_concurrency=settings.limit_concurrency,
        backlog=settings.backlog,
        timeout_keep_alive=settings.timeout_keep_alive,
        timeout_graceful_shutdown=settings.timeout_graceful_shutdown,
        server_header=False,
        access_log=False,
    )


if __name__ == "__main__":
    main()
