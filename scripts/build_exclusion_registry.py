from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from mdmeta.benchmark import canonical_sha256

PMC_ID = re.compile(r"^PMC\d+$", re.IGNORECASE)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ids_from_json(value: Any) -> set[str]:
    identifiers: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"document_id", "pmcid"} and isinstance(child, str):
                candidate = child.strip().upper()
                if PMC_ID.fullmatch(candidate):
                    identifiers.add(candidate)
            identifiers.update(_ids_from_json(child))
    elif isinstance(value, list):
        for child in value:
            identifiers.update(_ids_from_json(child))
    return identifiers


def _ids_from_text(path: Path) -> set[str]:
    return {
        line.strip().upper()
        for line in path.read_text(encoding="utf-8").splitlines()
        if PMC_ID.fullmatch(line.strip())
    }


def build_registry(text_paths: list[Path], json_paths: list[Path]) -> dict:
    sources: list[dict] = []
    identifiers: set[str] = set()
    for source_type, paths in (("text", text_paths), ("json", json_paths)):
        for path in paths:
            source_ids = (
                _ids_from_text(path)
                if source_type == "text"
                else _ids_from_json(json.loads(path.read_text(encoding="utf-8")))
            )
            identifiers.update(source_ids)
            sources.append(
                {
                    "path": path.as_posix(),
                    "source_type": source_type,
                    "file_sha256": _file_sha256(path),
                    "unique_document_id_count": len(source_ids),
                    "document_ids": sorted(source_ids),
                }
            )
    sources.sort(key=lambda row: row["path"])
    core = {
        "schema_version": "mdmeta.independent-exclusions.v1",
        "policy": "exclude_every_known_prior_development_candidate_or_run_article",
        "source_count": len(sources),
        "unique_document_id_count": len(identifiers),
        "document_ids": sorted(identifiers),
        "sources": sources,
    }
    return {**core, "registry_sha256": canonical_sha256(core)}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a deterministic registry of prior PMC article identifiers."
    )
    parser.add_argument("--text", action="append", type=Path, default=[])
    parser.add_argument("--json", action="append", type=Path, default=[])
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-txt", type=Path, required=True)
    args = parser.parse_args()
    registry = build_registry(args.text, args.json)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_txt.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    args.output_txt.write_text(
        "\n".join(registry["document_ids"]) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "unique_document_id_count": registry["unique_document_id_count"],
                "registry_sha256": registry["registry_sha256"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
