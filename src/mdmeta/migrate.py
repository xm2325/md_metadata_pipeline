from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .storage import MIGRATION_1_TO_2_STATEMENTS, SCHEMA_VERSION, SQLiteRecordStore


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _migration_sha256() -> str:
    encoded = "\n-- statement --\n".join(
        " ".join(statement.split()) for statement in MIGRATION_1_TO_2_STATEMENTS
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def _migration_lock(database: Path) -> Iterator[None]:
    lock_path = database.with_name(f".{database.name}.migration.lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(descriptor)
        raise RuntimeError("database migration lock is already held") from exc
    try:
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _online_v1_backup(source_path: Path, backup_path: Path) -> str:
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    if backup_path.exists() or backup_path.is_symlink():
        raise FileExistsError(backup_path)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{backup_path.name}.", suffix=".tmp", dir=backup_path.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with sqlite3.connect(source_path) as source, sqlite3.connect(temporary) as target:
            source.execute("PRAGMA busy_timeout = 5000")
            source.execute("PRAGMA foreign_keys = ON")
            SQLiteRecordStore._validate_schema(source, expected_version=1)
            source.backup(target)
            journal_mode = str(target.execute("PRAGMA journal_mode = DELETE").fetchone()[0])
            if journal_mode.casefold() != "delete":
                raise RuntimeError("failed to finalize the pre-migration backup")
            SQLiteRecordStore._validate_schema(target, expected_version=1)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, backup_path)
        _fsync_directory(backup_path.parent)
        return _sha256_file(backup_path)
    finally:
        temporary.unlink(missing_ok=True)


def migrate_database_v1_to_v2(
    database: str | Path,
    *,
    backup: str | Path,
) -> dict[str, object]:
    path = Path(database)
    backup_path = Path(backup)
    if path.is_symlink() or not path.is_file():
        raise ValueError("database must be an existing regular file and not a symlink")
    if path.resolve() == backup_path.resolve():
        raise ValueError("backup must not be the source database")

    with _migration_lock(path):
        with sqlite3.connect(path) as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version == SCHEMA_VERSION:
                SQLiteRecordStore._validate_schema(connection)
                return {
                    "status": "already_current",
                    "database": path.name,
                    "schema_version": SCHEMA_VERSION,
                }
            if version != 1:
                raise RuntimeError(
                    f"unsupported migration source version {version}; expected 1"
                )

        source_sha256_before = _sha256_file(path)
        backup_sha256 = _online_v1_backup(path, backup_path)
        migration_sha256 = _migration_sha256()
        applied_at = datetime.now(timezone.utc).isoformat()

        connection = sqlite3.connect(path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("BEGIN EXCLUSIVE")
            SQLiteRecordStore._validate_schema(connection, expected_version=1)
            for statement in MIGRATION_1_TO_2_STATEMENTS:
                connection.execute(statement)
            connection.execute(
                """
                INSERT INTO schema_migrations(
                    migration_id, from_version, to_version, applied_at,
                    migration_sha256, source_sha256_before, backup_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "sqlite-v1-to-v2",
                    1,
                    2,
                    applied_at,
                    migration_sha256,
                    source_sha256_before,
                    backup_sha256,
                ),
            )
            connection.execute("PRAGMA user_version = 2")
            SQLiteRecordStore._validate_schema(connection)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        store = SQLiteRecordStore(path)
        integrity = store.integrity_report()
        if integrity["integrity"] != ["ok"] or integrity["foreign_key_violations"]:
            raise RuntimeError("migrated database failed integrity validation")
        return {
            "status": "migrated",
            "database": path.name,
            "backup": backup_path.name,
            "from_version": 1,
            "schema_version": SCHEMA_VERSION,
            "source_sha256_before": source_sha256_before,
            "backup_sha256": backup_sha256,
            "database_sha256_after": _sha256_file(path),
            "migration_sha256": migration_sha256,
            "applied_at": applied_at,
            "integrity": integrity,
        }


def import_pdbekb_report(database: str | Path, report: str | Path) -> dict[str, object]:
    path = Path(report)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("PDBe-KB report must be a JSON object")
    store = SQLiteRecordStore(database)
    store.import_pdbekb_report(payload)
    commitment = str(payload["content_commitment_sha256"])
    return {
        "status": "imported",
        "report_commitment_sha256": commitment,
        "enrichment_count": len(payload["enrichments"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run explicit MD metadata database migrations and enrichment imports."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    migrate = subparsers.add_parser("v1-to-v2")
    migrate.add_argument("--database", type=Path, required=True)
    migrate.add_argument("--backup", type=Path, required=True)
    import_report = subparsers.add_parser("import-pdbekb")
    import_report.add_argument("--database", type=Path, required=True)
    import_report.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "v1-to-v2":
        result = migrate_database_v1_to_v2(args.database, backup=args.backup)
    else:
        result = import_pdbekb_report(args.database, args.report)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
