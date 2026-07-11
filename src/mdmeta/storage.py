from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .integration import IntegratedMDRecord


SCHEMA_VERSION = 1
_REQUIRED_TABLES = {
    "articles",
    "literature_facts",
    "validations",
    "residue_mappings",
    "md_assets",
}
_SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
CREATE TABLE IF NOT EXISTS articles (
    document_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    doi TEXT,
    source_uri TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    record_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS literature_facts (
    document_id TEXT NOT NULL,
    field TEXT NOT NULL,
    value_json TEXT NOT NULL,
    origin TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES articles(document_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_facts_field_value
    ON literature_facts(field, value_json);
CREATE TABLE IF NOT EXISTS validations (
    document_id TEXT NOT NULL,
    category TEXT NOT NULL,
    identifier_type TEXT NOT NULL,
    query_json TEXT NOT NULL,
    state TEXT NOT NULL,
    reason TEXT NOT NULL,
    response_sha256 TEXT,
    endpoint TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES articles(document_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_validation_state ON validations(state);
CREATE TABLE IF NOT EXISTS residue_mappings (
    document_id TEXT NOT NULL,
    pdb_id TEXT NOT NULL,
    uniprot_accession TEXT NOT NULL,
    chain_id TEXT NOT NULL,
    pdb_start INTEGER,
    pdb_end INTEGER,
    uniprot_start INTEGER,
    uniprot_end INTEGER,
    FOREIGN KEY(document_id) REFERENCES articles(document_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_mapping_pdb ON residue_mappings(pdb_id);
CREATE INDEX IF NOT EXISTS idx_mapping_uniprot ON residue_mappings(uniprot_accession);
CREATE TABLE IF NOT EXISTS md_assets (
    document_id TEXT NOT NULL,
    role TEXT NOT NULL,
    identifier TEXT,
    availability TEXT NOT NULL,
    source_uri TEXT,
    local_path TEXT,
    sha256 TEXT,
    reason TEXT,
    FOREIGN KEY(document_id) REFERENCES articles(document_id) ON DELETE CASCADE
);
"""


class SQLiteRecordStore:
    def __init__(self, path: str | Path, *, read_only: bool = False) -> None:
        self.path = Path(path)
        self.read_only = read_only
        if self.read_only:
            if not self.path.is_file():
                raise FileNotFoundError(self.path)
            with self._connect() as connection:
                self._validate_schema(connection)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                version = self._schema_version(connection)
                if version == 0:
                    connection.executescript(_SCHEMA)
                    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                elif version != SCHEMA_VERSION:
                    raise RuntimeError(
                        f"unsupported database schema version {version}; "
                        f"expected {SCHEMA_VERSION}"
                    )
                self._validate_schema(connection)

    @staticmethod
    def _schema_version(connection: sqlite3.Connection) -> int:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])

    @classmethod
    def _validate_schema(cls, connection: sqlite3.Connection) -> None:
        version = cls._schema_version(connection)
        if version != SCHEMA_VERSION:
            raise RuntimeError(
                f"unsupported database schema version {version}; expected {SCHEMA_VERSION}"
            )
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        tables = {str(row[0]) for row in rows}
        missing = sorted(_REQUIRED_TABLES - tables)
        if missing:
            raise RuntimeError(f"database schema is incomplete; missing tables: {missing}")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if self.read_only:
            # Deployment serves a checkpointed snapshot that is never replaced
            # under a running process.  immutable=1 avoids WAL shared-memory
            # writes when the dataset mount itself is read-only.
            uri = f"{self.path.resolve().as_uri()}?mode=ro&immutable=1"
            connection = sqlite3.connect(uri, uri=True)
        else:
            connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        # SQLite applies foreign-key enforcement per connection.  Enabling it
        # only in the schema bootstrap connection leaves later upserts unable
        # to cascade-delete the previous child rows.
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

    def write(self, record: IntegratedMDRecord) -> None:
        if self.read_only:
            raise RuntimeError("cannot write through a read-only record store")
        document_id = record.article.document_id
        payload = json.dumps(record.model_dump(mode="json"), sort_keys=True)
        with self._connect() as connection:
            connection.execute("DELETE FROM articles WHERE document_id = ?", (document_id,))
            connection.execute(
                """
                INSERT INTO articles(
                    document_id, title, doi, source_uri, source_sha256, record_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    record.article.title,
                    record.article.doi,
                    record.article.source_uri,
                    record.article.full_text_sha256,
                    payload,
                ),
            )
            connection.executemany(
                """
                INSERT INTO literature_facts(document_id, field, value_json, origin, evidence_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        document_id,
                        fact.field,
                        json.dumps(fact.value, sort_keys=True),
                        fact.origin.value,
                        json.dumps(fact.evidence.model_dump(mode="json"), sort_keys=True),
                    )
                    for fact in record.literature_facts
                ],
            )
            validation_rows = []
            for category, rows in (
                ("pdb", record.pdb_validations),
                ("uniprot", record.uniprot_validations),
                ("mapping", record.mapping_validations),
            ):
                validation_rows.extend(
                    (
                        document_id,
                        category,
                        row.identifier_type,
                        json.dumps(row.query, sort_keys=True),
                        row.state.value,
                        row.reason,
                        row.response_sha256,
                        row.endpoint,
                    )
                    for row in rows
                )
            connection.executemany(
                """
                INSERT INTO validations(
                    document_id, category, identifier_type, query_json,
                    state, reason, response_sha256, endpoint
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                validation_rows,
            )
            connection.executemany(
                """
                INSERT INTO residue_mappings(
                    document_id, pdb_id, uniprot_accession, chain_id,
                    pdb_start, pdb_end, uniprot_start, uniprot_end
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        document_id,
                        segment.pdb_id,
                        segment.uniprot_accession,
                        segment.chain_id,
                        segment.pdb_start,
                        segment.pdb_end,
                        segment.uniprot_start,
                        segment.uniprot_end,
                    )
                    for segment in record.residue_mappings
                ],
            )
            connection.executemany(
                """
                INSERT INTO md_assets(
                    document_id, role, identifier, availability,
                    source_uri, local_path, sha256, reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        document_id,
                        asset.role,
                        asset.identifier,
                        asset.availability.value,
                        asset.source_uri,
                        asset.local_path,
                        asset.sha256,
                        asset.reason,
                    )
                    for asset in record.provenance.assets
                ],
            )

    def get(self, document_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT record_json FROM articles WHERE document_id = ?",
                (document_id,),
            ).fetchone()
        return json.loads(row["record_json"]) if row is not None else None

    def search(
        self,
        *,
        pdb_id: str | None = None,
        uniprot_accession: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        if limit is not None and limit < 1:
            raise ValueError("limit must be positive")
        document_ids: set[str] = set()
        with self._connect() as connection:
            if pdb_id is not None:
                rows = connection.execute(
                    """
                    SELECT DISTINCT document_id FROM literature_facts
                    WHERE field = 'starting_pdb_id' AND value_json = ?
                    UNION
                    SELECT DISTINCT document_id FROM residue_mappings WHERE pdb_id = ?
                    """,
                    (json.dumps(pdb_id.upper()), pdb_id.upper()),
                ).fetchall()
                document_ids.update(row["document_id"] for row in rows)
            if uniprot_accession is not None:
                rows = connection.execute(
                    """
                    SELECT DISTINCT document_id FROM residue_mappings
                    WHERE uniprot_accession = ?
                    """,
                    (uniprot_accession.upper(),),
                ).fetchall()
                document_ids.update(row["document_id"] for row in rows)
            if not document_ids:
                return []
            selected_ids = sorted(document_ids)
            if limit is not None:
                selected_ids = selected_ids[:limit]
            placeholders = ",".join("?" for _ in selected_ids)
            rows = connection.execute(
                (
                    "SELECT record_json FROM articles "
                    f"WHERE document_id IN ({placeholders}) ORDER BY document_id"
                ),
                tuple(selected_ids),
            ).fetchall()
        return [json.loads(row["record_json"]) for row in rows]

    def count_articles(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS n FROM articles").fetchone()
        return int(row["n"])

    def schema_version(self) -> int:
        with self._connect() as connection:
            return self._schema_version(connection)

    def checkpoint(self) -> tuple[int, int, int]:
        """Checkpoint WAL and finalize a portable single-file snapshot."""

        if self.read_only:
            raise RuntimeError("cannot checkpoint a read-only record store")
        with self._connect() as connection:
            row = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            result = int(row[0]), int(row[1]), int(row[2])
            if result[0] == 0 and result[1] == result[2]:
                journal_mode = str(
                    connection.execute("PRAGMA journal_mode = DELETE").fetchone()[0]
                ).casefold()
                if journal_mode != "delete":
                    raise RuntimeError(
                        f"failed to finalize snapshot journal mode: {journal_mode}"
                    )
        return result

    def integrity_report(self) -> dict[str, object]:
        """Return SQLite structural and foreign-key integrity results."""

        with self._connect() as connection:
            integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
            foreign_key_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
            schema_version = self._schema_version(connection)
            journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
        return {
            "integrity": [str(row[0]) for row in integrity_rows],
            "foreign_key_violations": [list(row) for row in foreign_key_rows],
            "schema_version": schema_version,
            "journal_mode": journal_mode,
        }
