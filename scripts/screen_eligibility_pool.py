from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

import httpx

from scripts.screen_selected_fulltext import fetch_xml, screen_xml


def screen_pool(pool: dict, client: httpx.Client, delay: float) -> dict:
    records = []
    failures = []
    for position, article in enumerate(pool["screening_pool"], start=1):
        document_id = article["document_id"]
        try:
            payload = fetch_xml(document_id, client)
            record = screen_xml(document_id, payload, "unassigned")
            record["pool_position"] = position
            records.append(record)
            if delay > 0:
                time.sleep(delay)
        except (httpx.HTTPError, ValueError, OSError) as exc:
            failures.append(
                {
                    "document_id": document_id,
                    "pool_position": position,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            )
    status_counts = Counter(record["machine_screen_status"] for record in records)
    engine_counts = Counter(
        engine for record in records for engine in record["engine_mentions"]
    )
    return {
        "study_id": pool["study_id"],
        "study_status": pool["study_status"],
        "pool_sha256": pool["pool_sha256"],
        "screening_scope": "machine_triage_not_human_eligibility",
        "requested_articles": len(pool["screening_pool"]),
        "screened_articles": len(records),
        "failure_count": len(failures),
        "status_counts": dict(sorted(status_counts.items())),
        "engine_mention_counts": dict(sorted(engine_counts.items())),
        "machine_eligible_count": sum(
            bool(record["machine_eligible_for_annotation"]) for record in records
        ),
        "records": records,
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Screen an ordered eligibility pool without storing article XML."
    )
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--delay", type=float, default=0.05)
    args = parser.parse_args()

    pool = json.loads(args.pool.read_text(encoding="utf-8"))
    with httpx.Client(
        timeout=args.timeout,
        headers={"User-Agent": "md-metadata-pipeline/0.8 eligibility-screen"},
        follow_redirects=True,
    ) as client:
        result = screen_pool(pool, client, args.delay)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "screened_articles",
                    "failure_count",
                    "status_counts",
                    "machine_eligible_count",
                )
            },
            indent=2,
        )
    )
    if result["failure_count"]:
        raise SystemExit("one or more pool articles could not be screened")


if __name__ == "__main__":
    main()
