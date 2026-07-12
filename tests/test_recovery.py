from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
from contextlib import closing
from pathlib import Path

import pytest

import mdmeta.recovery as recovery_module
from mdmeta.integration import ArticleMetadata, IntegratedMDRecord, ProvenanceRecord
from mdmeta.recovery import backup_database, restore_database
from mdmeta.storage import SQLiteRecordStore
from mdmeta.verify import verify_database


def _record(document_id: str) -> IntegratedMDRecord:
    source = f"fixture:{document_id}"
    return IntegratedMDRecord(
        article=ArticleMetadata(
            document_id=document_id,
            title=f"Article {document_id}",
            source_uri=f"https://example.org/articles/{document_id}",
            full_text_sha256=hashlib.sha256(source.encode("utf-8")).hexdigest(),
        ),
        literature_facts=[],
        protocol_events=[],
        pdb_validations=[],
        mapping_discoveries=[],
        uniprot_validations=[],
        mapping_validations=[],
        residue_mappings=[],
        provenance=ProvenanceRecord(),
        completeness={"fixture": "complete"},
    )


def _write_article(connection: sqlite3.Connection, record: IntegratedMDRecord) -> None:
    connection.execute(
        """
        INSERT INTO articles(document_id, title, doi, source_uri, source_sha256, record_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            record.article.document_id,
            record.article.title,
            record.article.doi,
            record.article.source_uri,
            record.article.full_text_sha256,
            json.dumps(record.model_dump(mode="json"), sort_keys=True),
        ),
    )


def _finalized_database(path: Path, *document_ids: str) -> Path:
    store = SQLiteRecordStore(path)
    for document_id in document_ids:
        store.write(_record(document_id))
    store.checkpoint()
    return path


def test_store_refuses_nonempty_unversioned_database(tmp_path: Path) -> None:
    database = tmp_path / "foreign.sqlite"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE articles(document_id TEXT PRIMARY KEY)")
        connection.commit()

    with pytest.raises(RuntimeError, match="non-empty unversioned"):
        SQLiteRecordStore(database)

    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'articles'"
        ).fetchone()[0] == 1


def test_store_strictly_validates_columns_foreign_keys_and_indexes(tmp_path: Path) -> None:
    missing_index = _finalized_database(tmp_path / "missing-index.sqlite")
    with closing(sqlite3.connect(missing_index)) as connection:
        connection.execute("DROP INDEX idx_validation_state")
        connection.commit()
    with pytest.raises(RuntimeError, match="missing required index idx_validation_state"):
        SQLiteRecordStore(missing_index, read_only=True)

    wrong_columns = _finalized_database(tmp_path / "wrong-columns.sqlite")
    with closing(sqlite3.connect(wrong_columns)) as connection:
        connection.execute("ALTER TABLE md_assets RENAME COLUMN reason TO explanation")
        connection.commit()
    with pytest.raises(RuntimeError, match="md_assets has an incompatible column schema"):
        SQLiteRecordStore(wrong_columns, read_only=True)

    wrong_foreign_key = _finalized_database(tmp_path / "wrong-fk.sqlite")
    with closing(sqlite3.connect(wrong_foreign_key)) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("ALTER TABLE md_assets RENAME TO md_assets_old")
        connection.execute(
            """
            CREATE TABLE md_assets (
                document_id TEXT NOT NULL,
                role TEXT NOT NULL,
                identifier TEXT,
                availability TEXT NOT NULL,
                source_uri TEXT,
                local_path TEXT,
                sha256 TEXT,
                reason TEXT
            )
            """
        )
        connection.execute("DROP TABLE md_assets_old")
        connection.commit()
    with pytest.raises(RuntimeError, match="md_assets has incompatible foreign keys"):
        SQLiteRecordStore(wrong_foreign_key, read_only=True)

    unexpected_view = _finalized_database(tmp_path / "unexpected-view.sqlite")
    with closing(sqlite3.connect(unexpected_view)) as connection:
        connection.execute("CREATE VIEW article_titles AS SELECT title FROM articles")
        connection.commit()
    with pytest.raises(RuntimeError, match="unexpected version 1 objects"):
        SQLiteRecordStore(unexpected_view, read_only=True)


def test_database_verification_parses_records_and_redundant_columns(tmp_path: Path) -> None:
    database = _finalized_database(tmp_path / "records.sqlite", "DOC1")
    report = verify_database(database, expected_articles=1)
    assert report["valid"] is True
    assert report["record_validation"] == {"checked": 1, "valid": True, "errors": []}

    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "UPDATE articles SET source_sha256 = ? WHERE document_id = 'DOC1'", ("0" * 64,)
        )
        connection.commit()
    report = verify_database(database)
    assert report["valid"] is False
    assert report["record_validation"]["errors"] == [
        {
            "document_id": "DOC1",
            "reason": "redundant_column_mismatch",
            "fields": ["source_sha256"],
        }
    ]

    with closing(sqlite3.connect(database)) as connection:
        connection.execute("UPDATE articles SET record_json = '{'")
        connection.commit()
    report = verify_database(database)
    assert report["valid"] is False
    assert report["record_validation"]["errors"][0]["reason"] == "invalid_record_json"


def test_online_backup_includes_wal_without_changing_source_journal(tmp_path: Path) -> None:
    source = tmp_path / "live.sqlite"
    store = SQLiteRecordStore(source)
    store.write(_record("DOC1"))

    writer = sqlite3.connect(source)
    try:
        assert writer.execute("PRAGMA journal_mode").fetchone()[0].casefold() == "wal"
        _write_article(writer, _record("DOC2"))
        writer.commit()
        wal = Path(f"{source}-wal")
        assert wal.is_file() and wal.stat().st_size > 0

        destination = tmp_path / "backups" / "records.sqlite"
        report = backup_database(source, destination, expected_articles=2)

        assert report["valid"] is True
        assert report["article_count"] == 2
        assert report["integrity"]["journal_mode"] == "delete"
        assert writer.execute("PRAGMA journal_mode").fetchone()[0].casefold() == "wal"
        assert SQLiteRecordStore(destination, read_only=True).get("DOC2") is not None
    finally:
        writer.close()


def test_restore_preserves_digest_and_rejects_wrong_commitment(tmp_path: Path) -> None:
    source = _finalized_database(tmp_path / "source.sqlite", "DOC1")
    os.chmod(source, 0o640)
    digest = str(verify_database(source)["sha256"])
    restored = tmp_path / "restored" / "records.sqlite"

    report = restore_database(
        source,
        restored,
        expected_sha256=digest,
        expected_articles=1,
    )
    assert report["sha256"] == digest
    assert stat.S_IMODE(restored.stat().st_mode) == 0o640
    assert SQLiteRecordStore(restored, read_only=True).get("DOC1") is not None

    rejected = tmp_path / "rejected.sqlite"
    with pytest.raises(ValueError, match="does not match"):
        restore_database(source, rejected, expected_sha256="0" * 64)
    assert not rejected.exists()

    linked = tmp_path / "linked.sqlite"
    linked.symlink_to(source)
    with pytest.raises(ValueError, match="not a symlink"):
        restore_database(linked, tmp_path / "linked-restore.sqlite")


def test_finalized_snapshot_verification_rejects_any_sqlite_sidecar(
    tmp_path: Path,
) -> None:
    source = _finalized_database(tmp_path / "source.sqlite", "DOC1")
    journal = Path(f"{source}-journal")
    journal.write_bytes(b"hot-journal")

    report = verify_database(source)

    assert report["valid"] is False
    assert report["sidecar_files"] == [journal.name]
    with pytest.raises(ValueError, match="not a valid finalized SQLite snapshot"):
        restore_database(source, tmp_path / "restored.sqlite")


def test_restore_refuses_destination_with_sqlite_sidecars(tmp_path: Path) -> None:
    source = _finalized_database(tmp_path / "source.sqlite", "DOC1")
    destination = _finalized_database(tmp_path / "destination.sqlite", "OLD")
    original = destination.read_bytes()
    wal = Path(f"{destination}-wal")
    wal.write_bytes(b"stale-wal")

    with pytest.raises(ValueError, match="has SQLite sidecars"):
        restore_database(source, destination, overwrite=True)

    assert destination.read_bytes() == original
    assert wal.read_bytes() == b"stale-wal"


def test_failed_backup_does_not_publish_a_target(tmp_path: Path) -> None:
    source = _finalized_database(tmp_path / "invalid-source.sqlite", "DOC1")
    with closing(sqlite3.connect(source)) as connection:
        connection.execute("UPDATE articles SET record_json = '{'")
        connection.commit()
    destination = tmp_path / "backup" / "records.sqlite"

    with pytest.raises(RuntimeError, match="temporary database failed"):
        backup_database(source, destination)

    assert not destination.exists()
    assert not list(destination.parent.glob(f".{destination.name}.*.tmp"))


def test_overwrite_rolls_back_if_post_install_verification_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _finalized_database(tmp_path / "source.sqlite", "DOC1")
    destination = tmp_path / "destination.sqlite"
    original = b"previous database bytes"
    destination.write_bytes(original)
    real_verify = recovery_module.verify_database
    calls = 0

    def fail_post_install(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("simulated post-install failure")
        return real_verify(*args, **kwargs)

    monkeypatch.setattr(recovery_module, "verify_database", fail_post_install)
    with pytest.raises(RuntimeError, match="simulated post-install failure"):
        restore_database(source, destination, overwrite=True)

    assert destination.read_bytes() == original
