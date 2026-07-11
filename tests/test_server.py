from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mdmeta.server import ServerSettings, create_server_app
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

    client = TestClient(create_server_app())
    assert client.get("/readyz").json()["status"] == "ready"
    assert client.get("/metadata").json()["article_count"] == 0


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("MDMETA_PORT", "0", "MDMETA_PORT must be positive"),
        ("MDMETA_WORKERS", "many", "MDMETA_WORKERS must be an integer"),
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
