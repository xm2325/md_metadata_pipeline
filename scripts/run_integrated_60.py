from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx

from mdmeta import user_agent
from mdmeta.benchmark import canonical_sha256
from mdmeta.integration import integrate_article, summarize_integrated_records
from mdmeta.storage import SQLiteRecordStore
from mdmeta.validation import IdentifierValidator

FULLTEXT_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
_SPLITS = ("development", "validation", "locked_test")


def validate_source_manifest(manifest: dict) -> list[dict]:
    stored_digest = manifest.get("manifest_sha256")
    core = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if stored_digest != canonical_sha256(core):
        raise ValueError("source manifest commitment is invalid")
    articles = manifest.get("articles", [])
    if len(articles) != 60:
        raise ValueError(f"expected 60 manifest articles, found {len(articles)}")
    counts = Counter(article.get("split") for article in articles)
    if counts != Counter({"development": 30, "validation": 10, "locked_test": 20}):
        raise ValueError(f"unexpected 30/10/20 split counts: {dict(counts)}")
    document_ids = [article.get("document_id") for article in articles]
    if len(set(document_ids)) != len(document_ids):
        raise ValueError("source manifest contains duplicate document identifiers")
    if any(split not in _SPLITS for split in counts):
        raise ValueError("source manifest contains an unknown split")
    return articles


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run evidence-linked integration across the frozen provisional 60-article set."
    )
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--delay", type=float, default=0.05)
    args = parser.parse_args()

    source_manifest = json.loads(args.source_manifest.read_text(encoding="utf-8"))
    articles = validate_source_manifest(source_manifest)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    records_dir = args.output_dir / "records"
    records_dir.mkdir(exist_ok=True)
    store = SQLiteRecordStore(args.database)
    records = []
    failures: list[dict] = []

    with httpx.Client(
        timeout=args.timeout,
        follow_redirects=True,
        headers={"User-Agent": user_agent("integrated-60")},
    ) as client:
        validator = IdentifierValidator(client, cache_dir=args.cache_dir)
        for article in articles:
            document_id = article["document_id"]
            try:
                response = client.get(FULLTEXT_URL.format(pmcid=document_id))
                response.raise_for_status()
                xml_bytes = response.content
                digest = hashlib.sha256(xml_bytes).hexdigest()
                if digest != article["full_text_sha256"]:
                    raise ValueError("JATS SHA-256 differs from the frozen source snapshot")
                record = integrate_article(
                    document_id,
                    xml_bytes,
                    source_uri=article["source_uri"],
                    validator=validator,
                )
                store.write(record)
                records.append(record)
                (records_dir / f"{document_id}.json").write_text(
                    json.dumps(
                        record.model_dump(mode="json"),
                        indent=2,
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            except (httpx.HTTPError, OSError, ValueError) as exc:
                failures.append(
                    {
                        "document_id": document_id,
                        "split": article["split"],
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    }
                )
            if args.delay > 0:
                time.sleep(args.delay)

    summary = summarize_integrated_records(records, failures)
    result = {
        "study_id": source_manifest["study_id"],
        "study_status": source_manifest["study_status"],
        "source_plan_sha256": source_manifest["plan_sha256"],
        "source_screen_sha256": source_manifest["source_screen_sha256"],
        "source_manifest_sha256": source_manifest["manifest_sha256"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "external_validation_policy": (
            "network failures remain unresolved; only successful identifier/mapping responses "
            "can create validated or conflict states"
        ),
        "md_file_policy": (
            "literature-only articles do not receive an invented MD-to-PDB residue mapping"
        ),
        "summary": summary,
        "record_index": [
            {
                "document_id": record.article.document_id,
                "title": record.article.title,
                "doi": record.article.doi,
                "record_path": f"records/{record.article.document_id}.json",
                "completeness": record.completeness,
            }
            for record in records
        ],
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))
    if failures:
        raise SystemExit("one or more articles failed source retrieval or integration")
    if len(records) != 60 or store.count_articles() != 60:
        raise SystemExit("60-article integration completeness gate failed")


if __name__ == "__main__":
    main()
