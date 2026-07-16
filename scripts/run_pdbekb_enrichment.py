from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from mdmeta.pdbekb import build_pdbekb_batch_report, fetch_pdbekb_enrichment
from mdmeta.storage import SQLiteRecordStore
from mdmeta.validation import IdentifierValidator


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def run(
    database: Path,
    *,
    output: Path,
    cache_dir: Path,
    require_complete: bool,
) -> dict[str, object]:
    store = SQLiteRecordStore(database, read_only=True)
    accessions = store.list_uniprot_accessions()
    if not accessions:
        raise ValueError("source database contains no mapped UniProt accessions")
    validator = IdentifierValidator(cache_dir=cache_dir)
    enrichments = [fetch_pdbekb_enrichment(validator, accession) for accession in accessions]
    report = build_pdbekb_batch_report(
        enrichments,
        source_database=database,
        source_database_schema_version=store.schema_version(),
        source_article_count=store.count_articles(),
    )
    payload = report.model_dump(mode="json")
    _atomic_write_json(output, payload)
    if require_complete and report.state_counts != {"validated": len(accessions)}:
        raise RuntimeError(
            "PDBe-KB completeness gate failed after report publication: "
            f"{report.state_counts}"
        )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch compact, auditable PDBe-KB enrichment for a verified MD metadata DB."
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    payload = run(
        args.database,
        output=args.output,
        cache_dir=args.cache_dir,
        require_complete=args.require_complete,
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "accession_count": len(payload["requested_accessions"]),
                "state_counts": payload["state_counts"],
                "content_commitment_sha256": payload["content_commitment_sha256"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
