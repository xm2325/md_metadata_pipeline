from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from mdmeta.integration import ArticleMetadata, IntegratedMDRecord, ProvenanceRecord
from mdmeta.models import Evidence, EventType, MappingSegment, ProtocolEvent
from mdmeta.storage import SQLiteRecordStore


DOCUMENT_ID = "WORKFLOW-SMOKE-1"


def build_fixture(output_dir: Path) -> tuple[Path, Path]:
    if output_dir.is_symlink():
        raise ValueError("fixture output directory must not be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True)
    database = output_dir / "records.sqlite"
    model_summary = output_dir / "model-summary.json"
    if database.exists() or model_summary.exists():
        raise FileExistsError("refusing to overwrite an existing workflow fixture")

    quote = "A 100 ns production simulation was run at 300 K."
    evidence = Evidence(
        document_id=DOCUMENT_ID,
        section="Methods",
        paragraph_id="p1",
        quote=quote,
        start_char=0,
        end_char=len(quote),
        context_sha256=hashlib.sha256(quote.encode()).hexdigest(),
    )
    record = IntegratedMDRecord(
        article=ArticleMetadata(
            document_id=DOCUMENT_ID,
            title="Nextflow production smoke fixture",
            source_uri="https://example.org/articles/workflow-smoke-1",
            full_text_sha256=hashlib.sha256(DOCUMENT_ID.encode()).hexdigest(),
        ),
        literature_facts=[],
        protocol_events=[
            ProtocolEvent(
                event_id="production-1",
                event_type=EventType.PRODUCTION,
                duration_ps=100_000,
                temperature_k=300,
                evidence=[evidence],
                relation_method="workflow_smoke_fixture",
                confidence=0.99,
            )
        ],
        pdb_validations=[],
        mapping_discoveries=[],
        uniprot_validations=[],
        mapping_validations=[],
        residue_mappings=[
            MappingSegment(
                pdb_id="1CBS",
                uniprot_accession="P29373",
                chain_id="A",
                pdb_start=1,
                pdb_end=137,
                uniprot_start=2,
                uniprot_end=138,
            )
        ],
        provenance=ProvenanceRecord(),
        completeness={"pipeline": "complete"},
    )
    store = SQLiteRecordStore(database)
    store.write(record)
    store.checkpoint()

    payload = {
        "batch": {
            "per_article": {
                DOCUMENT_ID: {
                    "paragraph_count": 1,
                    "accepted_paragraph_count": 1,
                    "accepted_with_evidence_rejections_count": 0,
                    "rejected_paragraph_count": 0,
                    "generation_rejected_count": 0,
                    "event_count": 1,
                }
            }
        }
    }
    model_summary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return database, model_summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the bounded Nextflow smoke fixture.")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    database, model_summary = build_fixture(args.output_dir)
    print(json.dumps({"database": str(database), "model_summary": str(model_summary)}))


if __name__ == "__main__":
    main()
