from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mdmeta.integration import parse_jats_paragraphs, protocol_paragraphs


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


def _article(value: str) -> tuple[str, Path]:
    document_id, separator, raw_path = value.partition("=")
    if not separator or not document_id or not raw_path:
        raise argparse.ArgumentTypeError("--article must use DOCUMENT_ID=XML_PATH")
    return document_id, Path(raw_path)


def _load_manifest(path: Path) -> list[tuple[str, Path]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: Any
    if isinstance(payload, dict):
        rows = payload.get("articles")
    else:
        rows = payload
    if not isinstance(rows, list):
        raise ValueError("input manifest must be a list or contain an articles list")

    output: list[tuple[str, Path]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"manifest article {index} must be an object")
        document_id = row.get("document_id")
        xml_path = row.get("xml_path")
        if not isinstance(document_id, str) or not document_id:
            raise ValueError(f"manifest article {index} requires document_id")
        if not isinstance(xml_path, str) or not xml_path:
            raise ValueError(f"manifest article {index} requires xml_path")
        candidate = Path(xml_path)
        if not candidate.is_absolute():
            candidate = path.parent / candidate
        output.append((document_id, candidate))
    return output


def run(
    articles: list[tuple[str, Path]],
    output_path: Path,
    manifest_path: Path,
    *,
    protocol_only: bool,
) -> dict[str, Any]:
    if not articles:
        raise ValueError("provide --input-manifest or at least one --article")
    seen_documents: set[str] = set()
    jsonl_rows: list[str] = []
    source_rows: list[dict[str, Any]] = []
    total_paragraphs = 0

    for document_id, xml_path in articles:
        if document_id in seen_documents:
            raise ValueError(f"duplicate document_id: {document_id}")
        seen_documents.add(document_id)
        source_bytes = xml_path.read_bytes()
        parsed = parse_jats_paragraphs(document_id, source_bytes)
        selected = protocol_paragraphs(parsed) if protocol_only else parsed
        for paragraph in selected:
            jsonl_rows.append(
                json.dumps(
                    {
                        "document_id": paragraph.document_id,
                        "section": paragraph.section,
                        "paragraph_id": paragraph.paragraph_id,
                        "text": paragraph.text,
                    },
                    sort_keys=True,
                )
            )
        source_rows.append(
            {
                "document_id": document_id,
                "xml_path": str(xml_path),
                "xml_sha256": hashlib.sha256(source_bytes).hexdigest(),
                "parsed_paragraph_count": len(parsed),
                "selected_paragraph_count": len(selected),
            }
        )
        total_paragraphs += len(selected)

    jsonl_content = "\n".join(jsonl_rows) + ("\n" if jsonl_rows else "")
    output_sha256 = hashlib.sha256(jsonl_content.encode("utf-8")).hexdigest()
    manifest = {
        "schema_version": "llm-paragraph-input-manifest-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "selection": "protocol_paragraphs_v1" if protocol_only else "all_body_paragraphs",
        "article_count": len(source_rows),
        "paragraph_count": total_paragraphs,
        "output_path": str(output_path),
        "output_sha256": output_sha256,
        "sources": source_rows,
    }
    _atomic_write(output_path, jsonl_content)
    _atomic_write(manifest_path, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a frozen JSONL paragraph set from local JATS XML for LLM extraction."
    )
    parser.add_argument("--input-manifest", type=Path)
    parser.add_argument("--article", action="append", type=_article, default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    parser.add_argument(
        "--all-paragraphs",
        action="store_true",
        help="Include all JATS body paragraphs instead of the frozen protocol selector.",
    )
    args = parser.parse_args()

    articles = list(args.article)
    if args.input_manifest is not None:
        articles.extend(_load_manifest(args.input_manifest))
    result = run(
        articles,
        args.output,
        args.manifest_output,
        protocol_only=not args.all_paragraphs,
    )
    print(
        json.dumps(
            {
                "articles": result["article_count"],
                "paragraphs": result["paragraph_count"],
                "output_sha256": result["output_sha256"],
                "output": str(args.output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
