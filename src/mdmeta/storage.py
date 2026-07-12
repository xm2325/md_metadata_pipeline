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
_EXPECTED_COLUMNS: dict[str, tuple[tuple[str, str, int, int], ...]] = {
    "articles": (
        ("document_id", "TEXT", 0, 1),
        ("title", "TEXT", 1, 0),
        ("doi", "TEXT", 0, 0),
        ("source_uri", "TEXT", 1, 0),
        ("source_sha256", "TEXT", 1, 0),
        ("record_json", "TEXT", 1, 0),
    ),
    "literature_facts": (
        ("document_id", "TEXT", 1, 0),
        ("field", "TEXT", 1, 0),
        ("value_json", "TEXT", 1, 0),
        ("origin", "TEXT", 1, 0),
        ("evidence_json", "TEXT", 1, 0),
    ),
    "validations": (
        ("document_id", "TEXT", 1, 0),
        ("category", "TEXT", 1, 0),
        ("identifier_type", "TEXT", 1, 0),
        ("query_json", "TEXT", 1, 0),
        ("state", "TEXT", 1, 0),
        ("reason", "TEXT", 1, 0),
        ("response_sha256", "TEXT", 0, 0),
        ("endpoint", "TEXT", 1, 0),
    ),
    "residue_mappings": (
        ("document_id", "TEXT", 1, 0),
        ("pdb_id", "TEXT", 1, 0),
        ("uniprot_accession", "TEXT", 1, 0),
        ("chain_id", "TEXT", 1, 0),
        ("pdb_start", "INTEGER", 0, 0),
        ("pdb_end", "INTEGER", 0, 0),
        ("uniprot_start", "INTEGER", 0, 0),
        ("uniprot_end", "INTEGER", 0, 0),
    ),
    "md_assets": (
        ("document_id", "TEXT", 1, 0),
        ("role", "TEXT", 1, 0),
        ("identifier", "TEXT", 0, 0),
        ("availability", "TEXT", 1, 0),
        ("source_uri", "TEXT", 0, 0),
        ("local_path", "TEXT", 0, 0),
        ("sha256", "TEXT", 0, 0),
        ("reason", "TEXT", 0, 0),
    ),
}
_EXPECTED_INDEXES: dict[str, tuple[str, tuple[str, ...]]] = {
    "idx_facts_field_value": ("literature_facts", ("field", "value_json")),
    "idx_validation_state": ("validations", ("state",)),
    "idx_mapping_pdb": ("residue_mappings", ("pdb_id",)),
    "idx_mapping_uniprot": ("residue_mappings", ("uniprot_accession",)),
}
_EXPECTED_USER_OBJECTS = {
    *(("table", table) for table in _REQUIRED_TABLES),
    *(("index", index) for index in _EXPECTED_INDEXES),
}
_FOREIGN_KEY_TABLES = _REQUIRED_TABLES - {"articles"}
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
                    if self._has_user_schema(connection):
                        raise RuntimeError(
                            "refusing to initialize a non-empty unversioned database"
                        )
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

    @staticmethod
    def _has_user_schema(connection: sqlite3.Connection) -> bool:
        row = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE name NOT LIKE 'sqlite_%'
              AND type IN ('table', 'index', 'view', 'trigger')
            LIMIT 1
            """
        ).fetchone()
        return row is not None

    @classmethod
    def _validate_schema(cls, connection: sqlite3.Connection) -> None:
        version = cls._schema_version(connection)
        if version != SCHEMA_VERSION:
            raise RuntimeError(
                f"unsupported database schema version {version}; expected {SCHEMA_VERSION}"
            )
        object_rows = connection.execute(
            """
            SELECT type, name FROM sqlite_master
            WHERE type IN ('table', 'index', 'view', 'trigger')
              AND name NOT LIKE 'sqlite_%'
            """
        ).fetchall()
        objects = {(str(row[0]), str(row[1])) for row in object_rows}
        tables = {name for object_type, name in objects if object_type == "table"}
        missing = sorted(_REQUIRED_TABLES - tables)
        if missing:
            raise RuntimeError(f"database schema is incomplete; missing tables: {missing}")
        unexpected = sorted(tables - _REQUIRED_TABLES)
        if unexpected:
            raise RuntimeError(
                f"database schema contains unexpected tables for version 1: {unexpected}"
            )
        unexpected_objects = sorted(objects - _EXPECTED_USER_OBJECTS)
        if unexpected_objects:
            rendered = [f"{object_type}:{name}" for object_type, name in unexpected_objects]
            raise RuntimeError(
                "database schema contains unexpected version 1 objects: " + ", ".join(rendered)
            )

        for table, expected in _EXPECTED_COLUMNS.items():
            rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
            actual = tuple(
                (str(row[1]), str(row[2]).upper(), int(row[3]), int(row[5]))
                for row in rows
            )
            if actual != expected:
                raise RuntimeError(f"database table {table} has an incompatible column schema")

        for table in sorted(_FOREIGN_KEY_TABLES):
            rows = connection.execute(f"PRAGMA foreign_key_list({table})").fetchall()
            actual = {
                (
                    str(row[2]),
                    str(row[3]),
                    str(row[4]),
                    str(row[5]).upper(),
                    str(row[6]).upper(),
                    str(row[7]).upper(),
                )
                for row in rows
            }
            expected = {
                (
                    "articles",
                    "document_id",
                    "document_id",
                    "NO ACTION",
                    "CASCADE",
                    "NONE",
                )
            }
            if actual != expected:
                raise RuntimeError(f"database table {table} has incompatible foreign keys")

        for index, (table, expected_columns) in _EXPECTED_INDEXES.items():
            rows = connection.execute(f"PRAGMA index_list({table})").fetchall()
            matching = [row for row in rows if str(row[1]) == index]
            if len(matching) != 1:
                raise RuntimeError(f"database schema is missing required index {index}")
            row = matching[0]
            if int(row[2]) != 0 or int(row[4]) != 0:
                raise RuntimeError(f"database index {index} has incompatible properties")
            columns = tuple(
                str(item[2])
                for item in connection.execute(f"PRAGMA index_info({index})").fetchall()
            )
            if columns != expected_columns:
                raise RuntimeError(f"database index {index} has incompatible columns")

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

    def verification_rows(self) -> list[dict[str, object]]:
        """Return the stored record and its deliberately redundant article columns."""

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT document_id, title, doi, source_uri, source_sha256, record_json
                FROM articles
                ORDER BY document_id
                """
            ).fetchall()
        return [dict(row) for row in rows]

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
