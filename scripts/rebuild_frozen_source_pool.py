#!/usr/bin/env python3
"""Rebuild one frozen 60-article corpus from a complete current-source audit."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mdmeta.benchmark import canonical_sha256
from mdmeta.llm_batch import atomic_write_json, validate_sha256, validate_source_manifest
from scripts.audit_frozen_source_pool import (
    _validate_inputs,
    validate_audit_cache,
    validate_audit_report,
)
from scripts.substitute_frozen_article import (
    MANIFEST_SCHEMA_VERSION as SUPERSEDED_MANIFEST_SCHEMA_VERSION,
    REPORT_SCHEMA_VERSION as SUPERSEDED_REPORT_SCHEMA_VERSION,
    RESERVE_REASON,
    SUBSTITUTION_REASON,
    _load_expected_json,
    _source_uri,
)


MANIFEST_SCHEMA_VERSION = "mdmeta.frozen-source-multi-rebuild.v1"
REPORT_SCHEMA_VERSION = "mdmeta.frozen-source-multi-rebuild-report.v1"
REBUILD_POLICY = "all_drifted_positions_to_first_n_currently_valid_original_reserves.v1"
REBUILD_GENERATION = 1
STUDY_STATUS = "provisional_operational_multi_rebuild_not_accuracy"
_COMMIT = re.compile(r"[0-9a-f]{40}")

_MANIFEST_KEYS = {
    "accepted_audit_file_sha256",
    "accepted_audit_sha256",
    "articles",
    "audit_job_id",
    "decision_key_sha256",
    "failed_stage_job_ids",
    "fulltext_screen_file_sha256",
    "fulltext_screen_sha256",
    "generated_at",
    "invariants",
    "manifest_sha256",
    "model_output_used_for_rebuild",
    "plan_sha256",
    "provisional_plan_file_sha256",
    "provisional_plan_sha256",
    "rebuild_generation",
    "rebuild_job_id",
    "rebuild_policy",
    "rebuild_source_archive_sha256",
    "rebuild_source_commit",
    "replacement_count",
    "replacements",
    "schema_version",
    "selection_parent_manifest_file_sha256",
    "selection_parent_manifest_sha256",
    "source_screen_sha256",
    "source_workflow_artifact_digest",
    "source_workflow_artifact_id",
    "source_workflow_run",
    "study_id",
    "study_status",
    "superseded_remediations",
    "unchanged_article_count",
}
_PASS_REPORT_KEYS = {
    "accepted_audit_file_sha256",
    "accepted_audit_sha256",
    "audit_job_id",
    "decision_key_sha256",
    "failed_stage_job_ids",
    "full_text_included",
    "fulltext_screen_file_sha256",
    "fulltext_screen_sha256",
    "generated_at",
    "invariants",
    "model_output_used",
    "new_manifest_sha256",
    "output_manifest_created",
    "private_paths_recorded",
    "provisional_plan_file_sha256",
    "provisional_plan_sha256",
    "rebuild_generation",
    "rebuild_job_id",
    "rebuild_policy",
    "replacement_count",
    "replacements",
    "report_sha256",
    "schema_version",
    "selection_parent_manifest_file_sha256",
    "selection_parent_manifest_sha256",
    "source_archive_sha256",
    "source_commit",
    "source_workflow_artifact_digest",
    "source_workflow_artifact_id",
    "source_workflow_run",
    "status",
    "study_id",
    "superseded_remediations",
    "unchanged_article_count",
}
_BLOCKED_REPORT_KEYS = {
    "accepted_audit_file_sha256",
    "accepted_audit_sha256",
    "audit_job_id",
    "available_valid_reserve_ranks",
    "decision_key_sha256",
    "drifted_positions",
    "failed_stage_job_ids",
    "full_text_included",
    "fulltext_screen_file_sha256",
    "fulltext_screen_sha256",
    "generated_at",
    "model_output_used",
    "output_manifest_created",
    "private_paths_recorded",
    "provisional_plan_file_sha256",
    "provisional_plan_sha256",
    "rebuild_generation",
    "rebuild_job_id",
    "rebuild_policy",
    "replacement_required_count",
    "report_sha256",
    "reserve_deficit",
    "schema_version",
    "selection_parent_manifest_file_sha256",
    "selection_parent_manifest_sha256",
    "source_archive_sha256",
    "source_commit",
    "source_workflow_artifact_digest",
    "source_workflow_artifact_id",
    "source_workflow_run",
    "status",
    "study_id",
    "superseded_remediations",
    "valid_reserve_count",
}
_REPLACEMENT_KEYS = {"new", "old", "position", "split"}
_REPLACEMENT_OLD_KEYS = {
    "classification",
    "document_id",
    "frozen_full_text_sha256",
    "frozen_size_bytes",
    "observed_current_full_text_sha256",
    "observed_current_size_bytes",
}
_REPLACEMENT_NEW_KEYS = {
    "classification",
    "document_id",
    "full_text_sha256",
    "original_reserve_rank",
    "xml_size_bytes",
}
_SUPERSEDED_LINEAGE_KEYS = {
    "failed_stage_job_id",
    "manifest_file_sha256",
    "manifest_sha256",
    "status",
    "substitution_job_id",
    "substitution_report_file_sha256",
    "substitution_report_sha256",
}
_INVARIANT_KEYS = {
    "article_count",
    "first_n_currently_valid_original_reserves",
    "positions_preserved",
    "selection_parent_is_original_manifest",
    "split_counts",
    "unique_document_ids",
}
_ORIGINAL_MANIFEST_KEYS = {
    "articles",
    "manifest_sha256",
    "plan_sha256",
    "source_screen_sha256",
    "source_workflow_artifact_digest",
    "source_workflow_artifact_id",
    "source_workflow_run",
    "study_id",
    "study_status",
}
_SUPERSEDED_MANIFEST_KEYS = {
    "articles",
    "failed_stage_job_id",
    "fulltext_screen_file_sha256",
    "generated_at",
    "manifest_sha256",
    "model_output_used_for_substitution",
    "parent_manifest_file_sha256",
    "parent_manifest_sha256",
    "plan_sha256",
    "provisional_plan_file_sha256",
    "schema_version",
    "source_screen_sha256",
    "source_workflow_artifact_digest",
    "source_workflow_artifact_id",
    "source_workflow_run",
    "study_id",
    "study_status",
    "substitution_job_id",
    "substitution_new",
    "substitution_old",
    "substitution_policy",
    "substitution_reason",
    "unchanged_article_count_expected",
    "unchanged_article_count_observed",
}
_SUPERSEDED_REPORT_KEYS = {
    "article_count",
    "failed_stage_job_id",
    "full_text_included",
    "fulltext_screen_file_sha256",
    "fulltext_screen_sha256",
    "generated_at",
    "model_output_used",
    "new",
    "new_manifest_sha256",
    "old",
    "parent_manifest_file_sha256",
    "parent_manifest_sha256",
    "provisional_plan_file_sha256",
    "provisional_plan_sha256",
    "reason",
    "report_sha256",
    "schema_version",
    "selection_policy",
    "source_workflow_artifact_digest",
    "source_workflow_artifact_id",
    "source_workflow_run",
    "status",
    "substitution_job_id",
    "unchanged_article_count_expected",
    "unchanged_article_count_observed",
}
_SUBSTITUTION_OLD_KEYS = {
    "document_id",
    "frozen_full_text_sha256",
    "frozen_size_bytes",
    "observed_current_full_text_sha256",
    "observed_current_size_bytes",
    "position",
    "source_uri",
    "split",
}
_SUBSTITUTION_NEW_KEYS = {
    "document_id",
    "full_text_sha256",
    "original_plan_reserve_rank",
    "original_plan_reserve_reason",
    "position",
    "source_uri",
    "split",
    "xml_size_bytes",
}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _require_exact_keys(
    payload: dict[str, Any],
    expected: set[str],
    *,
    label: str,
) -> None:
    if not isinstance(payload, dict) or set(payload) != expected:
        missing = sorted(expected - set(payload)) if isinstance(payload, dict) else []
        extra = sorted(set(payload) - expected) if isinstance(payload, dict) else []
        raise ValueError(f"{label} fields are invalid (missing={missing}, extra={extra})")


def _validate_timestamp(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{field} must be an ISO-8601 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO-8601 UTC timestamp") from error
    if parsed.tzinfo != UTC:
        raise ValueError(f"{field} must be an ISO-8601 UTC timestamp")
    return value


def _decision_key(original_manifest_sha256: str, audit_sha256: str) -> str:
    return canonical_sha256(
        {
            "selection_parent_manifest_sha256": original_manifest_sha256,
            "accepted_audit_sha256": audit_sha256,
            "rebuild_policy": REBUILD_POLICY,
            "rebuild_generation": REBUILD_GENERATION,
        }
    )


def _validate_compact_structures(
    *,
    replacements: Any,
    superseded_remediations: Any,
    invariants: Any | None = None,
) -> None:
    if not isinstance(replacements, list):
        raise ValueError("rebuild replacements must be a list")
    for replacement in replacements:
        _require_exact_keys(replacement, _REPLACEMENT_KEYS, label="replacement")
        _require_exact_keys(
            replacement["old"],
            _REPLACEMENT_OLD_KEYS,
            label="replacement old row",
        )
        _require_exact_keys(
            replacement["new"],
            _REPLACEMENT_NEW_KEYS,
            label="replacement new row",
        )
    if not isinstance(superseded_remediations, list) or len(
        superseded_remediations
    ) != 1:
        raise ValueError("rebuild must contain exactly one superseded remediation")
    _require_exact_keys(
        superseded_remediations[0],
        _SUPERSEDED_LINEAGE_KEYS,
        label="superseded remediation",
    )
    if invariants is not None:
        _require_exact_keys(invariants, _INVARIANT_KEYS, label="rebuild invariants")


def _validate_job_lineage(
    failed_jobs: list[int],
    *,
    superseded_lineage: dict[str, Any],
    audit_job_id: int,
    rebuild_job_id: int,
) -> None:
    if len(failed_jobs) != 2:
        raise ValueError("rebuild requires the two ordered failed staging jobs")
    failed_old, failed_later = failed_jobs
    superseded_failed = superseded_lineage["failed_stage_job_id"]
    substitution_job = superseded_lineage["substitution_job_id"]
    if superseded_failed != failed_old:
        raise ValueError("first failed stage job differs from superseded remediation")
    if not (
        failed_old
        < substitution_job
        < failed_later
        < audit_job_id
        < rebuild_job_id
    ):
        raise ValueError("stage, substitution, audit and rebuild jobs are out of order")
    identities = [
        failed_old,
        substitution_job,
        failed_later,
        audit_job_id,
        rebuild_job_id,
    ]
    if len(identities) != len(set(identities)):
        raise ValueError("stage, substitution, audit and rebuild jobs must be distinct")


def _positive_int(value: Any, *, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _parse_failed_jobs(value: str | list[int]) -> list[int]:
    if isinstance(value, str):
        if not value or re.fullmatch(r"[1-9][0-9]*(,[1-9][0-9]*)*", value) is None:
            raise ValueError("failed stage job IDs must be ordered positive integers")
        jobs = [int(item) for item in value.split(",")]
    elif isinstance(value, list):
        jobs = list(value)
    else:
        raise ValueError("failed stage job IDs must be a list or CSV string")
    if not jobs or any(
        not isinstance(item, int) or isinstance(item, bool) or item < 1 for item in jobs
    ):
        raise ValueError("failed stage job IDs must be positive integers")
    if len(jobs) != len(set(jobs)):
        raise ValueError("failed stage job IDs must be unique")
    if jobs != sorted(jobs):
        raise ValueError("failed stage job IDs must be strictly increasing")
    return jobs


def _validate_self_commitment(
    payload: dict[str, Any],
    *,
    field: str,
    label: str,
) -> str:
    stored = payload.get(field)
    core = {key: value for key, value in payload.items() if key != field}
    if not isinstance(stored, str) or stored != canonical_sha256(core):
        raise ValueError(f"{label} commitment is invalid")
    return stored


def _validate_superseded_lineage(
    *,
    original: dict[str, Any],
    original_file_sha256: str,
    plan: dict[str, Any],
    plan_file_sha256: str,
    screen: dict[str, Any],
    screen_file_sha256: str,
    superseded: dict[str, Any],
    superseded_file_sha256: str,
    substitution_report: dict[str, Any],
    substitution_report_file_sha256: str,
) -> dict[str, Any]:
    _require_exact_keys(original, _ORIGINAL_MANIFEST_KEYS, label="original manifest")
    _require_exact_keys(
        superseded,
        _SUPERSEDED_MANIFEST_KEYS,
        label="superseded source manifest",
    )
    _require_exact_keys(
        substitution_report,
        _SUPERSEDED_REPORT_KEYS,
        label="superseded substitution report",
    )
    original_articles = validate_source_manifest(original)
    superseded_articles = validate_source_manifest(superseded)
    if len(original_articles) != 60 or len(superseded_articles) != 60:
        raise ValueError("source lineage manifests must each contain 60 articles")
    if superseded.get("parent_manifest_sha256") != original["manifest_sha256"]:
        raise ValueError("superseded manifest does not descend from the original manifest")
    screen_sha256 = canonical_sha256(screen)
    common_expected = {
        "study_id": original["study_id"],
        "plan_sha256": plan["plan_sha256"],
        "source_screen_sha256": screen_sha256,
        "source_workflow_run": original["source_workflow_run"],
        "source_workflow_artifact_id": original["source_workflow_artifact_id"],
        "source_workflow_artifact_digest": original[
            "source_workflow_artifact_digest"
        ],
        "parent_manifest_file_sha256": original_file_sha256,
        "provisional_plan_file_sha256": plan_file_sha256,
        "fulltext_screen_file_sha256": screen_file_sha256,
    }
    if any(superseded.get(key) != value for key, value in common_expected.items()):
        raise ValueError("superseded manifest frozen-input lineage is inconsistent")
    if superseded.get("study_status") != original.get("study_status"):
        raise ValueError("superseded manifest changed the original study status")
    if superseded.get("schema_version") != SUPERSEDED_MANIFEST_SCHEMA_VERSION:
        raise ValueError("superseded manifest schema is invalid")
    if superseded.get("substitution_reason") != SUBSTITUTION_REASON or superseded.get(
        "substitution_policy"
    ) != "first_original_plan_eligible_reserve_not_selected":
        raise ValueError("superseded manifest substitution policy is invalid")
    _validate_timestamp(superseded.get("generated_at"), field="superseded generated_at")
    if superseded.get("model_output_used_for_substitution") is not False:
        raise ValueError("superseded substitution used model output")
    if (
        superseded.get("unchanged_article_count_expected") != 59
        or superseded.get("unchanged_article_count_observed") != 59
    ):
        raise ValueError("superseded substitution did not preserve exactly 59 rows")
    failed_job_id = _positive_int(
        superseded.get("failed_stage_job_id"), field="superseded failed job"
    )
    substitution_job_id = _positive_int(
        superseded.get("substitution_job_id"),
        field="superseded substitution job",
    )
    if failed_job_id == substitution_job_id:
        raise ValueError("superseded failed and substitution jobs must be distinct")
    report_sha256 = _validate_self_commitment(
        substitution_report,
        field="report_sha256",
        label="superseded substitution report",
    )
    if substitution_report.get("status") != "pass":
        raise ValueError("superseded substitution report did not pass")
    if substitution_report.get("schema_version") != SUPERSEDED_REPORT_SCHEMA_VERSION:
        raise ValueError("superseded substitution report schema is invalid")
    if substitution_report.get("generated_at") != superseded.get("generated_at"):
        raise ValueError("superseded manifest and report timestamps differ")
    if substitution_report.get("new_manifest_sha256") != superseded["manifest_sha256"]:
        raise ValueError("superseded substitution report names a different manifest")
    if substitution_report.get("parent_manifest_sha256") != original["manifest_sha256"]:
        raise ValueError("superseded substitution report names a different parent")
    if substitution_report.get("model_output_used") is not False:
        raise ValueError("superseded substitution report used model output")
    if substitution_report.get("full_text_included") is not False:
        raise ValueError("superseded substitution report contains full text")
    report_expected = {
        "parent_manifest_file_sha256": original_file_sha256,
        "provisional_plan_sha256": plan["plan_sha256"],
        "provisional_plan_file_sha256": plan_file_sha256,
        "fulltext_screen_sha256": screen_sha256,
        "fulltext_screen_file_sha256": screen_file_sha256,
        "source_workflow_run": original["source_workflow_run"],
        "source_workflow_artifact_id": original["source_workflow_artifact_id"],
        "source_workflow_artifact_digest": original[
            "source_workflow_artifact_digest"
        ],
        "reason": SUBSTITUTION_REASON,
        "selection_policy": "first_original_plan_eligible_reserve_not_selected",
        "unchanged_article_count_expected": 59,
        "unchanged_article_count_observed": 59,
        "article_count": 60,
    }
    if any(
        substitution_report.get(key) != value
        for key, value in report_expected.items()
    ):
        raise ValueError("superseded substitution report frozen-input lineage is inconsistent")
    if (
        substitution_report.get("failed_stage_job_id")
        != superseded.get("failed_stage_job_id")
        or substitution_report.get("substitution_job_id")
        != superseded.get("substitution_job_id")
    ):
        raise ValueError("superseded substitution job lineage is inconsistent")
    differences = sum(
        before.model_dump(mode="json") != after.model_dump(mode="json")
        for before, after in zip(original_articles, superseded_articles, strict=True)
    )
    if differences != 1:
        raise ValueError("superseded manifest must differ from the original at one row")
    difference_index = next(
        index
        for index, (before, after) in enumerate(
            zip(original_articles, superseded_articles, strict=True)
        )
        if before.model_dump(mode="json") != after.model_dump(mode="json")
    )
    old = superseded.get("substitution_old")
    new = superseded.get("substitution_new")
    _require_exact_keys(old, _SUBSTITUTION_OLD_KEYS, label="superseded old row")
    _require_exact_keys(new, _SUBSTITUTION_NEW_KEYS, label="superseded new row")
    if substitution_report.get("old") != old or substitution_report.get("new") != new:
        raise ValueError("superseded manifest and report substitution rows differ")
    before = original_articles[difference_index].model_dump(mode="json")
    after = superseded_articles[difference_index].model_dump(mode="json")
    expected_old = {
        "document_id": before["document_id"],
        "position": difference_index + 1,
        "split": before["split"],
        "source_uri": before["source_uri"],
        "frozen_full_text_sha256": before["full_text_sha256"],
    }
    if any(old.get(key) != value for key, value in expected_old.items()):
        raise ValueError("superseded old-row metadata differs from the original row")
    screen_by_id = {
        row.get("document_id"): row
        for row in screen.get("records", [])
        if isinstance(row, dict)
    }
    old_screen = screen_by_id.get(before["document_id"])
    new_screen = screen_by_id.get(after["document_id"])
    if not isinstance(old_screen, dict) or not isinstance(new_screen, dict):
        raise ValueError("superseded rows are absent from the frozen screen")
    validate_sha256(
        old.get("observed_current_full_text_sha256"),
        field="superseded observed old JATS digest",
    )
    _positive_int(old.get("frozen_size_bytes"), field="superseded frozen old size")
    _positive_int(
        old.get("observed_current_size_bytes"),
        field="superseded observed old size",
    )
    if old["observed_current_full_text_sha256"] == old["frozen_full_text_sha256"]:
        raise ValueError("superseded old row does not record frozen-payload drift")
    if old["frozen_size_bytes"] != old_screen.get("xml_size_bytes"):
        raise ValueError("superseded old size differs from the frozen screen")
    expected_new = {
        "document_id": after["document_id"],
        "position": difference_index + 1,
        "split": after["split"],
        "source_uri": after["source_uri"],
        "full_text_sha256": after["full_text_sha256"],
        "original_plan_reserve_rank": 1,
        "original_plan_reserve_reason": RESERVE_REASON,
    }
    if any(new.get(key) != value for key, value in expected_new.items()):
        raise ValueError("superseded new-row metadata differs from the output row")
    _positive_int(new.get("xml_size_bytes"), field="superseded replacement XML size")
    if (
        new["full_text_sha256"] != new_screen.get("full_text_sha256")
        or new["xml_size_bytes"] != new_screen.get("xml_size_bytes")
    ):
        raise ValueError("superseded replacement differs from the frozen screen")
    eligible_reserves = [
        row
        for row in plan.get("rejected_or_reserve", [])
        if isinstance(row, dict) and row.get("reason") == RESERVE_REASON
    ]
    if not eligible_reserves or eligible_reserves[0].get("document_id") != new["document_id"]:
        raise ValueError("superseded row is not the first original eligible reserve")
    return {
        "manifest_sha256": superseded["manifest_sha256"],
        "manifest_file_sha256": superseded_file_sha256,
        "substitution_report_sha256": report_sha256,
        "substitution_report_file_sha256": substitution_report_file_sha256,
        "failed_stage_job_id": superseded["failed_stage_job_id"],
        "substitution_job_id": superseded["substitution_job_id"],
        "status": "superseded_by_complete_pool_rebuild",
    }


def _validate_audit_lineage(
    audit: dict[str, Any],
    *,
    original: dict[str, Any],
    original_file_sha256: str,
    plan: dict[str, Any],
    plan_file_sha256: str,
    screen: dict[str, Any],
    screen_file_sha256: str,
) -> None:
    expected = {
        "original_manifest_sha256": original["manifest_sha256"],
        "original_manifest_file_sha256": original_file_sha256,
        "provisional_plan_sha256": plan["plan_sha256"],
        "provisional_plan_file_sha256": plan_file_sha256,
        "fulltext_screen_sha256": canonical_sha256(screen),
        "fulltext_screen_file_sha256": screen_file_sha256,
        "source_workflow_run": original["source_workflow_run"],
        "source_workflow_artifact_id": original["source_workflow_artifact_id"],
        "source_workflow_artifact_digest": original[
            "source_workflow_artifact_digest"
        ],
    }
    if any(audit.get(key) != value for key, value in expected.items()):
        raise ValueError("accepted audit lineage differs from the original frozen inputs")


def _lineage_rows_match_audit(
    *,
    selected_rows: list[dict[str, Any]],
    reserve_rows: list[dict[str, Any]],
    audit: dict[str, Any],
) -> None:
    audited_selected = audit["selected"]
    audited_reserves = audit["eligible_reserves"]
    if len(audited_selected) != len(selected_rows) or len(audited_reserves) != len(
        reserve_rows
    ):
        raise ValueError("accepted audit does not cover the complete original source pool")
    for expected, observed in zip(selected_rows, audited_selected, strict=True):
        for field in (
            "document_id",
            "original_position",
            "split",
            "expected_full_text_sha256",
            "expected_size_bytes",
        ):
            if observed.get(field) != expected.get(field):
                raise ValueError("accepted audit selected order differs from the original pool")
    for expected, observed in zip(reserve_rows, audited_reserves, strict=True):
        for field in (
            "document_id",
            "original_reserve_rank",
            "expected_full_text_sha256",
            "expected_size_bytes",
        ):
            if observed.get(field) != expected.get(field):
                raise ValueError("accepted audit reserve order differs from the original pool")


def _validate_superseded_audit_evidence(
    *,
    superseded: dict[str, Any],
    audit: dict[str, Any],
) -> None:
    old = superseded["substitution_old"]
    new = superseded["substitution_new"]
    position = old["position"]
    if new["position"] != position:
        raise ValueError("superseded old and new positions differ")
    selected_row = audit["selected"][position - 1]
    expected_old = {
        "document_id": selected_row["document_id"],
        "frozen_full_text_sha256": selected_row["expected_full_text_sha256"],
        "frozen_size_bytes": selected_row["expected_size_bytes"],
        "observed_current_full_text_sha256": selected_row[
            "observed_full_text_sha256"
        ],
        "observed_current_size_bytes": selected_row["observed_size_bytes"],
    }
    if any(old.get(key) != value for key, value in expected_old.items()):
        raise ValueError("superseded old-row evidence differs from the complete audit")
    if (
        selected_row.get("replacement_required") is not True
        or selected_row.get("classification") != "frozen_payload_drift"
    ):
        raise ValueError("superseded old row is not an audited selected-source drift")
    reserve_rank = new["original_plan_reserve_rank"]
    reserve_row = audit["eligible_reserves"][reserve_rank - 1]
    expected_new = {
        "document_id": reserve_row["document_id"],
        "full_text_sha256": reserve_row["expected_full_text_sha256"],
        "xml_size_bytes": reserve_row["expected_size_bytes"],
    }
    if any(new.get(key) != value for key, value in expected_new.items()):
        raise ValueError("superseded replacement differs from the complete audit")


def _replacement_metadata(
    old: dict[str, Any],
    new: dict[str, Any],
) -> dict[str, Any]:
    return {
        "position": old["original_position"],
        "split": old["split"],
        "old": {
            "document_id": old["document_id"],
            "frozen_full_text_sha256": old["expected_full_text_sha256"],
            "frozen_size_bytes": old["expected_size_bytes"],
            "observed_current_full_text_sha256": old[
                "observed_full_text_sha256"
            ],
            "observed_current_size_bytes": old["observed_size_bytes"],
            "classification": old["classification"],
        },
        "new": {
            "document_id": new["document_id"],
            "original_reserve_rank": new["original_reserve_rank"],
            "full_text_sha256": new["expected_full_text_sha256"],
            "xml_size_bytes": new["expected_size_bytes"],
            "classification": new["classification"],
        },
    }


def _blocked_report(
    *,
    generated_at: str,
    source_commit: str,
    source_archive_sha256: str,
    rebuild_job_id: int,
    failed_stage_job_ids: list[int],
    audit: dict[str, Any],
    audit_file_sha256: str,
    original: dict[str, Any],
    original_file_sha256: str,
    plan: dict[str, Any],
    plan_file_sha256: str,
    screen: dict[str, Any],
    screen_file_sha256: str,
    superseded_lineage: dict[str, Any],
    drifted: list[dict[str, Any]],
    valid_reserves: list[dict[str, Any]],
) -> dict[str, Any]:
    decision_key = _decision_key(original["manifest_sha256"], audit["audit_sha256"])
    core = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "blocked_insufficient_valid_reserves",
        "generated_at": generated_at,
        "study_id": original["study_id"],
        "source_commit": source_commit,
        "source_archive_sha256": source_archive_sha256,
        "rebuild_job_id": rebuild_job_id,
        "failed_stage_job_ids": failed_stage_job_ids,
        "selection_parent_manifest_sha256": original["manifest_sha256"],
        "selection_parent_manifest_file_sha256": original_file_sha256,
        "provisional_plan_sha256": plan["plan_sha256"],
        "provisional_plan_file_sha256": plan_file_sha256,
        "fulltext_screen_sha256": canonical_sha256(screen),
        "fulltext_screen_file_sha256": screen_file_sha256,
        "source_workflow_run": original["source_workflow_run"],
        "source_workflow_artifact_id": original["source_workflow_artifact_id"],
        "source_workflow_artifact_digest": original[
            "source_workflow_artifact_digest"
        ],
        "superseded_remediations": [superseded_lineage],
        "accepted_audit_sha256": audit["audit_sha256"],
        "accepted_audit_file_sha256": audit_file_sha256,
        "audit_job_id": audit["audit_job_id"],
        "rebuild_policy": REBUILD_POLICY,
        "rebuild_generation": REBUILD_GENERATION,
        "decision_key_sha256": decision_key,
        "replacement_required_count": len(drifted),
        "drifted_positions": [row["original_position"] for row in drifted],
        "valid_reserve_count": len(valid_reserves),
        "available_valid_reserve_ranks": [
            row["original_reserve_rank"] for row in valid_reserves
        ],
        "reserve_deficit": len(drifted) - len(valid_reserves),
        "output_manifest_created": False,
        "model_output_used": False,
        "full_text_included": False,
        "private_paths_recorded": False,
    }
    return {**core, "report_sha256": canonical_sha256(core)}


def rebuild_frozen_source_pool(
    *,
    original_manifest_path: Path,
    expected_original_manifest_file_sha256: str,
    superseded_manifest_path: Path,
    expected_superseded_manifest_file_sha256: str,
    superseded_substitution_report_path: Path,
    expected_superseded_substitution_report_file_sha256: str,
    provisional_plan_path: Path,
    expected_plan_file_sha256: str,
    fulltext_screen_path: Path,
    expected_screen_file_sha256: str,
    accepted_audit_report_path: Path,
    expected_audit_report_file_sha256: str,
    matching_cache_dir: Path,
    diagnostic_dir: Path,
    source_commit: str,
    source_archive_sha256: str,
    failed_stage_job_ids: str | list[int],
    rebuild_job_id: int,
    generated_at: str | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Build a new manifest without network or model-dependent source selection."""

    if _COMMIT.fullmatch(source_commit) is None:
        raise ValueError("source_commit must be a full lowercase Git SHA-1")
    validate_sha256(source_archive_sha256, field="source archive digest")
    jobs = _parse_failed_jobs(failed_stage_job_ids)
    _positive_int(rebuild_job_id, field="rebuild_job_id")
    timestamp = generated_at or _utc_now()

    (
        original,
        original_file_sha256,
        plan,
        plan_file_sha256,
        screen,
        screen_file_sha256,
        selected_rows,
        reserve_rows,
    ) = _validate_inputs(
        parent_manifest_path=original_manifest_path,
        expected_parent_file_sha256=expected_original_manifest_file_sha256,
        provisional_plan_path=provisional_plan_path,
        expected_plan_file_sha256=expected_plan_file_sha256,
        fulltext_screen_path=fulltext_screen_path,
        expected_screen_file_sha256=expected_screen_file_sha256,
    )
    superseded, superseded_file_sha256 = _load_expected_json(
        superseded_manifest_path,
        expected_superseded_manifest_file_sha256,
        label="superseded one-row source manifest",
    )
    substitution_report, substitution_report_file_sha256 = _load_expected_json(
        superseded_substitution_report_path,
        expected_superseded_substitution_report_file_sha256,
        label="superseded substitution report",
    )
    superseded_lineage = _validate_superseded_lineage(
        original=original,
        original_file_sha256=original_file_sha256,
        plan=plan,
        plan_file_sha256=plan_file_sha256,
        screen=screen,
        screen_file_sha256=screen_file_sha256,
        superseded=superseded,
        superseded_file_sha256=superseded_file_sha256,
        substitution_report=substitution_report,
        substitution_report_file_sha256=substitution_report_file_sha256,
    )
    audit, audit_file_sha256 = _load_expected_json(
        accepted_audit_report_path,
        expected_audit_report_file_sha256,
        label="accepted source-pool audit report",
    )
    validate_audit_cache(
        audit,
        matching_cache_dir=matching_cache_dir,
        diagnostic_dir=diagnostic_dir,
        require_complete=True,
    )
    _validate_audit_lineage(
        audit,
        original=original,
        original_file_sha256=original_file_sha256,
        plan=plan,
        plan_file_sha256=plan_file_sha256,
        screen=screen,
        screen_file_sha256=screen_file_sha256,
    )
    _lineage_rows_match_audit(
        selected_rows=selected_rows,
        reserve_rows=reserve_rows,
        audit=audit,
    )
    _validate_superseded_audit_evidence(superseded=superseded, audit=audit)
    drifted = sorted(
        (row for row in audit["selected"] if row["replacement_required"] is True),
        key=lambda row: row["original_position"],
    )
    valid_reserves = [
        row for row in audit["eligible_reserves"] if row["currently_valid"] is True
    ]
    _validate_job_lineage(
        jobs,
        superseded_lineage=superseded_lineage,
        audit_job_id=audit["audit_job_id"],
        rebuild_job_id=rebuild_job_id,
    )
    if not drifted:
        raise ValueError("accepted audit requires no source-pool rebuild")
    if len(valid_reserves) < len(drifted):
        blocked_report = _blocked_report(
            generated_at=timestamp,
            source_commit=source_commit,
            source_archive_sha256=source_archive_sha256,
            rebuild_job_id=rebuild_job_id,
            failed_stage_job_ids=jobs,
            audit=audit,
            audit_file_sha256=audit_file_sha256,
            original=original,
            original_file_sha256=original_file_sha256,
            plan=plan,
            plan_file_sha256=plan_file_sha256,
            screen=screen,
            screen_file_sha256=screen_file_sha256,
            superseded_lineage=superseded_lineage,
            drifted=drifted,
            valid_reserves=valid_reserves,
        )
        validate_blocked_rebuild_report(
            blocked_report,
            accepted_audit=audit,
            accepted_audit_file_sha256=audit_file_sha256,
            original=original,
            original_file_sha256=original_file_sha256,
            plan=plan,
            plan_file_sha256=plan_file_sha256,
            screen=screen,
            screen_file_sha256=screen_file_sha256,
            superseded_lineage=superseded_lineage,
        )
        return None, blocked_report

    chosen_reserves = valid_reserves[: len(drifted)]
    replacements = [
        _replacement_metadata(old, new)
        for old, new in zip(drifted, chosen_reserves, strict=True)
    ]
    original_articles = [
        article.model_dump(mode="json") for article in validate_source_manifest(original)
    ]
    new_articles = [dict(row) for row in original_articles]
    for old, new in zip(drifted, chosen_reserves, strict=True):
        index = old["original_position"] - 1
        new_articles[index] = {
            "document_id": new["document_id"],
            "split": old["split"],
            "source_uri": _source_uri(new["document_id"]),
            "full_text_sha256": new["expected_full_text_sha256"],
        }
    identifiers = [row["document_id"] for row in new_articles]
    split_counts = dict(sorted(Counter(row["split"] for row in new_articles).items()))
    unchanged_count = sum(
        before == after
        for before, after in zip(original_articles, new_articles, strict=True)
    )
    expected_split_counts = {"development": 30, "locked_test": 20, "validation": 10}
    if (
        len(new_articles) != 60
        or len(set(identifiers)) != 60
        or split_counts != expected_split_counts
        or unchanged_count != 60 - len(replacements)
    ):
        raise ValueError("multi-source rebuild invariants failed")

    decision_key = _decision_key(original["manifest_sha256"], audit["audit_sha256"])
    invariants = {
        "article_count": 60,
        "unique_document_ids": True,
        "split_counts": split_counts,
        "positions_preserved": True,
        "first_n_currently_valid_original_reserves": True,
        "selection_parent_is_original_manifest": True,
    }
    manifest_core = {
        "study_id": original["study_id"],
        "plan_sha256": original["plan_sha256"],
        "source_screen_sha256": original["source_screen_sha256"],
        "source_workflow_run": original["source_workflow_run"],
        "source_workflow_artifact_id": original["source_workflow_artifact_id"],
        "source_workflow_artifact_digest": original[
            "source_workflow_artifact_digest"
        ],
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "study_status": STUDY_STATUS,
        "generated_at": timestamp,
        "selection_parent_manifest_sha256": original["manifest_sha256"],
        "selection_parent_manifest_file_sha256": original_file_sha256,
        "provisional_plan_sha256": plan["plan_sha256"],
        "provisional_plan_file_sha256": plan_file_sha256,
        "fulltext_screen_sha256": canonical_sha256(screen),
        "fulltext_screen_file_sha256": screen_file_sha256,
        "superseded_remediations": [superseded_lineage],
        "accepted_audit_sha256": audit["audit_sha256"],
        "accepted_audit_file_sha256": audit_file_sha256,
        "audit_job_id": audit["audit_job_id"],
        "failed_stage_job_ids": jobs,
        "rebuild_job_id": rebuild_job_id,
        "rebuild_source_commit": source_commit,
        "rebuild_source_archive_sha256": source_archive_sha256,
        "rebuild_policy": REBUILD_POLICY,
        "rebuild_generation": REBUILD_GENERATION,
        "decision_key_sha256": decision_key,
        "model_output_used_for_rebuild": False,
        "replacement_count": len(replacements),
        "unchanged_article_count": unchanged_count,
        "replacements": replacements,
        "invariants": invariants,
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
        "study_id": original["study_id"],
        "source_commit": source_commit,
        "source_archive_sha256": source_archive_sha256,
        "rebuild_job_id": rebuild_job_id,
        "failed_stage_job_ids": jobs,
        "selection_parent_manifest_sha256": original["manifest_sha256"],
        "selection_parent_manifest_file_sha256": original_file_sha256,
        "provisional_plan_sha256": plan["plan_sha256"],
        "provisional_plan_file_sha256": plan_file_sha256,
        "fulltext_screen_sha256": canonical_sha256(screen),
        "fulltext_screen_file_sha256": screen_file_sha256,
        "source_workflow_run": original["source_workflow_run"],
        "source_workflow_artifact_id": original["source_workflow_artifact_id"],
        "source_workflow_artifact_digest": original[
            "source_workflow_artifact_digest"
        ],
        "superseded_remediations": [superseded_lineage],
        "accepted_audit_sha256": audit["audit_sha256"],
        "accepted_audit_file_sha256": audit_file_sha256,
        "audit_job_id": audit["audit_job_id"],
        "new_manifest_sha256": manifest["manifest_sha256"],
        "rebuild_policy": REBUILD_POLICY,
        "rebuild_generation": REBUILD_GENERATION,
        "decision_key_sha256": decision_key,
        "replacement_count": len(replacements),
        "unchanged_article_count": unchanged_count,
        "replacements": replacements,
        "invariants": invariants,
        "output_manifest_created": True,
        "model_output_used": False,
        "full_text_included": False,
        "private_paths_recorded": False,
    }
    report = {**report_core, "report_sha256": canonical_sha256(report_core)}
    validate_rebuild_outputs(
        manifest,
        report,
        audit,
        original_manifest_path=original_manifest_path,
        expected_original_manifest_file_sha256=(
            expected_original_manifest_file_sha256
        ),
        superseded_manifest_path=superseded_manifest_path,
        expected_superseded_manifest_file_sha256=(
            expected_superseded_manifest_file_sha256
        ),
        superseded_substitution_report_path=superseded_substitution_report_path,
        expected_superseded_substitution_report_file_sha256=(
            expected_superseded_substitution_report_file_sha256
        ),
        provisional_plan_path=provisional_plan_path,
        expected_plan_file_sha256=expected_plan_file_sha256,
        fulltext_screen_path=fulltext_screen_path,
        expected_screen_file_sha256=expected_screen_file_sha256,
        accepted_audit_report_path=accepted_audit_report_path,
        expected_audit_report_file_sha256=expected_audit_report_file_sha256,
        matching_cache_dir=matching_cache_dir,
        diagnostic_dir=diagnostic_dir,
    )
    return manifest, report


def validate_rebuild_outputs(
    manifest: dict[str, Any],
    report: dict[str, Any],
    accepted_audit: dict[str, Any],
    *,
    original_manifest_path: Path,
    expected_original_manifest_file_sha256: str,
    superseded_manifest_path: Path,
    expected_superseded_manifest_file_sha256: str,
    superseded_substitution_report_path: Path,
    expected_superseded_substitution_report_file_sha256: str,
    provisional_plan_path: Path,
    expected_plan_file_sha256: str,
    fulltext_screen_path: Path,
    expected_screen_file_sha256: str,
    accepted_audit_report_path: Path,
    expected_audit_report_file_sha256: str,
    matching_cache_dir: Path,
    diagnostic_dir: Path,
) -> None:
    """Verify pass outputs against every pinned lineage file and private source byte."""

    (
        original,
        original_file_sha256,
        plan,
        plan_file_sha256,
        screen,
        screen_file_sha256,
        selected_rows,
        reserve_rows,
    ) = _validate_inputs(
        parent_manifest_path=original_manifest_path,
        expected_parent_file_sha256=expected_original_manifest_file_sha256,
        provisional_plan_path=provisional_plan_path,
        expected_plan_file_sha256=expected_plan_file_sha256,
        fulltext_screen_path=fulltext_screen_path,
        expected_screen_file_sha256=expected_screen_file_sha256,
    )
    superseded, superseded_file_sha256 = _load_expected_json(
        superseded_manifest_path,
        expected_superseded_manifest_file_sha256,
        label="superseded one-row source manifest",
    )
    substitution_report, substitution_report_file_sha256 = _load_expected_json(
        superseded_substitution_report_path,
        expected_superseded_substitution_report_file_sha256,
        label="superseded substitution report",
    )
    expected_superseded_lineage = _validate_superseded_lineage(
        original=original,
        original_file_sha256=original_file_sha256,
        plan=plan,
        plan_file_sha256=plan_file_sha256,
        screen=screen,
        screen_file_sha256=screen_file_sha256,
        superseded=superseded,
        superseded_file_sha256=superseded_file_sha256,
        substitution_report=substitution_report,
        substitution_report_file_sha256=substitution_report_file_sha256,
    )
    disk_audit, audit_file_sha256 = _load_expected_json(
        accepted_audit_report_path,
        expected_audit_report_file_sha256,
        label="accepted source-pool audit report",
    )
    if disk_audit != accepted_audit:
        raise ValueError("accepted audit object differs from the pinned audit file")
    validate_audit_cache(
        disk_audit,
        matching_cache_dir=matching_cache_dir,
        diagnostic_dir=diagnostic_dir,
        require_complete=True,
    )
    _validate_audit_lineage(
        disk_audit,
        original=original,
        original_file_sha256=original_file_sha256,
        plan=plan,
        plan_file_sha256=plan_file_sha256,
        screen=screen,
        screen_file_sha256=screen_file_sha256,
    )
    _lineage_rows_match_audit(
        selected_rows=selected_rows,
        reserve_rows=reserve_rows,
        audit=disk_audit,
    )
    _validate_superseded_audit_evidence(
        superseded=superseded,
        audit=disk_audit,
    )

    _require_exact_keys(manifest, _MANIFEST_KEYS, label="rebuilt source manifest")
    _require_exact_keys(report, _PASS_REPORT_KEYS, label="source-pool rebuild report")
    articles = validate_source_manifest(manifest)
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ValueError("rebuilt source manifest schema is invalid")
    _validate_self_commitment(
        report,
        field="report_sha256",
        label="source-pool rebuild report",
    )
    if report.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise ValueError("source-pool rebuild report schema is invalid")
    if report.get("status") != "pass":
        raise ValueError("source-pool rebuild report did not pass")
    if manifest.get("study_status") != STUDY_STATUS:
        raise ValueError("rebuilt source manifest study status is invalid")
    generated_at = _validate_timestamp(
        manifest.get("generated_at"), field="rebuilt manifest generated_at"
    )
    if report.get("generated_at") != generated_at:
        raise ValueError("rebuilt manifest and report timestamps differ")
    if manifest.get("accepted_audit_sha256") != disk_audit.get("audit_sha256"):
        raise ValueError("rebuilt manifest names a different accepted audit")
    if report.get("accepted_audit_sha256") != disk_audit.get("audit_sha256"):
        raise ValueError("rebuild report names a different accepted audit")
    if (
        manifest.get("accepted_audit_file_sha256") != audit_file_sha256
        or report.get("accepted_audit_file_sha256") != audit_file_sha256
    ):
        raise ValueError("rebuild outputs name a different accepted audit file")
    if report.get("new_manifest_sha256") != manifest.get("manifest_sha256"):
        raise ValueError("rebuild report names a different output manifest")
    if manifest.get("rebuild_policy") != REBUILD_POLICY or report.get(
        "rebuild_policy"
    ) != REBUILD_POLICY:
        raise ValueError("source-pool rebuild policy is invalid")
    if manifest.get("audit_job_id") != disk_audit.get("audit_job_id") or report.get(
        "audit_job_id"
    ) != disk_audit.get("audit_job_id"):
        raise ValueError("source-pool rebuild audit job identity is inconsistent")
    decision_key = _decision_key(original["manifest_sha256"], disk_audit["audit_sha256"])
    if (
        manifest.get("rebuild_job_id") != report.get("rebuild_job_id")
        or manifest.get("accepted_audit_file_sha256")
        != report.get("accepted_audit_file_sha256")
        or manifest.get("rebuild_source_commit") != report.get("source_commit")
        or manifest.get("rebuild_source_archive_sha256")
        != report.get("source_archive_sha256")
        or manifest.get("failed_stage_job_ids") != report.get("failed_stage_job_ids")
        or manifest.get("superseded_remediations")
        != report.get("superseded_remediations")
        or manifest.get("rebuild_generation") != REBUILD_GENERATION
        or report.get("rebuild_generation") != REBUILD_GENERATION
        or manifest.get("decision_key_sha256") != decision_key
        or report.get("decision_key_sha256") != decision_key
    ):
        raise ValueError("source-pool rebuild execution lineage is inconsistent")
    expected_frozen_lineage = {
        "study_id": original["study_id"],
        "selection_parent_manifest_sha256": original["manifest_sha256"],
        "selection_parent_manifest_file_sha256": original_file_sha256,
        "provisional_plan_sha256": plan["plan_sha256"],
        "provisional_plan_file_sha256": plan_file_sha256,
        "fulltext_screen_sha256": canonical_sha256(screen),
        "fulltext_screen_file_sha256": screen_file_sha256,
        "source_workflow_run": original["source_workflow_run"],
        "source_workflow_artifact_id": original["source_workflow_artifact_id"],
        "source_workflow_artifact_digest": original[
            "source_workflow_artifact_digest"
        ],
    }
    if any(
        manifest.get(key) != value
        for key, value in {
            **expected_frozen_lineage,
            "plan_sha256": original["plan_sha256"],
            "source_screen_sha256": original["source_screen_sha256"],
        }.items()
    ) or any(
        report.get(key) != value for key, value in expected_frozen_lineage.items()
    ):
        raise ValueError("rebuild outputs differ from the pinned frozen-input lineage")
    if manifest.get("superseded_remediations") != [expected_superseded_lineage]:
        raise ValueError("rebuild outputs name a different superseded remediation")
    _validate_compact_structures(
        replacements=manifest.get("replacements"),
        superseded_remediations=manifest.get("superseded_remediations"),
        invariants=manifest.get("invariants"),
    )
    _validate_compact_structures(
        replacements=report.get("replacements"),
        superseded_remediations=report.get("superseded_remediations"),
        invariants=report.get("invariants"),
    )
    rebuild_job_id = _positive_int(report.get("rebuild_job_id"), field="rebuild_job_id")
    failed_jobs = _parse_failed_jobs(report.get("failed_stage_job_ids"))
    _validate_job_lineage(
        failed_jobs,
        superseded_lineage=expected_superseded_lineage,
        audit_job_id=disk_audit["audit_job_id"],
        rebuild_job_id=rebuild_job_id,
    )
    if _COMMIT.fullmatch(str(report.get("source_commit", ""))) is None:
        raise ValueError("source-pool rebuild source commit is invalid")
    validate_sha256(
        report.get("source_archive_sha256"),
        field="source-pool rebuild source archive digest",
    )
    if manifest.get("model_output_used_for_rebuild") is not False:
        raise ValueError("rebuilt source manifest used model output")
    if report.get("model_output_used") is not False:
        raise ValueError("source-pool rebuild report used model output")
    if report.get("full_text_included") is not False or report.get(
        "private_paths_recorded"
    ) is not False:
        raise ValueError("source-pool rebuild report leaks restricted source data")
    if report.get("output_manifest_created") is not True:
        raise ValueError("source-pool rebuild report did not create a manifest")
    if len(articles) != 60 or len({row.document_id for row in articles}) != 60:
        raise ValueError("rebuilt source manifest must contain 60 unique articles")
    split_counts = dict(sorted(Counter(row.split for row in articles).items()))
    if split_counts != {"development": 30, "locked_test": 20, "validation": 10}:
        raise ValueError("rebuilt source manifest split counts are invalid")

    drifted = sorted(
        (
            row
            for row in disk_audit["selected"]
            if row["replacement_required"] is True
        ),
        key=lambda row: row["original_position"],
    )
    valid_reserves = [
        row
        for row in disk_audit["eligible_reserves"]
        if row["currently_valid"] is True
    ]
    if len(valid_reserves) < len(drifted):
        raise ValueError("accepted audit has insufficient reserves for a completed rebuild")
    chosen = valid_reserves[: len(drifted)]
    expected_replacements = [
        _replacement_metadata(old, new)
        for old, new in zip(drifted, chosen, strict=True)
    ]
    if manifest.get("replacements") != expected_replacements or report.get(
        "replacements"
    ) != expected_replacements:
        raise ValueError("rebuild replacements are not the deterministic first-N mapping")
    if manifest.get("replacement_count") != len(drifted) or report.get(
        "replacement_count"
    ) != len(drifted):
        raise ValueError("rebuild replacement count is inconsistent")
    if manifest.get("unchanged_article_count") != 60 - len(drifted) or report.get(
        "unchanged_article_count"
    ) != 60 - len(drifted):
        raise ValueError("rebuild unchanged count is inconsistent")

    replacement_by_position = {
        old["original_position"]: new
        for old, new in zip(drifted, chosen, strict=True)
    }
    for position, (article, original_row) in enumerate(
        zip(articles, disk_audit["selected"], strict=True),
        start=1,
    ):
        replacement = replacement_by_position.get(position)
        if replacement is None:
            expected = {
                "document_id": original_row["document_id"],
                "split": original_row["split"],
                "source_uri": _source_uri(original_row["document_id"]),
                "full_text_sha256": original_row["expected_full_text_sha256"],
            }
        else:
            expected = {
                "document_id": replacement["document_id"],
                "split": original_row["split"],
                "source_uri": _source_uri(replacement["document_id"]),
                "full_text_sha256": replacement["expected_full_text_sha256"],
            }
        if article.model_dump(mode="json") != expected:
            raise ValueError("rebuilt source row differs from deterministic audit mapping")
    expected_invariants = {
        "article_count": 60,
        "unique_document_ids": True,
        "split_counts": split_counts,
        "positions_preserved": True,
        "first_n_currently_valid_original_reserves": True,
        "selection_parent_is_original_manifest": True,
    }
    if manifest.get("invariants") != expected_invariants or report.get(
        "invariants"
    ) != expected_invariants:
        raise ValueError("rebuild invariant summaries differ")


def validate_blocked_rebuild_report(
    report: dict[str, Any],
    *,
    accepted_audit: dict[str, Any],
    accepted_audit_file_sha256: str,
    original: dict[str, Any],
    original_file_sha256: str,
    plan: dict[str, Any],
    plan_file_sha256: str,
    screen: dict[str, Any],
    screen_file_sha256: str,
    superseded_lineage: dict[str, Any],
) -> None:
    """Validate a report-only decision when the complete audit has too few reserves."""

    validate_audit_report(accepted_audit, require_complete=True)
    _require_exact_keys(report, _BLOCKED_REPORT_KEYS, label="blocked rebuild report")
    _validate_self_commitment(
        report,
        field="report_sha256",
        label="blocked rebuild report",
    )
    if (
        report.get("schema_version") != REPORT_SCHEMA_VERSION
        or report.get("status") != "blocked_insufficient_valid_reserves"
    ):
        raise ValueError("blocked rebuild report status or schema is invalid")
    _validate_timestamp(report.get("generated_at"), field="blocked report generated_at")
    if (
        report.get("output_manifest_created") is not False
        or report.get("model_output_used") is not False
        or report.get("full_text_included") is not False
        or report.get("private_paths_recorded") is not False
    ):
        raise ValueError("blocked rebuild report violates no-output or privacy invariants")
    expected_lineage = {
        "study_id": original["study_id"],
        "selection_parent_manifest_sha256": original["manifest_sha256"],
        "selection_parent_manifest_file_sha256": original_file_sha256,
        "provisional_plan_sha256": plan["plan_sha256"],
        "provisional_plan_file_sha256": plan_file_sha256,
        "fulltext_screen_sha256": canonical_sha256(screen),
        "fulltext_screen_file_sha256": screen_file_sha256,
        "source_workflow_run": original["source_workflow_run"],
        "source_workflow_artifact_id": original["source_workflow_artifact_id"],
        "source_workflow_artifact_digest": original[
            "source_workflow_artifact_digest"
        ],
        "accepted_audit_sha256": accepted_audit["audit_sha256"],
        "accepted_audit_file_sha256": accepted_audit_file_sha256,
        "audit_job_id": accepted_audit["audit_job_id"],
        "rebuild_policy": REBUILD_POLICY,
        "rebuild_generation": REBUILD_GENERATION,
        "decision_key_sha256": _decision_key(
            original["manifest_sha256"], accepted_audit["audit_sha256"]
        ),
        "superseded_remediations": [superseded_lineage],
    }
    if any(report.get(key) != value for key, value in expected_lineage.items()):
        raise ValueError("blocked rebuild report lineage is inconsistent")
    _validate_compact_structures(
        replacements=[],
        superseded_remediations=report.get("superseded_remediations"),
    )
    drifted = sorted(
        (
            row
            for row in accepted_audit["selected"]
            if row["replacement_required"] is True
        ),
        key=lambda row: row["original_position"],
    )
    valid_reserves = [
        row
        for row in accepted_audit["eligible_reserves"]
        if row["currently_valid"] is True
    ]
    if len(valid_reserves) >= len(drifted):
        raise ValueError("blocked rebuild report has sufficient reserves")
    expected_counts = {
        "replacement_required_count": len(drifted),
        "drifted_positions": [row["original_position"] for row in drifted],
        "valid_reserve_count": len(valid_reserves),
        "available_valid_reserve_ranks": [
            row["original_reserve_rank"] for row in valid_reserves
        ],
        "reserve_deficit": len(drifted) - len(valid_reserves),
    }
    if any(report.get(key) != value for key, value in expected_counts.items()):
        raise ValueError("blocked rebuild report counts are inconsistent")
    rebuild_job_id = _positive_int(report.get("rebuild_job_id"), field="rebuild_job_id")
    failed_jobs = _parse_failed_jobs(report.get("failed_stage_job_ids"))
    _validate_job_lineage(
        failed_jobs,
        superseded_lineage=superseded_lineage,
        audit_job_id=accepted_audit["audit_job_id"],
        rebuild_job_id=rebuild_job_id,
    )
    if _COMMIT.fullmatch(str(report.get("source_commit", ""))) is None:
        raise ValueError("blocked rebuild source commit is invalid")
    validate_sha256(
        report.get("source_archive_sha256"),
        field="blocked rebuild source archive digest",
    )


def validate_blocked_rebuild_report_files(
    report: dict[str, Any],
    *,
    original_manifest_path: Path,
    expected_original_manifest_file_sha256: str,
    superseded_manifest_path: Path,
    expected_superseded_manifest_file_sha256: str,
    superseded_substitution_report_path: Path,
    expected_superseded_substitution_report_file_sha256: str,
    provisional_plan_path: Path,
    expected_plan_file_sha256: str,
    fulltext_screen_path: Path,
    expected_screen_file_sha256: str,
    accepted_audit_report_path: Path,
    expected_audit_report_file_sha256: str,
    matching_cache_dir: Path,
    diagnostic_dir: Path,
) -> None:
    """Re-verify a report-only blocked decision after it has been written."""

    (
        original,
        original_file_sha256,
        plan,
        plan_file_sha256,
        screen,
        screen_file_sha256,
        selected_rows,
        reserve_rows,
    ) = _validate_inputs(
        parent_manifest_path=original_manifest_path,
        expected_parent_file_sha256=expected_original_manifest_file_sha256,
        provisional_plan_path=provisional_plan_path,
        expected_plan_file_sha256=expected_plan_file_sha256,
        fulltext_screen_path=fulltext_screen_path,
        expected_screen_file_sha256=expected_screen_file_sha256,
    )
    superseded, superseded_file_sha256 = _load_expected_json(
        superseded_manifest_path,
        expected_superseded_manifest_file_sha256,
        label="superseded one-row source manifest",
    )
    substitution_report, substitution_report_file_sha256 = _load_expected_json(
        superseded_substitution_report_path,
        expected_superseded_substitution_report_file_sha256,
        label="superseded substitution report",
    )
    superseded_lineage = _validate_superseded_lineage(
        original=original,
        original_file_sha256=original_file_sha256,
        plan=plan,
        plan_file_sha256=plan_file_sha256,
        screen=screen,
        screen_file_sha256=screen_file_sha256,
        superseded=superseded,
        superseded_file_sha256=superseded_file_sha256,
        substitution_report=substitution_report,
        substitution_report_file_sha256=substitution_report_file_sha256,
    )
    audit, audit_file_sha256 = _load_expected_json(
        accepted_audit_report_path,
        expected_audit_report_file_sha256,
        label="accepted source-pool audit report",
    )
    validate_audit_cache(
        audit,
        matching_cache_dir=matching_cache_dir,
        diagnostic_dir=diagnostic_dir,
        require_complete=True,
    )
    _validate_audit_lineage(
        audit,
        original=original,
        original_file_sha256=original_file_sha256,
        plan=plan,
        plan_file_sha256=plan_file_sha256,
        screen=screen,
        screen_file_sha256=screen_file_sha256,
    )
    _lineage_rows_match_audit(
        selected_rows=selected_rows,
        reserve_rows=reserve_rows,
        audit=audit,
    )
    _validate_superseded_audit_evidence(superseded=superseded, audit=audit)
    validate_blocked_rebuild_report(
        report,
        accepted_audit=audit,
        accepted_audit_file_sha256=audit_file_sha256,
        original=original,
        original_file_sha256=original_file_sha256,
        plan=plan,
        plan_file_sha256=plan_file_sha256,
        screen=screen,
        screen_file_sha256=screen_file_sha256,
        superseded_lineage=superseded_lineage,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-source-manifest", type=Path, required=True)
    parser.add_argument("--original-source-manifest-sha256", required=True)
    parser.add_argument("--superseded-source-manifest", type=Path, required=True)
    parser.add_argument("--superseded-source-manifest-sha256", required=True)
    parser.add_argument("--superseded-substitution-report", type=Path, required=True)
    parser.add_argument("--superseded-substitution-report-sha256", required=True)
    parser.add_argument("--provisional-plan", type=Path, required=True)
    parser.add_argument("--provisional-plan-sha256", required=True)
    parser.add_argument("--fulltext-screen", type=Path, required=True)
    parser.add_argument("--fulltext-screen-sha256", required=True)
    parser.add_argument("--accepted-audit-report", type=Path, required=True)
    parser.add_argument("--accepted-audit-report-sha256", required=True)
    parser.add_argument("--matching-cache-dir", type=Path, required=True)
    parser.add_argument("--diagnostic-dir", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-archive-sha256", required=True)
    parser.add_argument("--failed-stage-job-ids", required=True)
    parser.add_argument("--rebuild-job-id", type=int, required=True)
    parser.add_argument("--output-manifest", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    args = parser.parse_args()

    output_manifest = args.output_manifest.resolve()
    output_report = args.output_report.resolve()
    input_paths = {
        args.original_source_manifest.resolve(),
        args.superseded_source_manifest.resolve(),
        args.superseded_substitution_report.resolve(),
        args.provisional_plan.resolve(),
        args.fulltext_screen.resolve(),
        args.accepted_audit_report.resolve(),
    }
    if (
        output_manifest == output_report
        or output_manifest in input_paths
        or output_report in input_paths
        or output_manifest.exists()
        or output_report.exists()
        or output_manifest.is_symlink()
        or output_report.is_symlink()
    ):
        raise SystemExit("rebuild outputs must be new, distinct and separate from inputs")
    manifest, report = rebuild_frozen_source_pool(
        original_manifest_path=args.original_source_manifest,
        expected_original_manifest_file_sha256=args.original_source_manifest_sha256,
        superseded_manifest_path=args.superseded_source_manifest,
        expected_superseded_manifest_file_sha256=(
            args.superseded_source_manifest_sha256
        ),
        superseded_substitution_report_path=args.superseded_substitution_report,
        expected_superseded_substitution_report_file_sha256=(
            args.superseded_substitution_report_sha256
        ),
        provisional_plan_path=args.provisional_plan,
        expected_plan_file_sha256=args.provisional_plan_sha256,
        fulltext_screen_path=args.fulltext_screen,
        expected_screen_file_sha256=args.fulltext_screen_sha256,
        accepted_audit_report_path=args.accepted_audit_report,
        expected_audit_report_file_sha256=args.accepted_audit_report_sha256,
        matching_cache_dir=args.matching_cache_dir,
        diagnostic_dir=args.diagnostic_dir,
        source_commit=args.source_commit,
        source_archive_sha256=args.source_archive_sha256,
        failed_stage_job_ids=args.failed_stage_job_ids,
        rebuild_job_id=args.rebuild_job_id,
    )
    if manifest is None:
        atomic_write_json(output_report, report)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 3
    atomic_write_json(output_manifest, manifest)
    atomic_write_json(output_report, report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "new_manifest_sha256": manifest["manifest_sha256"],
                "report_sha256": report["report_sha256"],
                "replacement_count": report["replacement_count"],
                "unchanged_article_count": report["unchanged_article_count"],
                "audit_job_id": report["audit_job_id"],
                "rebuild_job_id": report["rebuild_job_id"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
