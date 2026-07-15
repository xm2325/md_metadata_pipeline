from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mdmeta.integration import IntegratedMDRecord
from mdmeta.pdbe_kb import PDBeKBEnrichment, fetch_pdbe_kb_annotations
from mdmeta.validation import IdentifierValidator


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _record_pdb_ids(record: IntegratedMDRecord) -> set[str]:
    from_facts = {
        str(fact.value).upper()
        for fact in record.literature_facts
        if fact.field == "starting_pdb_id"
    }
    from_mappings = {segment.pdb_id.upper() for segment in record.residue_mappings}
    return from_facts | from_mappings


def run(
    record_path: Path | None,
    pdb_ids: list[str],
    output_path: Path,
    cache_dir: Path,
    *,
    retain_payload: bool,
) -> dict[str, Any]:
    source_sha256 = None
    identifiers = {identifier.upper() for identifier in pdb_ids}
    if record_path is not None:
        source_bytes = record_path.read_bytes()
        source_sha256 = hashlib.sha256(source_bytes).hexdigest()
        record = IntegratedMDRecord.model_validate_json(source_bytes)
        identifiers.update(_record_pdb_ids(record))
    if not identifiers:
        raise ValueError("provide --record or at least one --pdb-id")

    enrichments: list[PDBeKBEnrichment] = []
    with IdentifierValidator(cache_dir=cache_dir) as validator:
        for pdb_id in sorted(identifiers):
            enrichments.append(
                fetch_pdbe_kb_annotations(validator, pdb_id, retain_payload=retain_payload)
            )

    payload = {
        "schema_version": "pdbe-kb-enrichment-run-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_record": str(record_path) if record_path is not None else None,
        "source_record_sha256": source_sha256,
        "pdb_id_count": len(identifiers),
        "annotation_count": sum(len(item.annotations) for item in enrichments),
        "enrichments": [item.model_dump(mode="json") for item in enrichments],
    }
    _atomic_write(output_path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch audited PDBe-KB/FunPDBe annotations for an integrated MD record."
    )
    parser.add_argument("--record", type=Path, help="IntegratedMDRecord JSON")
    parser.add_argument("--pdb-id", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument(
        "--retain-payload",
        action="store_true",
        help="Retain full upstream JSON; disabled by default for compact public artifacts.",
    )
    args = parser.parse_args()
    payload = run(
        args.record,
        args.pdb_id,
        args.output,
        args.cache_dir,
        retain_payload=args.retain_payload,
    )
    print(
        json.dumps(
            {
                "pdb_ids": payload["pdb_id_count"],
                "annotations": payload["annotation_count"],
                "output": str(args.output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
