from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from mdmeta.benchmark import canonical_sha256
from mdmeta.llm_batch import FULLTEXT_URL
from scripts.audit_frozen_source_pool import (
    AUDIT_POLICY_VERSION,
    SCHEMA_VERSION as AUDIT_SCHEMA_VERSION,
)
from scripts.rebuild_frozen_source_pool import (
    REBUILD_POLICY,
    STUDY_STATUS,
    main as rebuild_main,
    rebuild_frozen_source_pool,
    validate_blocked_rebuild_report_files,
    validate_rebuild_outputs,
)
from scripts.substitute_frozen_article import (
    MANIFEST_SCHEMA_VERSION as SUPERSEDED_MANIFEST_SCHEMA_VERSION,
    REPORT_SCHEMA_VERSION as SUPERSEDED_REPORT_SCHEMA_VERSION,
    RESERVE_REASON,
    SUBSTITUTION_REASON,
)


GENERATED_AT = "2026-07-15T20:00:00Z"
SOURCE_COMMIT = "a" * 40
SOURCE_ARCHIVE_SHA256 = "b" * 64
SPLITS = ("development", "validation", "locked_test")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _xml(document_id: str, body: str = "frozen fixture") -> bytes:
    return (
        "<article><front><article-meta>"
        f"<article-id pub-id-type='pmcid'>{document_id}</article-id>"
        "</article-meta></front><body><sec><title>Methods</title>"
        f"<p>{body}</p></sec></body></article>"
    ).encode()


def _source_uri(document_id: str) -> str:
    return f"https://europepmc.org/articles/{document_id}"


def _write_json(path: Path, payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, indent=2, sort_keys=True).encode()
    path.write_bytes(encoded)
    return _sha256(encoded)


def _recommit(payload: dict[str, Any], field: str) -> None:
    payload[field] = canonical_sha256(
        {key: value for key, value in payload.items() if key != field}
    )


def _plan_core(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "study_id": plan["study_id"],
        "study_status": plan["study_status"],
        "source_pool_plan_sha256": plan["source_pool_plan_sha256"],
        "screen_sha256": plan["screen_sha256"],
        "screening_scope": plan["screening_scope"],
        **{
            split: [row["document_id"] for row in plan[split]]
            for split in SPLITS
        },
        "rejected_or_reserve": plan["rejected_or_reserve"],
    }


def _exact_record(row: dict[str, Any], payload: bytes) -> dict[str, Any]:
    return {
        **row,
        "retrieval_status": "retrieved",
        "attempts": 1,
        "http_status": 200,
        "error_code": None,
        "observed_full_text_sha256": _sha256(payload),
        "observed_size_bytes": len(payload),
        "pmcid_identity_valid": True,
        "frozen_payload_match": True,
        "cache_bucket": "matching_cache",
        "classification": "current_exact_match",
        "replacement_required": False,
        "currently_valid": True,
    }


def _diagnostic_record(
    row: dict[str, Any],
    payload: bytes,
    *,
    identity_valid: bool,
) -> dict[str, Any]:
    return {
        **row,
        "retrieval_status": "retrieved",
        "attempts": 1,
        "http_status": 200,
        "error_code": None,
        "observed_full_text_sha256": _sha256(payload),
        "observed_size_bytes": len(payload),
        "pmcid_identity_valid": identity_valid,
        "frozen_payload_match": False,
        "cache_bucket": "diagnostic",
        "classification": (
            "frozen_payload_drift" if identity_valid else "invalid_pmcid_identity"
        ),
        "replacement_required": row["pool_role"] == "selected",
        "currently_valid": False,
    }


def _unavailable_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **row,
        "retrieval_status": "definitive_unavailable",
        "attempts": 1,
        "http_status": 404,
        "error_code": "http_404",
        "observed_full_text_sha256": None,
        "observed_size_bytes": None,
        "pmcid_identity_valid": None,
        "frozen_payload_match": False,
        "cache_bucket": None,
        "classification": "definitive_unavailable",
        "replacement_required": row["pool_role"] == "selected",
        "currently_valid": False,
    }


def _audit_report(
    *,
    original: dict[str, Any],
    original_file_sha256: str,
    plan: dict[str, Any],
    plan_file_sha256: str,
    screen: dict[str, Any],
    screen_file_sha256: str,
    selected: list[dict[str, Any]],
    reserves: list[dict[str, Any]],
) -> dict[str, Any]:
    records = [*selected, *reserves]
    selected_ids = [row["document_id"] for row in selected]
    reserve_ids = [row["document_id"] for row in reserves]
    audit_spec_core = {
        "policy_version": AUDIT_POLICY_VERSION,
        "endpoint_template": FULLTEXT_URL,
        "timeout_seconds": 10.0,
        "retries_after_first_attempt": 0,
        "retryable_http_statuses": [429, 500, 502, 503, 504],
        "definitive_unavailable_http_statuses": [404, 410],
        "http_user_agent": "mdmeta-rebuild-test/1",
        "selected_count_expected": 60,
        "eligible_reserve_count_expected": len(reserves),
        "ordered_selected_ids_sha256": canonical_sha256(selected_ids),
        "ordered_reserve_ids_sha256": canonical_sha256(reserve_ids),
    }
    audit_spec = {
        **audit_spec_core,
        "audit_spec_sha256": canonical_sha256(audit_spec_core),
    }
    inventory = [
        {
            "document_id": row["document_id"],
            "cache_bucket": row["cache_bucket"],
            "observed_full_text_sha256": row["observed_full_text_sha256"],
            "observed_size_bytes": row["observed_size_bytes"],
        }
        for row in records
        if row["cache_bucket"] is not None
    ]
    replacement_count = sum(
        row["replacement_required"] is True for row in selected
    )
    valid_reserve_count = sum(row["currently_valid"] is True for row in reserves)
    matching_count = sum(row["cache_bucket"] == "matching_cache" for row in records)
    diagnostic_count = sum(row["cache_bucket"] == "diagnostic" for row in records)
    core = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "status": "complete",
        "generated_at": GENERATED_AT,
        "audit_job_id": 185800,
        "source_commit": SOURCE_COMMIT,
        "source_archive_sha256": SOURCE_ARCHIVE_SHA256,
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
        "audit_spec": audit_spec,
        "model_output_used": False,
        "full_text_included": False,
        "private_paths_recorded": False,
        "selected": selected,
        "eligible_reserves": reserves,
        "summary": {
            "selected_count": 60,
            "eligible_reserve_count": len(reserves),
            "audited_record_count": len(records),
            "selected_split_counts": {
                "development": 30,
                "locked_test": 20,
                "validation": 10,
            },
            "selected_replacement_required_count": replacement_count,
            "selected_exact_match_count": 60 - replacement_count,
            "valid_reserve_count": valid_reserve_count,
            "unresolved_count": 0,
            "matching_cache_file_count": matching_count,
            "diagnostic_file_count": diagnostic_count,
            "sufficient_valid_reserves": valid_reserve_count >= replacement_count,
        },
        "cache_inventory_sha256": canonical_sha256(inventory),
    }
    return {**core, "audit_sha256": canonical_sha256(core)}


def _fixture(
    tmp_path: Path,
    *,
    valid_reserve_ranks: tuple[int, ...] = (2, 3, 4),
) -> dict[str, Any]:
    selected_ids = [f"PMC{index:06d}" for index in range(1, 61)]
    reserve_ids = [f"PMC{index:06d}" for index in range(61, 65)]
    all_ids = [*selected_ids, *reserve_ids]
    frozen = {document_id: _xml(document_id) for document_id in all_ids}
    split_by_id = {
        **{document_id: "development" for document_id in selected_ids[:30]},
        **{document_id: "validation" for document_id in selected_ids[30:40]},
        **{document_id: "locked_test" for document_id in selected_ids[40:]},
    }
    screening_pool_sha256 = "c" * 64
    screen = {
        "study_id": "screen-pool",
        "study_status": "provisional_temporal_isolation",
        "plan_sha256": screening_pool_sha256,
        "screening_scope": "machine_triage_not_human_eligibility",
        "records": [
            {
                "document_id": document_id,
                "split": split_by_id.get(document_id, "development"),
                "full_text_sha256": _sha256(frozen[document_id]),
                "xml_size_bytes": len(frozen[document_id]),
                "machine_screen_status": "strong_biomolecular_protocol_signal",
                "machine_eligible_for_annotation": True,
            }
            for document_id in all_ids
        ],
        "failures": [],
    }
    screen_sha256 = canonical_sha256(screen)
    selected_plan_rows = [
        {
            "document_id": document_id,
            "title": f"Article {document_id}",
            "source_uri": _source_uri(document_id),
            "year": 2020,
        }
        for document_id in selected_ids
    ]
    plan = {
        "study_id": "provisional-60",
        "study_status": "provisional_temporal_isolation_machine_screened",
        "source_pool_plan_sha256": screening_pool_sha256,
        "screen_sha256": screen_sha256,
        "screening_scope": "machine_triage_not_human_eligibility",
        "development": selected_plan_rows[:30],
        "validation": selected_plan_rows[30:40],
        "locked_test": selected_plan_rows[40:],
        "rejected_or_reserve": [
            {
                "document_id": document_id,
                "reason": "eligible_reserve_not_selected",
                "machine_screen_status": "strong_biomolecular_protocol_signal",
                "article_type": "research-article",
            }
            for document_id in reserve_ids
        ],
        "interpretation": "machine-screened provisional plan",
    }
    plan["plan_sha256"] = canonical_sha256(_plan_core(plan))
    original_core = {
        "study_id": "original-parent-60",
        "study_status": "provisional_temporal_isolation_machine_screened",
        "plan_sha256": plan["plan_sha256"],
        "source_screen_sha256": screen_sha256,
        "source_workflow_run": 29087844703,
        "source_workflow_artifact_id": 8225494475,
        "source_workflow_artifact_digest": f"sha256:{'d' * 64}",
        "articles": [
            {
                "document_id": document_id,
                "split": split_by_id[document_id],
                "source_uri": _source_uri(document_id),
                "full_text_sha256": _sha256(frozen[document_id]),
            }
            for document_id in selected_ids
        ],
    }
    original = {
        **original_core,
        "manifest_sha256": canonical_sha256(original_core),
    }
    original_path = tmp_path / "original.json"
    plan_path = tmp_path / "plan.json"
    screen_path = tmp_path / "screen.json"
    original_file_sha256 = _write_json(original_path, original)
    plan_file_sha256 = _write_json(plan_path, plan)
    screen_file_sha256 = _write_json(screen_path, screen)

    superseded_position = 45
    superseded_index = superseded_position - 1
    superseded_old_article = original["articles"][superseded_index]
    superseded_new_article = {
        "document_id": reserve_ids[0],
        "split": superseded_old_article["split"],
        "source_uri": _source_uri(reserve_ids[0]),
        "full_text_sha256": _sha256(frozen[reserve_ids[0]]),
    }
    superseded_articles = deepcopy(original["articles"])
    superseded_articles[superseded_index] = superseded_new_article
    superseded_observed_old = _xml(
        superseded_old_article["document_id"],
        f"PRIVATE DRIFT AT POSITION {superseded_position}",
    )
    superseded_old = {
        "document_id": superseded_old_article["document_id"],
        "position": superseded_position,
        "split": superseded_old_article["split"],
        "source_uri": superseded_old_article["source_uri"],
        "frozen_full_text_sha256": superseded_old_article["full_text_sha256"],
        "frozen_size_bytes": len(frozen[superseded_old_article["document_id"]]),
        "observed_current_full_text_sha256": _sha256(superseded_observed_old),
        "observed_current_size_bytes": len(superseded_observed_old),
    }
    superseded_new = {
        "document_id": superseded_new_article["document_id"],
        "position": superseded_position,
        "split": superseded_new_article["split"],
        "source_uri": superseded_new_article["source_uri"],
        "full_text_sha256": superseded_new_article["full_text_sha256"],
        "xml_size_bytes": len(frozen[reserve_ids[0]]),
        "original_plan_reserve_rank": 1,
        "original_plan_reserve_reason": RESERVE_REASON,
    }
    superseded_core = {
        "study_id": original["study_id"],
        "study_status": original["study_status"],
        "plan_sha256": plan["plan_sha256"],
        "source_screen_sha256": screen_sha256,
        "source_workflow_run": original["source_workflow_run"],
        "source_workflow_artifact_id": original["source_workflow_artifact_id"],
        "source_workflow_artifact_digest": original[
            "source_workflow_artifact_digest"
        ],
        "schema_version": SUPERSEDED_MANIFEST_SCHEMA_VERSION,
        "generated_at": "2026-07-15T18:00:00Z",
        "parent_manifest_sha256": original["manifest_sha256"],
        "parent_manifest_file_sha256": original_file_sha256,
        "provisional_plan_file_sha256": plan_file_sha256,
        "fulltext_screen_file_sha256": screen_file_sha256,
        "substitution_reason": SUBSTITUTION_REASON,
        "substitution_policy": "first_original_plan_eligible_reserve_not_selected",
        "failed_stage_job_id": 185329,
        "substitution_job_id": 185500,
        "substitution_old": superseded_old,
        "substitution_new": superseded_new,
        "model_output_used_for_substitution": False,
        "unchanged_article_count_expected": 59,
        "unchanged_article_count_observed": 59,
        "articles": superseded_articles,
    }
    superseded = {
        **superseded_core,
        "manifest_sha256": canonical_sha256(superseded_core),
    }
    superseded_path = tmp_path / "superseded.json"
    superseded_file_sha256 = _write_json(superseded_path, superseded)
    substitution_report_core = {
        "schema_version": SUPERSEDED_REPORT_SCHEMA_VERSION,
        "status": "pass",
        "generated_at": superseded["generated_at"],
        "parent_manifest_sha256": original["manifest_sha256"],
        "new_manifest_sha256": superseded["manifest_sha256"],
        "source_workflow_run": original["source_workflow_run"],
        "source_workflow_artifact_id": original["source_workflow_artifact_id"],
        "source_workflow_artifact_digest": original[
            "source_workflow_artifact_digest"
        ],
        "parent_manifest_file_sha256": original_file_sha256,
        "provisional_plan_sha256": plan["plan_sha256"],
        "provisional_plan_file_sha256": plan_file_sha256,
        "fulltext_screen_sha256": screen_sha256,
        "fulltext_screen_file_sha256": screen_file_sha256,
        "reason": SUBSTITUTION_REASON,
        "selection_policy": "first_original_plan_eligible_reserve_not_selected",
        "failed_stage_job_id": 185329,
        "substitution_job_id": 185500,
        "old": superseded_old,
        "new": superseded_new,
        "model_output_used": False,
        "unchanged_article_count_expected": 59,
        "unchanged_article_count_observed": 59,
        "article_count": 60,
        "full_text_included": False,
    }
    substitution_report = {
        **substitution_report_core,
        "report_sha256": canonical_sha256(substitution_report_core),
    }
    substitution_report_path = tmp_path / "substitution-report.json"
    substitution_report_file_sha256 = _write_json(
        substitution_report_path,
        substitution_report,
    )

    matching_cache_dir = tmp_path / "matching-cache"
    diagnostic_dir = tmp_path / "diagnostic"
    matching_cache_dir.mkdir()
    diagnostic_dir.mkdir()
    drift_positions = (5, 45)
    selected_audit: list[dict[str, Any]] = []
    for position, document_id in enumerate(selected_ids, start=1):
        base = {
            "pool_role": "selected",
            "document_id": document_id,
            "original_position": position,
            "split": split_by_id[document_id],
            "expected_full_text_sha256": _sha256(frozen[document_id]),
            "expected_size_bytes": len(frozen[document_id]),
        }
        if position in drift_positions:
            observed = (
                superseded_observed_old
                if position == superseded_position
                else _xml(document_id, f"PRIVATE DRIFT AT POSITION {position}")
            )
            record = _diagnostic_record(base, observed, identity_valid=True)
            (diagnostic_dir / f"{document_id}.current.xml").write_bytes(observed)
        else:
            observed = frozen[document_id]
            record = _exact_record(base, observed)
            (matching_cache_dir / f"{document_id}.xml").write_bytes(observed)
        selected_audit.append(record)

    reserve_audit: list[dict[str, Any]] = []
    for rank, document_id in enumerate(reserve_ids, start=1):
        base = {
            "pool_role": "eligible_reserve",
            "document_id": document_id,
            "original_reserve_rank": rank,
            "expected_full_text_sha256": _sha256(frozen[document_id]),
            "expected_size_bytes": len(frozen[document_id]),
        }
        if rank == 1:
            observed = _xml("PMC999999", "PRIVATE WRONG IDENTITY")
            record = _diagnostic_record(base, observed, identity_valid=False)
            (diagnostic_dir / f"{document_id}.current.xml").write_bytes(observed)
        elif rank in valid_reserve_ranks:
            observed = frozen[document_id]
            record = _exact_record(base, observed)
            (matching_cache_dir / f"{document_id}.xml").write_bytes(observed)
        else:
            record = _unavailable_record(base)
        reserve_audit.append(record)

    audit = _audit_report(
        original=original,
        original_file_sha256=original_file_sha256,
        plan=plan,
        plan_file_sha256=plan_file_sha256,
        screen=screen,
        screen_file_sha256=screen_file_sha256,
        selected=selected_audit,
        reserves=reserve_audit,
    )
    audit_path = tmp_path / "accepted-audit.json"
    audit_file_sha256 = _write_json(audit_path, audit)
    arguments = {
        "original_manifest_path": original_path,
        "expected_original_manifest_file_sha256": original_file_sha256,
        "superseded_manifest_path": superseded_path,
        "expected_superseded_manifest_file_sha256": superseded_file_sha256,
        "superseded_substitution_report_path": substitution_report_path,
        "expected_superseded_substitution_report_file_sha256": (
            substitution_report_file_sha256
        ),
        "provisional_plan_path": plan_path,
        "expected_plan_file_sha256": plan_file_sha256,
        "fulltext_screen_path": screen_path,
        "expected_screen_file_sha256": screen_file_sha256,
        "accepted_audit_report_path": audit_path,
        "expected_audit_report_file_sha256": audit_file_sha256,
        "matching_cache_dir": matching_cache_dir,
        "diagnostic_dir": diagnostic_dir,
        "source_commit": SOURCE_COMMIT,
        "source_archive_sha256": SOURCE_ARCHIVE_SHA256,
        "failed_stage_job_ids": "185329,185656",
        "rebuild_job_id": 185900,
        "generated_at": GENERATED_AT,
    }
    return {
        "arguments": arguments,
        "original": original,
        "plan": plan,
        "screen": screen,
        "superseded": superseded,
        "substitution_report": substitution_report,
        "audit": audit,
        "frozen": frozen,
        "selected_ids": selected_ids,
        "reserve_ids": reserve_ids,
        "drift_positions": drift_positions,
    }


def _call(case: dict[str, Any], **updates):
    arguments = dict(case["arguments"])
    arguments.update(updates)
    return rebuild_frozen_source_pool(**arguments)


def _validate(
    case: dict[str, Any],
    manifest: dict[str, Any],
    report: dict[str, Any],
    *,
    accepted_audit: dict[str, Any] | None = None,
) -> None:
    arguments = case["arguments"]
    validate_rebuild_outputs(
        manifest,
        report,
        accepted_audit if accepted_audit is not None else case["audit"],
        original_manifest_path=arguments["original_manifest_path"],
        expected_original_manifest_file_sha256=arguments[
            "expected_original_manifest_file_sha256"
        ],
        superseded_manifest_path=arguments["superseded_manifest_path"],
        expected_superseded_manifest_file_sha256=arguments[
            "expected_superseded_manifest_file_sha256"
        ],
        superseded_substitution_report_path=arguments[
            "superseded_substitution_report_path"
        ],
        expected_superseded_substitution_report_file_sha256=arguments[
            "expected_superseded_substitution_report_file_sha256"
        ],
        provisional_plan_path=arguments["provisional_plan_path"],
        expected_plan_file_sha256=arguments["expected_plan_file_sha256"],
        fulltext_screen_path=arguments["fulltext_screen_path"],
        expected_screen_file_sha256=arguments["expected_screen_file_sha256"],
        accepted_audit_report_path=arguments["accepted_audit_report_path"],
        expected_audit_report_file_sha256=arguments[
            "expected_audit_report_file_sha256"
        ],
        matching_cache_dir=arguments["matching_cache_dir"],
        diagnostic_dir=arguments["diagnostic_dir"],
    )


def _relink_pass_outputs(
    manifest: dict[str, Any],
    report: dict[str, Any],
) -> None:
    _recommit(manifest, "manifest_sha256")
    report["new_manifest_sha256"] = manifest["manifest_sha256"]
    _recommit(report, "report_sha256")


def test_complete_audit_rebuilds_two_positions_and_preserves_corpus(
    tmp_path: Path,
) -> None:
    case = _fixture(tmp_path)

    manifest, report = _call(case)

    assert manifest is not None
    assert [
        manifest["articles"][position - 1]["document_id"]
        for position in case["drift_positions"]
    ] == case["reserve_ids"][1:3]
    assert [row["new"]["original_reserve_rank"] for row in report["replacements"]] == [
        2,
        3,
    ]
    assert [row["position"] for row in report["replacements"]] == [5, 45]
    assert len(manifest["articles"]) == 60
    assert len({row["document_id"] for row in manifest["articles"]}) == 60
    assert Counter(row["split"] for row in manifest["articles"]) == {
        "development": 30,
        "validation": 10,
        "locked_test": 20,
    }
    assert manifest["unchanged_article_count"] == 58
    assert report["unchanged_article_count"] == 58
    assert sum(
        before == after
        for before, after in zip(
            case["original"]["articles"],
            manifest["articles"],
            strict=True,
        )
    ) == 58
    assert manifest["selection_parent_manifest_sha256"] == case["original"][
        "manifest_sha256"
    ]
    assert manifest["study_status"] == STUDY_STATUS
    assert manifest["manifest_sha256"] == canonical_sha256(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    assert report["report_sha256"] == canonical_sha256(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    assert manifest["model_output_used_for_rebuild"] is False
    assert report["model_output_used"] is False
    assert report["full_text_included"] is False
    assert report["private_paths_recorded"] is False
    serialized = json.dumps({"manifest": manifest, "report": report}, sort_keys=True)
    assert "PRIVATE DRIFT" not in serialized
    assert "PRIVATE WRONG IDENTITY" not in serialized
    assert str(tmp_path) not in serialized
    _validate(case, manifest, report)


def test_invalid_earlier_reserve_is_skipped_only_in_complete_audit_order(
    tmp_path: Path,
) -> None:
    case = _fixture(tmp_path)

    manifest, report = _call(case)

    assert manifest is not None
    assert case["audit"]["eligible_reserves"][0]["currently_valid"] is False
    assert case["audit"]["eligible_reserves"][0]["classification"] == (
        "invalid_pmcid_identity"
    )
    assert [row["new"]["document_id"] for row in report["replacements"]] == (
        case["reserve_ids"][1:3]
    )
    assert case["reserve_ids"][3] not in {
        row["document_id"] for row in manifest["articles"]
    }


def test_insufficient_valid_reserves_emits_report_only_with_pinned_decision(
    tmp_path: Path,
) -> None:
    case = _fixture(tmp_path, valid_reserve_ranks=(2,))

    manifest, report = _call(case)

    assert manifest is None
    assert report["status"] == "blocked_insufficient_valid_reserves"
    assert report["output_manifest_created"] is False
    assert report["replacement_required_count"] == 2
    assert report["drifted_positions"] == [5, 45]
    assert report["valid_reserve_count"] == 1
    assert report["available_valid_reserve_ranks"] == [2]
    assert report["reserve_deficit"] == 1
    assert report["failed_stage_job_ids"] == [185329, 185656]
    assert report["accepted_audit_sha256"] == case["audit"]["audit_sha256"]
    assert report["rebuild_policy"] == REBUILD_POLICY
    assert report["superseded_remediations"] == [
        {
            "manifest_sha256": case["superseded"]["manifest_sha256"],
            "manifest_file_sha256": case["arguments"][
                "expected_superseded_manifest_file_sha256"
            ],
            "substitution_report_sha256": case["substitution_report"][
                "report_sha256"
            ],
            "substitution_report_file_sha256": case["arguments"][
                "expected_superseded_substitution_report_file_sha256"
            ],
            "failed_stage_job_id": 185329,
            "substitution_job_id": 185500,
            "status": "superseded_by_complete_pool_rebuild",
        }
    ]
    assert "new_manifest_sha256" not in report
    assert "replacements" not in report
    assert "invariants" not in report
    assert report["model_output_used"] is False
    assert report["full_text_included"] is False
    assert report["private_paths_recorded"] is False
    assert report["report_sha256"] == canonical_sha256(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )


@pytest.mark.parametrize(
    "failure",
    ["incomplete", "audit_commitment", "matching_cache", "diagnostic_cache"],
)
def test_rejects_incomplete_or_tampered_audit_and_private_cache(
    tmp_path: Path,
    failure: str,
) -> None:
    case = _fixture(tmp_path)
    arguments = dict(case["arguments"])
    if failure in {"incomplete", "audit_commitment"}:
        audit = deepcopy(case["audit"])
        if failure == "incomplete":
            audit["status"] = "incomplete"
            _recommit(audit, "audit_sha256")
            match = "incomplete"
        else:
            audit["model_output_used"] = True
            match = "commitment"
        arguments["expected_audit_report_file_sha256"] = _write_json(
            arguments["accepted_audit_report_path"],
            audit,
        )
    elif failure == "matching_cache":
        path = arguments["matching_cache_dir"] / f"{case['selected_ids'][0]}.xml"
        path.write_bytes(path.read_bytes() + b"tampered")
        match = "SHA-256"
    else:
        document_id = case["selected_ids"][case["drift_positions"][0] - 1]
        path = arguments["diagnostic_dir"] / f"{document_id}.current.xml"
        path.write_bytes(path.read_bytes() + b"tampered")
        match = "SHA-256"

    with pytest.raises(ValueError, match=match):
        rebuild_frozen_source_pool(**arguments)


@pytest.mark.parametrize(
    "path_key",
    [
        "original_manifest_path",
        "superseded_manifest_path",
        "superseded_substitution_report_path",
        "provisional_plan_path",
        "fulltext_screen_path",
        "accepted_audit_report_path",
    ],
)
def test_rejects_changed_external_artifact_file_sha256(
    tmp_path: Path,
    path_key: str,
) -> None:
    case = _fixture(tmp_path)
    path = case["arguments"][path_key]
    path.write_bytes(path.read_bytes() + b"\n")

    with pytest.raises(ValueError, match="file SHA-256"):
        _call(case)


@pytest.mark.parametrize("artifact", ["original", "plan"])
def test_rejects_recommitted_original_or_plan_order_changes(
    tmp_path: Path,
    artifact: str,
) -> None:
    case = _fixture(tmp_path)
    arguments = dict(case["arguments"])
    original = deepcopy(case["original"])
    if artifact == "original":
        original["articles"][0], original["articles"][1] = (
            original["articles"][1],
            original["articles"][0],
        )
    else:
        plan = deepcopy(case["plan"])
        plan["development"][0], plan["development"][1] = (
            plan["development"][1],
            plan["development"][0],
        )
        plan["plan_sha256"] = canonical_sha256(_plan_core(plan))
        arguments["expected_plan_file_sha256"] = _write_json(
            arguments["provisional_plan_path"],
            plan,
        )
        original["plan_sha256"] = plan["plan_sha256"]
    _recommit(original, "manifest_sha256")
    arguments["expected_original_manifest_file_sha256"] = _write_json(
        arguments["original_manifest_path"],
        original,
    )

    with pytest.raises(ValueError, match="source order differs"):
        rebuild_frozen_source_pool(**arguments)


def test_rejects_recommitted_superseded_manifest_order_change(tmp_path: Path) -> None:
    case = _fixture(tmp_path)
    arguments = dict(case["arguments"])
    superseded = deepcopy(case["superseded"])
    superseded["articles"][0], superseded["articles"][1] = (
        superseded["articles"][1],
        superseded["articles"][0],
    )
    _recommit(superseded, "manifest_sha256")
    arguments["expected_superseded_manifest_file_sha256"] = _write_json(
        arguments["superseded_manifest_path"],
        superseded,
    )
    substitution_report = deepcopy(case["substitution_report"])
    substitution_report["new_manifest_sha256"] = superseded["manifest_sha256"]
    _recommit(substitution_report, "report_sha256")
    arguments[
        "expected_superseded_substitution_report_file_sha256"
    ] = _write_json(
        arguments["superseded_substitution_report_path"],
        substitution_report,
    )

    with pytest.raises(ValueError, match="differ from the original at one row"):
        rebuild_frozen_source_pool(**arguments)


def test_rejects_reordered_screen_against_frozen_file_sha256(tmp_path: Path) -> None:
    case = _fixture(tmp_path)
    screen = deepcopy(case["screen"])
    screen["records"][0], screen["records"][1] = (
        screen["records"][1],
        screen["records"][0],
    )
    _write_json(case["arguments"]["fulltext_screen_path"], screen)

    with pytest.raises(ValueError, match="file SHA-256"):
        _call(case)


@pytest.mark.parametrize(
    "bad_jobs",
    [
        "",
        "0",
        "185329,185329",
        "185656,185329",
        [],
        [185329, True],
    ],
)
def test_rejects_invalid_failed_stage_job_ids(tmp_path: Path, bad_jobs: Any) -> None:
    case = _fixture(tmp_path)

    with pytest.raises(ValueError, match="failed stage job IDs"):
        _call(case, failed_stage_job_ids=bad_jobs)


@pytest.mark.parametrize("bad_job", [0, -1, True])
def test_rejects_invalid_rebuild_job_id(tmp_path: Path, bad_job: Any) -> None:
    case = _fixture(tmp_path)

    with pytest.raises(ValueError, match="rebuild_job_id"):
        _call(case, rebuild_job_id=bad_job)


@pytest.mark.parametrize(
    "failed_jobs",
    ["185656", "185329,185656,185700"],
)
def test_rejects_missing_or_extra_failed_stage_jobs(
    tmp_path: Path,
    failed_jobs: str,
) -> None:
    case = _fixture(tmp_path)

    with pytest.raises(
        ValueError,
        match="requires the two ordered failed staging jobs",
    ):
        _call(case, failed_stage_job_ids=failed_jobs)


def test_rejects_first_failed_job_that_differs_from_superseded_evidence(
    tmp_path: Path,
) -> None:
    case = _fixture(tmp_path)

    with pytest.raises(ValueError, match="differs from superseded remediation"):
        _call(case, failed_stage_job_ids="185328,185656")


@pytest.mark.parametrize(
    "updates",
    [
        {"failed_stage_job_ids": "185329,185800"},
        {"rebuild_job_id": 185656},
        {"rebuild_job_id": 185800},
    ],
)
def test_rejects_out_of_order_or_conflicting_job_lineage(
    tmp_path: Path,
    updates: dict[str, Any],
) -> None:
    case = _fixture(tmp_path)

    with pytest.raises(ValueError, match="jobs are out of order"):
        _call(case, **updates)


@pytest.mark.parametrize("artifact", ["manifest", "report"])
def test_rejects_exact_unknown_output_keys(tmp_path: Path, artifact: str) -> None:
    case = _fixture(tmp_path)
    manifest, report = _call(case)
    assert manifest is not None
    manifest = deepcopy(manifest)
    report = deepcopy(report)

    if artifact == "manifest":
        manifest["private_cache_path"] = "/restricted/cache/PMC000001.xml"
        _relink_pass_outputs(manifest, report)
        match = "rebuilt source manifest fields are invalid"
    else:
        report["private_cache_path"] = "/restricted/cache/PMC000001.xml"
        _recommit(report, "report_sha256")
        match = "source-pool rebuild report fields are invalid"

    with pytest.raises(ValueError, match=match):
        _validate(case, manifest, report)


def test_rejects_forged_selection_parent_lineage(tmp_path: Path) -> None:
    case = _fixture(tmp_path)
    manifest, report = _call(case)
    assert manifest is not None
    manifest = deepcopy(manifest)
    report = deepcopy(report)
    forged_parent = "e" * 64
    manifest["selection_parent_manifest_sha256"] = forged_parent
    report["selection_parent_manifest_sha256"] = forged_parent
    _relink_pass_outputs(manifest, report)

    with pytest.raises(ValueError, match="pinned frozen-input lineage"):
        _validate(case, manifest, report)


def test_rejects_recommitted_forged_audit_lineage(tmp_path: Path) -> None:
    case = _fixture(tmp_path)
    audit = deepcopy(case["audit"])
    audit["original_manifest_sha256"] = "e" * 64
    _recommit(audit, "audit_sha256")
    case["arguments"]["expected_audit_report_file_sha256"] = _write_json(
        case["arguments"]["accepted_audit_report_path"],
        audit,
    )

    with pytest.raises(ValueError, match="accepted audit lineage differs"):
        _call(case)


def test_rejects_recommitted_forged_superseded_parent_lineage(
    tmp_path: Path,
) -> None:
    case = _fixture(tmp_path)
    superseded = deepcopy(case["superseded"])
    substitution_report = deepcopy(case["substitution_report"])
    forged_parent = "e" * 64
    superseded["parent_manifest_sha256"] = forged_parent
    _recommit(superseded, "manifest_sha256")
    substitution_report["parent_manifest_sha256"] = forged_parent
    substitution_report["new_manifest_sha256"] = superseded["manifest_sha256"]
    _recommit(substitution_report, "report_sha256")
    case["arguments"][
        "expected_superseded_manifest_file_sha256"
    ] = _write_json(case["arguments"]["superseded_manifest_path"], superseded)
    case["arguments"][
        "expected_superseded_substitution_report_file_sha256"
    ] = _write_json(
        case["arguments"]["superseded_substitution_report_path"],
        substitution_report,
    )

    with pytest.raises(ValueError, match="does not descend from the original"):
        _call(case)


def test_rejects_recommitted_forged_superseded_nested_metadata(
    tmp_path: Path,
) -> None:
    case = _fixture(tmp_path)
    superseded = deepcopy(case["superseded"])
    substitution_report = deepcopy(case["substitution_report"])
    superseded["substitution_new"]["original_plan_reserve_rank"] = 2
    substitution_report["new"]["original_plan_reserve_rank"] = 2
    _recommit(superseded, "manifest_sha256")
    substitution_report["new_manifest_sha256"] = superseded["manifest_sha256"]
    _recommit(substitution_report, "report_sha256")
    case["arguments"][
        "expected_superseded_manifest_file_sha256"
    ] = _write_json(case["arguments"]["superseded_manifest_path"], superseded)
    case["arguments"][
        "expected_superseded_substitution_report_file_sha256"
    ] = _write_json(
        case["arguments"]["superseded_substitution_report_path"],
        substitution_report,
    )

    with pytest.raises(ValueError, match="new-row metadata differs"):
        _call(case)


def test_rejects_superseded_old_evidence_that_differs_from_complete_audit(
    tmp_path: Path,
) -> None:
    case = _fixture(tmp_path)
    superseded = deepcopy(case["superseded"])
    substitution_report = deepcopy(case["substitution_report"])
    superseded["substitution_old"]["observed_current_full_text_sha256"] = "f" * 64
    superseded["substitution_old"]["observed_current_size_bytes"] += 1
    substitution_report["old"] = deepcopy(superseded["substitution_old"])
    _recommit(superseded, "manifest_sha256")
    substitution_report["new_manifest_sha256"] = superseded["manifest_sha256"]
    _recommit(substitution_report, "report_sha256")
    case["arguments"][
        "expected_superseded_manifest_file_sha256"
    ] = _write_json(case["arguments"]["superseded_manifest_path"], superseded)
    case["arguments"][
        "expected_superseded_substitution_report_file_sha256"
    ] = _write_json(
        case["arguments"]["superseded_substitution_report_path"],
        substitution_report,
    )

    with pytest.raises(
        ValueError,
        match="old-row evidence differs from the complete audit",
    ):
        _call(case)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("study_status", "production_ready", "study status is invalid"),
        (
            "generated_at",
            "2026-07-15T20:00:00+01:00",
            "ISO-8601 UTC timestamp",
        ),
    ],
)
def test_rejects_invalid_rebuilt_study_status_or_timestamp(
    tmp_path: Path,
    field: str,
    value: str,
    match: str,
) -> None:
    case = _fixture(tmp_path)
    manifest, report = _call(case)
    assert manifest is not None
    manifest = deepcopy(manifest)
    report = deepcopy(report)
    manifest[field] = value
    if field == "generated_at":
        report[field] = value
    _relink_pass_outputs(manifest, report)

    with pytest.raises(ValueError, match=match):
        _validate(case, manifest, report)


def test_rejects_original_manifest_extra_private_field(tmp_path: Path) -> None:
    case = _fixture(tmp_path)
    original = deepcopy(case["original"])
    original["private_cache_path"] = str(tmp_path / "matching-cache")
    _recommit(original, "manifest_sha256")
    case["arguments"][
        "expected_original_manifest_file_sha256"
    ] = _write_json(case["arguments"]["original_manifest_path"], original)

    with pytest.raises(ValueError, match="original manifest fields are invalid"):
        _call(case)


def test_cli_blocked_exit_three_writes_report_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _fixture(tmp_path, valid_reserve_ranks=(2,))
    arguments = case["arguments"]
    output_manifest = tmp_path / "output" / "source_manifest.json"
    output_report = tmp_path / "output" / "rebuild_report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rebuild_frozen_source_pool.py",
            "--original-source-manifest",
            str(arguments["original_manifest_path"]),
            "--original-source-manifest-sha256",
            arguments["expected_original_manifest_file_sha256"],
            "--superseded-source-manifest",
            str(arguments["superseded_manifest_path"]),
            "--superseded-source-manifest-sha256",
            arguments["expected_superseded_manifest_file_sha256"],
            "--superseded-substitution-report",
            str(arguments["superseded_substitution_report_path"]),
            "--superseded-substitution-report-sha256",
            arguments["expected_superseded_substitution_report_file_sha256"],
            "--provisional-plan",
            str(arguments["provisional_plan_path"]),
            "--provisional-plan-sha256",
            arguments["expected_plan_file_sha256"],
            "--fulltext-screen",
            str(arguments["fulltext_screen_path"]),
            "--fulltext-screen-sha256",
            arguments["expected_screen_file_sha256"],
            "--accepted-audit-report",
            str(arguments["accepted_audit_report_path"]),
            "--accepted-audit-report-sha256",
            arguments["expected_audit_report_file_sha256"],
            "--matching-cache-dir",
            str(arguments["matching_cache_dir"]),
            "--diagnostic-dir",
            str(arguments["diagnostic_dir"]),
            "--source-commit",
            arguments["source_commit"],
            "--source-archive-sha256",
            arguments["source_archive_sha256"],
            "--failed-stage-job-ids",
            arguments["failed_stage_job_ids"],
            "--rebuild-job-id",
            str(arguments["rebuild_job_id"]),
            "--output-manifest",
            str(output_manifest),
            "--output-report",
            str(output_report),
        ],
    )

    assert rebuild_main() == 3
    assert not output_manifest.exists()
    assert output_report.is_file()
    report = json.loads(output_report.read_text())
    validate_blocked_rebuild_report_files(
        report,
        original_manifest_path=arguments["original_manifest_path"],
        expected_original_manifest_file_sha256=arguments[
            "expected_original_manifest_file_sha256"
        ],
        superseded_manifest_path=arguments["superseded_manifest_path"],
        expected_superseded_manifest_file_sha256=arguments[
            "expected_superseded_manifest_file_sha256"
        ],
        superseded_substitution_report_path=arguments[
            "superseded_substitution_report_path"
        ],
        expected_superseded_substitution_report_file_sha256=arguments[
            "expected_superseded_substitution_report_file_sha256"
        ],
        provisional_plan_path=arguments["provisional_plan_path"],
        expected_plan_file_sha256=arguments["expected_plan_file_sha256"],
        fulltext_screen_path=arguments["fulltext_screen_path"],
        expected_screen_file_sha256=arguments["expected_screen_file_sha256"],
        accepted_audit_report_path=arguments["accepted_audit_report_path"],
        expected_audit_report_file_sha256=arguments[
            "expected_audit_report_file_sha256"
        ],
        matching_cache_dir=arguments["matching_cache_dir"],
        diagnostic_dir=arguments["diagnostic_dir"],
    )
    assert report["status"] == "blocked_insufficient_valid_reserves"
    assert report["output_manifest_created"] is False
    assert report["replacement_required_count"] == 2
    assert report["valid_reserve_count"] == 1
    assert report["reserve_deficit"] == 1
    assert "new_manifest_sha256" not in report
    assert "replacements" not in report
    assert report["report_sha256"] == canonical_sha256(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
