from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx

from mdmeta import user_agent
from mdmeta.integration import integrate_article, summarize_integrated_records
from mdmeta.storage import SQLiteRecordStore
from mdmeta.validation import IdentifierValidator


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one evidence-linked literature→PDBe→UniProt→SIFTS integration case."
    )
    parser.add_argument("--xml", type=Path, required=True)
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--source-uri", required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--expect-pdb", action="append", default=[])
    parser.add_argument("--expect-uniprot", action="append", default=[])
    args = parser.parse_args()

    manifest = (
        json.loads(args.manifest.read_text(encoding="utf-8"))
        if args.manifest is not None
        else None
    )
    xml_bytes = args.xml.read_bytes()
    with httpx.Client(
        timeout=args.timeout,
        follow_redirects=True,
        headers={"User-Agent": user_agent("golden-live")},
    ) as client:
        validator = IdentifierValidator(client, cache_dir=args.cache_dir)
        record = integrate_article(
            args.document_id,
            xml_bytes,
            source_uri=args.source_uri,
            validator=validator,
            provenance_manifest=manifest,
            provenance_base_dir=args.manifest.parent if args.manifest else None,
        )

    observed_pdb = {
        str(fact.value)
        for fact in record.literature_facts
        if fact.field == "starting_pdb_id"
    }
    observed_uniprot = {
        segment.uniprot_accession for segment in record.residue_mappings
    }
    missing_pdb = sorted(set(args.expect_pdb) - observed_pdb)
    missing_uniprot = sorted(set(args.expect_uniprot) - observed_uniprot)
    if missing_pdb:
        raise SystemExit(f"missing expected PDB identifiers: {missing_pdb}")
    if missing_uniprot:
        raise SystemExit(f"missing expected UniProt accessions: {missing_uniprot}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(record.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    store = SQLiteRecordStore(args.database)
    store.write(record)
    print(json.dumps(summarize_integrated_records([record]), indent=2))


if __name__ == "__main__":
    main()
