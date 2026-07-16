#!/usr/bin/env python3
"""Stage frozen Europe PMC JATS inputs in a private cache before GPU inference."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import httpx

from mdmeta import user_agent
from mdmeta.benchmark import canonical_sha256
from mdmeta.llm_batch import (
    atomic_write_json,
    fetch_frozen_jats,
    select_articles,
    validate_source_manifest,
)
from mdmeta.integration import (
    extract_literature_facts,
    parse_jats_paragraphs,
    protocol_paragraphs,
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--article-limit", type=int)
    parser.add_argument("--document-id", action="append", default=[])
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--retries", type=int, default=5)
    args = parser.parse_args()

    source_payload = json.loads(args.source_manifest.read_text(encoding="utf-8"))
    all_articles = validate_source_manifest(source_payload)
    articles = select_articles(
        all_articles,
        limit=args.article_limit,
        document_ids=args.document_id,
    )
    records: list[dict] = []
    headers = {"User-Agent": user_agent("roihu-frozen-jats-stage")}
    with httpx.Client(
        timeout=args.timeout,
        headers=headers,
        follow_redirects=True,
    ) as client:
        for article in articles:
            payload, cache_hit = fetch_frozen_jats(
                article,
                cache_dir=args.cache_dir,
                client=client,
                retries=args.retries,
            )
            all_paragraphs = parse_jats_paragraphs(article.document_id, payload)
            paragraphs = protocol_paragraphs(all_paragraphs)
            facts = extract_literature_facts(all_paragraphs)
            pdb_ids = sorted(
                {
                    str(fact.value)
                    for fact in facts
                    if fact.field == "starting_pdb_id"
                }
            )
            records.append(
                {
                    "document_id": article.document_id,
                    "split": article.split,
                    "source_uri": article.source_uri,
                    "full_text_sha256": hashlib.sha256(payload).hexdigest(),
                    "size_bytes": len(payload),
                    "cache_hit": cache_hit,
                    "protocol_paragraph_count": len(paragraphs),
                    "max_protocol_paragraph_chars": max(
                        (len(paragraph.text) for paragraph in paragraphs),
                        default=0,
                    ),
                    "explicit_pdb_ids": pdb_ids,
                }
            )
    core = {
        "schema_version": "mdmeta.frozen-jats-stage.v1",
        "generated_at": _utc_now(),
        "source_manifest_sha256": source_payload["manifest_sha256"],
        "source_manifest_article_count": len(all_articles),
        "selected_article_count": len(articles),
        "selected_split_counts": dict(sorted(Counter(item.split for item in articles).items())),
        "cache_hit_count": sum(record["cache_hit"] for record in records),
        "downloaded_count": sum(not record["cache_hit"] for record in records),
        "total_size_bytes": sum(record["size_bytes"] for record in records),
        "protocol_paragraph_count": sum(
            record["protocol_paragraph_count"] for record in records
        ),
        "max_protocol_paragraph_chars": max(
            record["max_protocol_paragraph_chars"] for record in records
        ),
        "article_count_with_explicit_pdb": sum(
            bool(record["explicit_pdb_ids"]) for record in records
        ),
        "all_frozen_sha256_matched": True,
        "cache_path_recorded": False,
        "records": records,
    }
    result = {**core, "manifest_sha256": canonical_sha256(core)}
    atomic_write_json(args.output, result)
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "selected_article_count",
                    "cache_hit_count",
                    "downloaded_count",
                    "total_size_bytes",
                    "protocol_paragraph_count",
                    "max_protocol_paragraph_chars",
                    "article_count_with_explicit_pdb",
                    "all_frozen_sha256_matched",
                    "manifest_sha256",
                )
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
