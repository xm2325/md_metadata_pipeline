from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mdmeta.api import create_app
from mdmeta.integration import ArticleMetadata, IntegratedMDRecord, ProvenanceRecord
from mdmeta.migrate import import_pdbekb_report, migrate_database_v1_to_v2
from mdmeta.models import MappingSegment, ValidationState
from mdmeta.pdbekb import (
    PDBeKBAnnotationGroup,
    PDBeKBEndpointResult,
    PDBeKBEnrichment,
    PDBeKBPartner,
    build_pdbekb_batch_report,
)
from mdmeta.storage import SQLiteRecordStore


ACCESSION = "Q14676"


def _record() -> IntegratedMDRecord:
    return IntegratedMDRecord(
        article=ArticleMetadata(
            document_id="DOC1",
            title="Migration fixture",
            source_uri="https://example.org/articles/DOC1",
            full_text_sha256=hashlib.sha256(b"DOC1").hexdigest(),
        ),
        literature_facts=[],
        protocol_events=[],
        pdb_validations=[],
        mapping_discoveries=[],
        uniprot_validations=[],
        mapping_validations=[],
        residue_mappings=[
            MappingSegment(
                pdb_id="3UNN",
                uniprot_accession=ACCESSION,
                chain_id="B",
                pdb_start=1,
                pdb_end=20,
                uniprot_start=1,
                uniprot_end=20,
            )
        ],
        provenance=ProvenanceRecord(),
        completeness={"fixture": "complete"},
    )


def _downgraded_v1_database(path: Path) -> Path:
    store = SQLiteRecordStore(path)
    store.write(_record())
    store.checkpoint()
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("DROP INDEX idx_pdbekb_enrichment_state")
        connection.execute("DROP INDEX idx_pdbekb_enrichment_accession")
        connection.execute("DROP TABLE pdbekb_enrichments")
        connection.execute("DROP TABLE pdbekb_reports")
        connection.execute("DROP TABLE schema_migrations")
        connection.execute("PRAGMA user_version = 1")
        connection.commit()
    return path


def _enrichment() -> PDBeKBEnrichment:
    annotation = PDBeKBEndpointResult(
        state=ValidationState.VALIDATED,
        endpoint=f"https://www.ebi.ac.uk/pdbe/graph-api/uniprot/annotations/{ACCESSION}",
        reason="pdbekb_annotations_validated",
        http_status=200,
        response_sha256="a" * 64,
        attempts=1,
    )
    partners = PDBeKBEndpointResult(
        state=ValidationState.VALIDATED,
        endpoint=(
            "https://www.ebi.ac.uk/pdbe/graph-api/uniprot/"
            f"annotation_partners/{ACCESSION}"
        ),
        reason="pdbekb_partners_validated",
        http_status=200,
        response_sha256="b" * 64,
        attempts=1,
    )
    return PDBeKBEnrichment(
        accession=ACCESSION,
        state=ValidationState.VALIDATED,
        sequence_length=20,
        annotation_result=annotation,
        partner_result=partners,
        annotation_groups=[
            PDBeKBAnnotationGroup(
                name="Predicted ligand pocket",
                accession="p2rank",
                data_type="ANNOTATION",
                residue_range_count=1,
                covered_sequence_position_count=3,
                pdb_ids=["3UNN"],
            )
        ],
        partners=[
            PDBeKBPartner(
                resource_name="p2rank",
                url="https://example.org/p2rank",
                annotation_category="predicted_ligand_binding_site",
            )
        ],
    )


def test_explicit_v1_to_v2_migration_preserves_records_and_imports_pdbekb(
    tmp_path: Path,
) -> None:
    database = _downgraded_v1_database(tmp_path / "records.sqlite")
    report = build_pdbekb_batch_report(
        [_enrichment()],
        source_database=database,
        source_database_schema_version=1,
        source_article_count=1,
        generated_at=datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
    )
    report_path = tmp_path / "pdbekb.json"
    report_path.write_text(
        json.dumps(report.model_dump(mode="json"), sort_keys=True), encoding="utf-8"
    )
    backup = tmp_path / "backups" / "records-v1.sqlite"

    result = migrate_database_v1_to_v2(database, backup=backup)

    assert result["status"] == "migrated"
    assert result["from_version"] == 1
    assert result["schema_version"] == 2
    assert result["backup_sha256"] == hashlib.sha256(backup.read_bytes()).hexdigest()
    with closing(sqlite3.connect(backup)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
    store = SQLiteRecordStore(database)
    assert store.schema_version() == 2
    assert store.get("DOC1")["article"]["title"] == "Migration fixture"
    with closing(sqlite3.connect(database)) as connection:
        row = connection.execute(
            """
            SELECT from_version, to_version, source_sha256_before, backup_sha256
            FROM schema_migrations WHERE migration_id = 'sqlite-v1-to-v2'
            """
        ).fetchone()
    assert row == (1, 2, result["source_sha256_before"], result["backup_sha256"])

    imported = import_pdbekb_report(database, report_path)

    assert imported["status"] == "imported"
    rows = store.get_pdbekb_enrichments(ACCESSION.lower())
    assert len(rows) == 1
    assert rows[0]["annotation_groups"][0]["pdb_ids"] == ["3UNN"]
    response = TestClient(create_app(database)).get(f"/pdbekb/{ACCESSION.lower()}")
    assert response.status_code == 200
    assert response.json()["accession"] == ACCESSION
    assert response.json()["count"] == 1


def test_migration_rejects_invalid_v1_without_partial_change(tmp_path: Path) -> None:
    database = _downgraded_v1_database(tmp_path / "invalid.sqlite")
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE VIEW unexpected AS SELECT title FROM articles")
        connection.commit()
    backup = tmp_path / "backup.sqlite"

    with pytest.raises(RuntimeError, match="unexpected version 1 objects"):
        migrate_database_v1_to_v2(database, backup=backup)

    assert not backup.exists()
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name = 'schema_migrations'"
        ).fetchone()[0] == 0


def test_migration_is_idempotent_without_overwriting_backup(tmp_path: Path) -> None:
    database = tmp_path / "current.sqlite"
    SQLiteRecordStore(database).checkpoint()
    backup = tmp_path / "must-not-be-created.sqlite"

    result = migrate_database_v1_to_v2(database, backup=backup)

    assert result == {
        "status": "already_current",
        "database": database.name,
        "schema_version": 2,
    }
    assert not backup.exists()
