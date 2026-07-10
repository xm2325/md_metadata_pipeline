from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .models import MDRecord

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS article (
  document_id TEXT PRIMARY KEY,
  title TEXT,
  doi TEXT,
  pmcid TEXT,
  source_uri TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  generated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fact (
  fact_id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES article(document_id),
  field_name TEXT NOT NULL,
  raw_value TEXT NOT NULL,
  normalized_value TEXT NOT NULL,
  unit TEXT,
  phase TEXT,
  method TEXT NOT NULL,
  confidence REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence (
  evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
  fact_id TEXT REFERENCES fact(fact_id),
  event_id TEXT,
  source_uri TEXT NOT NULL,
  section TEXT NOT NULL,
  paragraph_id TEXT NOT NULL,
  start_char INTEGER NOT NULL,
  end_char INTEGER NOT NULL,
  quote TEXT NOT NULL,
  context_sha256 TEXT NOT NULL,
  CHECK ((fact_id IS NOT NULL) OR (event_id IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS validation_event (
  validation_id INTEGER PRIMARY KEY AUTOINCREMENT,
  fact_id TEXT REFERENCES fact(fact_id),
  event_id TEXT,
  document_id TEXT NOT NULL REFERENCES article(document_id),
  validator TEXT NOT NULL,
  status TEXT NOT NULL,
  message TEXT NOT NULL,
  checked_at TEXT NOT NULL,
  source_uri TEXT,
  response_sha256 TEXT
);
CREATE TABLE IF NOT EXISTS protocol_event (
  event_id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES article(document_id),
  event_order INTEGER NOT NULL,
  phase TEXT NOT NULL,
  duration_value REAL,
  duration_unit TEXT,
  temperature_k REAL,
  pressure_bar REAL,
  ensemble TEXT,
  time_step_ps REAL,
  replicates INTEGER,
  completeness TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS event_fact (
  event_id TEXT NOT NULL REFERENCES protocol_event(event_id),
  fact_id TEXT NOT NULL REFERENCES fact(fact_id),
  PRIMARY KEY(event_id, fact_id)
);
CREATE TABLE IF NOT EXISTS structure_sequence_mapping (
  mapping_id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id TEXT NOT NULL REFERENCES article(document_id),
  pdb_id TEXT NOT NULL,
  uniprot_accession TEXT NOT NULL,
  chain_id TEXT NOT NULL,
  pdb_start INTEGER,
  pdb_end INTEGER,
  uniprot_start INTEGER,
  uniprot_end INTEGER,
  source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fact_field_value ON fact(field_name, normalized_value);
CREATE INDEX IF NOT EXISTS idx_fact_phase ON fact(phase);
CREATE INDEX IF NOT EXISTS idx_event_phase ON protocol_event(phase);
CREATE INDEX IF NOT EXISTS idx_evidence_document ON evidence(source_uri, paragraph_id);
"""


def write_sqlite(record: MDRecord, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(SCHEMA)
        article = record.article
        connection.execute(
            "INSERT INTO article VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                article.document_id,
                article.title,
                article.doi,
                article.pmcid,
                article.source_uri,
                record.schema_version,
                record.generated_at.isoformat(),
            ),
        )
        for fact in record.facts:
            if fact.fact_id is None:
                raise ValueError("fact_id must be assigned before storage")
            connection.execute(
                """INSERT INTO fact(fact_id, document_id, field_name, raw_value, normalized_value, unit, phase, method, confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    fact.fact_id,
                    article.document_id,
                    fact.field_name,
                    fact.raw_value,
                    json.dumps(fact.normalized_value, ensure_ascii=False),
                    fact.unit,
                    fact.phase,
                    fact.method,
                    fact.confidence,
                ),
            )
            for evidence in fact.evidence:
                connection.execute(
                    """INSERT INTO evidence(fact_id, event_id, source_uri, section, paragraph_id, start_char, end_char, quote, context_sha256)
                       VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        fact.fact_id,
                        evidence.source_uri,
                        evidence.section,
                        evidence.paragraph_id,
                        evidence.start_char,
                        evidence.end_char,
                        evidence.quote,
                        evidence.context_sha256,
                    ),
                )
            for event in fact.validation:
                connection.execute(
                    """INSERT INTO validation_event(fact_id, event_id, document_id, validator, status, message, checked_at, source_uri, response_sha256)
                       VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        fact.fact_id,
                        article.document_id,
                        event.validator,
                        event.status,
                        event.message,
                        event.checked_at.isoformat(),
                        event.source_uri,
                        event.response_sha256,
                    ),
                )

        for protocol_event in record.protocol_events:
            connection.execute(
                """INSERT INTO protocol_event VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    protocol_event.event_id,
                    article.document_id,
                    protocol_event.order,
                    protocol_event.phase,
                    protocol_event.duration_value,
                    protocol_event.duration_unit,
                    protocol_event.temperature_k,
                    protocol_event.pressure_bar,
                    protocol_event.ensemble,
                    protocol_event.time_step_ps,
                    protocol_event.replicates,
                    protocol_event.completeness,
                ),
            )
            for fact_id in protocol_event.source_fact_ids:
                connection.execute(
                    "INSERT OR IGNORE INTO event_fact(event_id, fact_id) VALUES (?, ?)",
                    (protocol_event.event_id, fact_id),
                )
            for evidence in protocol_event.evidence:
                connection.execute(
                    """INSERT INTO evidence(fact_id, event_id, source_uri, section, paragraph_id, start_char, end_char, quote, context_sha256)
                       VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        protocol_event.event_id,
                        evidence.source_uri,
                        evidence.section,
                        evidence.paragraph_id,
                        evidence.start_char,
                        evidence.end_char,
                        evidence.quote,
                        evidence.context_sha256,
                    ),
                )
            for event in protocol_event.validation:
                connection.execute(
                    """INSERT INTO validation_event(fact_id, event_id, document_id, validator, status, message, checked_at, source_uri, response_sha256)
                       VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        protocol_event.event_id,
                        article.document_id,
                        event.validator,
                        event.status,
                        event.message,
                        event.checked_at.isoformat(),
                        event.source_uri,
                        event.response_sha256,
                    ),
                )

        for event in record.record_validation:
            connection.execute(
                """INSERT INTO validation_event(fact_id, event_id, document_id, validator, status, message, checked_at, source_uri, response_sha256)
                   VALUES (NULL, NULL, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    article.document_id,
                    event.validator,
                    event.status,
                    event.message,
                    event.checked_at.isoformat(),
                    event.source_uri,
                    event.response_sha256,
                ),
            )
        for mapping in record.mappings:
            connection.execute(
                """INSERT INTO structure_sequence_mapping(document_id, pdb_id, uniprot_accession, chain_id, pdb_start, pdb_end,
                   uniprot_start, uniprot_end, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    article.document_id,
                    mapping.pdb_id,
                    mapping.uniprot_accession,
                    mapping.chain_id,
                    mapping.pdb_start,
                    mapping.pdb_end,
                    mapping.uniprot_start,
                    mapping.uniprot_end,
                    mapping.source,
                ),
            )
        connection.commit()
