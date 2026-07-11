from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI

from .api import create_app
from .verify import verify_database


_LOG_LEVELS = {"critical", "error", "warning", "info", "debug", "trace"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{7,64}$")


def _positive_int(name: str, value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed < 1:
        raise ValueError(f"{name} must be positive")
    return parsed


def _boolean(name: str, value: str) -> bool:
    normalized = value.casefold()
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
    normalized = value.casefold()
    if normalized == placeholder or pattern.fullmatch(normalized):
        return normalized
    raise ValueError(f"{name} must be {placeholder} or a hexadecimal digest")


@dataclass(frozen=True)
class ServerSettings:
    database_path: Path
    database_read_only: bool = True
    host: str = "127.0.0.1"
    port: int = 8000
    workers: int = 1
    log_level: str = "info"
    dataset_sha256: str = "unversioned"
    build_sha: str = "unknown"

    @classmethod
    def from_env(cls) -> "ServerSettings":
        log_level = os.getenv("MDMETA_LOG_LEVEL", "info").casefold()
        if log_level not in _LOG_LEVELS:
            raise ValueError(
                "MDMETA_LOG_LEVEL must be one of " + ", ".join(sorted(_LOG_LEVELS))
            )
        return cls(
            database_path=Path(
                os.getenv("MDMETA_DATABASE_PATH", "data/records.sqlite")
            ).expanduser(),
            database_read_only=_boolean(
                "MDMETA_DATABASE_READ_ONLY",
                os.getenv("MDMETA_DATABASE_READ_ONLY", "true"),
            ),
            host=os.getenv("MDMETA_HOST", "127.0.0.1"),
            port=_positive_int("MDMETA_PORT", os.getenv("MDMETA_PORT", "8000")),
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
        )


def create_server_app() -> FastAPI:
    """Uvicorn factory configured exclusively through environment variables."""

    settings = ServerSettings.from_env()
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
    )


def main() -> None:
    """Run the query API; ingestion remains an offline, single-writer workflow."""

    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - exercised by packaging smoke tests
        raise SystemExit("install the 'api' extra to run mdmeta-serve") from exc

    settings = ServerSettings.from_env()
    uvicorn.run(
        "mdmeta.server:create_server_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        workers=settings.workers,
        log_level=settings.log_level,
        proxy_headers=True,
    )


if __name__ == "__main__":
    main()
