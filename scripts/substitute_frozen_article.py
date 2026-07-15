#!/usr/bin/env python3
"""Replace one irrecoverably drifted frozen JATS source with the first eligible reserve."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from defusedxml.ElementTree import fromstring as safe_xml_fromstring

from mdmeta.benchmark import canonical_sha256
from mdmeta.llm_batch import atomic_write_json, validate_sha256, validate_source_manifest


SPLITS = ("development", "validation", "locked_test")
MANIFEST_SCHEMA_VERSION = "mdmeta.frozen-source-substitution.v1"
REPORT_SCHEMA_VERSION = "mdmeta.frozen-source-substitution-report.v1"
SUBSTITUTION_REASON = "frozen_jats_unrecoverable_sha256_drift"
RESERVE_REASON = "eligible_reserve_not_selected"
_DOCUMENT_ID = re.compile(r"PMC\d+")
_ARTIFACT_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_RESERVED_OUTPUT_KEYS = {
    "parent_manifest_sha256",
    "parent_manifest_file_sha256",
    "provisional_plan_file_sha256",
    "fulltext_screen_file_sha256",
    "substitution_reason",
    "substitution_policy",
    "substitution_old",
    "substitution_new",
    "model_output_used_for_substitution",
    "unchanged_article_count_expected",
    "unchanged_article_count_observed",
}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _load_expected_json(path: Path, expected_sha256: str, *, label: str) -> tuple[dict, str]:
    validate_sha256(expected_sha256, field=f"{label} file digest")
    payload_bytes = path.read_bytes()
    observed_sha256 = _sha256_bytes(payload_bytes)
    if observed_sha256 != expected_sha256:
        raise ValueError(f"{label} file SHA-256 differs from the expected digest")
    payload = json.loads(payload_bytes)
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload, observed_sha256


def _document_id(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or _DOCUMENT_ID.fullmatch(value) is None:
        raise ValueError(f"{field} must be an uppercase PMC identifier")
    return value


def _source_uri(document_id: str) -> str:
    return f"https://europepmc.org/articles/{document_id}"


def _plan_selected_rows(plan: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    selected: list[tuple[str, dict[str, Any]]] = []
    for split in SPLITS:
        rows = plan.get(split)
        if not isinstance(rows, list):
            raise ValueError(f"provisional plan split {split!r} must be a list")
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("provisional plan selected rows must be JSON objects")
            _document_id(row.get("document_id"), field="provisional plan document_id")
            selected.append((split, row))
    identifiers = [row["document_id"] for _, row in selected]
    if len(identifiers) != 60 or len(set(identifiers)) != 60:
        raise ValueError("provisional plan must contain exactly 60 unique selected articles")
    return selected


def _validate_plan_commitment(plan: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    selected = _plan_selected_rows(plan)
    rejected = plan.get("rejected_or_reserve")
    if not isinstance(rejected, list) or not all(isinstance(row, dict) for row in rejected):
        raise ValueError("provisional plan has no valid rejected-or-reserve list")
    required = (
        "study_id",
        "study_status",
        "source_pool_plan_sha256",
        "screen_sha256",
        "screening_scope",
    )
    if any(key not in plan for key in required):
        raise ValueError("provisional plan is missing commitment fields")
    core = {
        "study_id": plan["study_id"],
        "study_status": plan["study_status"],
        "source_pool_plan_sha256": plan["source_pool_plan_sha256"],
        "screen_sha256": plan["screen_sha256"],
        "screening_scope": plan["screening_scope"],
        **{
            split: [
                row["document_id"]
                for selected_split, row in selected
                if selected_split == split
            ]
            for split in SPLITS
        },
        "rejected_or_reserve": rejected,
    }
    if plan.get("plan_sha256") != canonical_sha256(core):
        raise ValueError("provisional plan commitment is invalid")
    return selected


def _screen_records(screen: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = screen.get("records")
    if not isinstance(rows, list) or not rows:
        raise ValueError("full-text screen has no records")
    records: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("full-text screen records must be JSON objects")
        identifier = _document_id(row.get("document_id"), field="screen document_id")
        if identifier in records:
            raise ValueError(f"full-text screen contains duplicate record: {identifier}")
        records[identifier] = row
    return records


def _workflow_identity(parent: dict[str, Any]) -> tuple[int, int, str]:
    run_id = parent.get("source_workflow_run")
    artifact_id = parent.get("source_workflow_artifact_id")
    artifact_digest = parent.get("source_workflow_artifact_digest")
    if (
        not isinstance(run_id, int)
        or isinstance(run_id, bool)
        or run_id < 1
        or not isinstance(artifact_id, int)
        or isinstance(artifact_id, bool)
        or artifact_id < 1
        or not isinstance(artifact_digest, str)
        or _ARTIFACT_DIGEST.fullmatch(artifact_digest) is None
    ):
        raise ValueError("parent manifest has no valid workflow run/artifact/digest identity")
    return run_id, artifact_id, artifact_digest


def _cached_xml(
    cache_dir: Path,
    document_id: str,
    *,
    role: str,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
) -> bytes:
    path = cache_dir / f"{document_id}.xml"
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{role} cached JATS is missing or is a symlink: {path.name}")
    payload = path.read_bytes()
    if expected_size is not None and len(payload) != expected_size:
        raise ValueError(f"cached {role} JATS size differs from the original screen")
    if expected_sha256 is not None and _sha256_bytes(payload) != expected_sha256:
        raise ValueError(f"cached {role} JATS SHA-256 differs from the original screen")
    root = safe_xml_fromstring(payload)
    observed_ids = {
        " ".join("".join(node.itertext()).split()).upper()
        for node in root.findall(".//article-id[@pub-id-type='pmcid']")
    }
    if document_id not in observed_ids:
        raise ValueError(f"{role} cached JATS does not declare PMCID {document_id}")
    return payload


def substitute_frozen_article(
    *,
    parent_manifest_path: Path,
    expected_parent_file_sha256: str,
    provisional_plan_path: Path,
    expected_plan_file_sha256: str,
    fulltext_screen_path: Path,
    expected_screen_file_sha256: str,
    jats_cache_dir: Path,
    replace_document_id: str,
    replacement_document_id: str,
    generated_at: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a one-source substitution manifest after strict offline provenance checks."""

    replace_document_id = _document_id(
        replace_document_id,
        field="replace_document_id",
    )
    replacement_document_id = _document_id(
        replacement_document_id,
        field="replacement_document_id",
    )
    if replace_document_id == replacement_document_id:
        raise ValueError("replacement article must differ from the replaced article")

    parent, parent_file_sha256 = _load_expected_json(
        parent_manifest_path,
        expected_parent_file_sha256,
        label="parent source manifest",
    )
    plan, plan_file_sha256 = _load_expected_json(
        provisional_plan_path,
        expected_plan_file_sha256,
        label="provisional plan artifact",
    )
    screen, screen_file_sha256 = _load_expected_json(
        fulltext_screen_path,
        expected_screen_file_sha256,
        label="full-text screen artifact",
    )
    if _RESERVED_OUTPUT_KEYS.intersection(parent):
        raise ValueError("parent source manifest already contains substitution metadata")
    parent_articles = validate_source_manifest(parent)
    if len(parent_articles) != 60:
        raise ValueError("parent source manifest must contain exactly 60 articles")
    run_id, artifact_id, artifact_digest = _workflow_identity(parent)
    selected_plan_rows = _validate_plan_commitment(plan)
    records = _screen_records(screen)

    screen_sha256 = canonical_sha256(screen)
    if plan.get("screen_sha256") != screen_sha256:
        raise ValueError("full-text screen commitment differs from the provisional plan")
    if parent.get("source_screen_sha256") != screen_sha256:
        raise ValueError("full-text screen commitment differs from the parent manifest")
    if parent.get("plan_sha256") != plan.get("plan_sha256"):
        raise ValueError("provisional plan commitment differs from the parent manifest")
    if screen.get("plan_sha256") != plan.get("source_pool_plan_sha256"):
        raise ValueError("full-text screen does not match the plan's original screening pool")

    parent_rows = [article.model_dump(mode="json") for article in parent_articles]
    parent_ids = [row["document_id"] for row in parent_rows]
    plan_ids = [row["document_id"] for _, row in selected_plan_rows]
    if parent_ids != plan_ids:
        raise ValueError("parent source order differs from the original provisional plan")
    for parent_row, (plan_split, plan_row) in zip(
        parent_rows,
        selected_plan_rows,
        strict=True,
    ):
        if parent_row["split"] != plan_split:
            raise ValueError("parent source split differs from the original provisional plan")
        if parent_row["source_uri"] != _source_uri(parent_row["document_id"]):
            raise ValueError("parent source URI does not follow the Europe PMC rule")
        if plan_row.get("source_uri") != parent_row["source_uri"]:
            raise ValueError("parent source URI differs from the original provisional plan")
        screen_row = records.get(parent_row["document_id"])
        if screen_row is None:
            raise ValueError("parent source article is absent from the full-text screen")
        if screen_row.get("machine_eligible_for_annotation") is not True:
            raise ValueError(
                "parent source article was not machine-eligible in the original screen"
            )
        if screen_row.get("full_text_sha256") != parent_row["full_text_sha256"]:
            raise ValueError("parent frozen JATS commitment differs from the original screen")

    if replace_document_id not in parent_ids:
        raise ValueError("article to replace is absent from the parent source manifest")
    reserves = [
        row
        for row in plan["rejected_or_reserve"]
        if row.get("reason") == RESERVE_REASON
    ]
    if not reserves:
        raise ValueError("original provisional plan contains no eligible reserve")
    first_reserve_id = _document_id(
        reserves[0].get("document_id"),
        field="first eligible reserve document_id",
    )
    if replacement_document_id != first_reserve_id:
        raise ValueError(
            "replacement must be the first eligible_reserve_not_selected article "
            f"({first_reserve_id})"
        )
    if replacement_document_id in parent_ids:
        raise ValueError("replacement reserve is already present in the parent manifest")

    replacement_screen = records.get(replacement_document_id)
    if replacement_screen is None:
        raise ValueError("replacement reserve is absent from the full-text screen")
    if replacement_screen.get("machine_eligible_for_annotation") is not True:
        raise ValueError("replacement reserve is not machine-eligible in the original screen")
    replacement_sha256 = replacement_screen.get("full_text_sha256")
    replacement_size = replacement_screen.get("xml_size_bytes")
    if not isinstance(replacement_sha256, str):
        raise ValueError("replacement screen record has no frozen JATS SHA-256")
    validate_sha256(replacement_sha256, field="replacement screen JATS digest")
    if (
        not isinstance(replacement_size, int)
        or isinstance(replacement_size, bool)
        or replacement_size < 1
    ):
        raise ValueError("replacement screen record has no valid XML size")

    replacement_xml = _cached_xml(
        jats_cache_dir,
        replacement_document_id,
        role="replacement",
        expected_size=replacement_size,
        expected_sha256=replacement_sha256,
    )

    replace_index = parent_ids.index(replace_document_id)
    old_row = parent_rows[replace_index]
    old_screen = records[replace_document_id]
    old_frozen_size = old_screen.get("xml_size_bytes")
    if (
        not isinstance(old_frozen_size, int)
        or isinstance(old_frozen_size, bool)
        or old_frozen_size < 1
    ):
        raise ValueError("replaced screen record has no valid original XML size")
    observed_old_xml = _cached_xml(jats_cache_dir, replace_document_id, role="replaced")
    observed_old_sha256 = _sha256_bytes(observed_old_xml)
    if observed_old_sha256 == old_row["full_text_sha256"]:
        raise ValueError("parent frozen source has not drifted and must not be substituted")

    new_row = {
        "document_id": replacement_document_id,
        "split": old_row["split"],
        "source_uri": _source_uri(replacement_document_id),
        "full_text_sha256": replacement_sha256,
    }
    new_articles = [dict(row) for row in parent_rows]
    new_articles[replace_index] = new_row
    new_ids = [row["document_id"] for row in new_articles]
    if len(new_ids) != 60 or len(set(new_ids)) != 60:
        raise ValueError("substitution did not preserve 60 unique source articles")
    unchanged_count = sum(
        before == after
        for before, after in zip(parent_rows, new_articles, strict=True)
    )
    if unchanged_count != 59:
        raise ValueError("substitution did not preserve exactly 59 parent source rows")

    timestamp = generated_at or _utc_now()
    old_metadata = {
        "document_id": old_row["document_id"],
        "position": replace_index + 1,
        "split": old_row["split"],
        "source_uri": old_row["source_uri"],
        "frozen_full_text_sha256": old_row["full_text_sha256"],
        "frozen_size_bytes": old_frozen_size,
        "observed_current_full_text_sha256": observed_old_sha256,
        "observed_current_size_bytes": len(observed_old_xml),
    }
    new_metadata = {
        "document_id": new_row["document_id"],
        "position": replace_index + 1,
        "split": new_row["split"],
        "source_uri": new_row["source_uri"],
        "full_text_sha256": new_row["full_text_sha256"],
        "xml_size_bytes": replacement_size,
        "original_plan_reserve_rank": 1,
        "original_plan_reserve_reason": RESERVE_REASON,
    }
    parent_core = {
        key: value
        for key, value in parent.items()
        if key not in {"manifest_sha256", "articles"}
    }
    manifest_core = {
        **parent_core,
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_at": timestamp,
        "parent_manifest_sha256": parent["manifest_sha256"],
        "parent_manifest_file_sha256": parent_file_sha256,
        "provisional_plan_file_sha256": plan_file_sha256,
        "fulltext_screen_file_sha256": screen_file_sha256,
        "substitution_reason": SUBSTITUTION_REASON,
        "substitution_policy": "first_original_plan_eligible_reserve_not_selected",
        "substitution_old": old_metadata,
        "substitution_new": new_metadata,
        "model_output_used_for_substitution": False,
        "unchanged_article_count_expected": 59,
        "unchanged_article_count_observed": unchanged_count,
        "articles": new_articles,
    }
    manifest = {
        **manifest_core,
        "manifest_sha256": canonical_sha256(manifest_core),
    }
    validate_source_manifest(manifest)

    report_core = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "pass",
        "generated_at": timestamp,
        "parent_manifest_sha256": parent["manifest_sha256"],
        "new_manifest_sha256": manifest["manifest_sha256"],
        "source_workflow_run": run_id,
        "source_workflow_artifact_id": artifact_id,
        "source_workflow_artifact_digest": artifact_digest,
        "parent_manifest_file_sha256": parent_file_sha256,
        "provisional_plan_sha256": plan["plan_sha256"],
        "provisional_plan_file_sha256": plan_file_sha256,
        "fulltext_screen_sha256": screen_sha256,
        "fulltext_screen_file_sha256": screen_file_sha256,
        "reason": SUBSTITUTION_REASON,
        "selection_policy": "first_original_plan_eligible_reserve_not_selected",
        "old": old_metadata,
        "new": new_metadata,
        "model_output_used": False,
        "unchanged_article_count_expected": 59,
        "unchanged_article_count_observed": unchanged_count,
        "article_count": len(new_articles),
        "full_text_included": False,
    }
    report = {**report_core, "report_sha256": canonical_sha256(report_core)}
    return manifest, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-source-manifest", type=Path, required=True)
    parser.add_argument("--parent-source-manifest-sha256", required=True)
    parser.add_argument("--provisional-plan", type=Path, required=True)
    parser.add_argument("--provisional-plan-sha256", required=True)
    parser.add_argument("--fulltext-screen", type=Path, required=True)
    parser.add_argument("--fulltext-screen-sha256", required=True)
    parser.add_argument("--jats-cache-dir", type=Path, required=True)
    parser.add_argument("--replace-document-id", required=True)
    parser.add_argument("--replacement-document-id", required=True)
    parser.add_argument("--output-manifest", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    args = parser.parse_args()

    input_paths = {
        args.parent_source_manifest.resolve(),
        args.provisional_plan.resolve(),
        args.fulltext_screen.resolve(),
    }
    output_paths = {args.output_manifest.resolve(), args.output_report.resolve()}
    if len(output_paths) != 2 or input_paths.intersection(output_paths):
        raise SystemExit("outputs must be distinct and must not overwrite input artifacts")
    manifest, report = substitute_frozen_article(
        parent_manifest_path=args.parent_source_manifest,
        expected_parent_file_sha256=args.parent_source_manifest_sha256,
        provisional_plan_path=args.provisional_plan,
        expected_plan_file_sha256=args.provisional_plan_sha256,
        fulltext_screen_path=args.fulltext_screen,
        expected_screen_file_sha256=args.fulltext_screen_sha256,
        jats_cache_dir=args.jats_cache_dir,
        replace_document_id=args.replace_document_id,
        replacement_document_id=args.replacement_document_id,
    )
    atomic_write_json(args.output_manifest, manifest)
    atomic_write_json(args.output_report, report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "parent_manifest_sha256": report["parent_manifest_sha256"],
                "new_manifest_sha256": report["new_manifest_sha256"],
                "old_document_id": report["old"]["document_id"],
                "new_document_id": report["new"]["document_id"],
                "unchanged_article_count": report["unchanged_article_count_observed"],
                "report_sha256": report["report_sha256"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
