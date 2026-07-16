#!/usr/bin/env python3
"""Audit every originally selected JATS source and every ordered eligible reserve."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from xml.etree.ElementTree import ParseError

import httpx
from defusedxml.ElementTree import fromstring as safe_xml_fromstring
from defusedxml.common import DefusedXmlException

from mdmeta import user_agent
from mdmeta.benchmark import canonical_sha256
from mdmeta.llm_batch import (
    FULLTEXT_URL,
    RETRYABLE_STATUS_CODES,
    atomic_write_bytes,
    atomic_write_json,
    validate_sha256,
    validate_source_manifest,
)

try:
    from scripts.substitute_frozen_article import (
        RESERVE_REASON,
        _document_id,
        _load_expected_json,
        _screen_records,
        _source_uri,
        _validate_plan_commitment,
        _workflow_identity,
    )
except ModuleNotFoundError:  # pragma: no cover - direct execution from scripts/
    from substitute_frozen_article import (  # type: ignore[no-redef]
        RESERVE_REASON,
        _document_id,
        _load_expected_json,
        _screen_records,
        _source_uri,
        _validate_plan_commitment,
        _workflow_identity,
    )


SCHEMA_VERSION = "mdmeta.current-source-pool-audit.v1"
AUDIT_POLICY_VERSION = "original-selected-and-all-ordered-eligible-reserves.v1"
_COMMIT = re.compile(r"[0-9a-f]{40}")
_DEFINITIVE_UNAVAILABLE = {404, 410}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _positive_int(value: Any, *, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _screen_commitment(row: dict[str, Any], *, document_id: str) -> tuple[str, int]:
    digest = row.get("full_text_sha256")
    size = row.get("xml_size_bytes")
    if not isinstance(digest, str):
        raise ValueError(f"screen record {document_id} has no frozen JATS SHA-256")
    validate_sha256(digest, field=f"screen JATS digest for {document_id}")
    return digest, _positive_int(size, field=f"screen XML size for {document_id}")


def _prepare_empty_private_directory(path: Path, *, label: str) -> None:
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symbolic link")
    path.mkdir(parents=True, exist_ok=True)
    if any(path.iterdir()):
        raise ValueError(f"{label} must be empty")
    os.chmod(path, 0o700)


def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
    fallback = min(2.0**attempt, 20.0)
    if response is None:
        return fallback
    raw = response.headers.get("Retry-After")
    if raw is None:
        return fallback
    try:
        return min(max(float(raw), 0.0), 30.0)
    except ValueError:
        return fallback


def _retrieve_current(
    document_id: str,
    *,
    client: httpx.Client,
    retries: int,
    sleep: Callable[[float], None],
) -> dict[str, Any]:
    endpoint = FULLTEXT_URL.format(document_id=document_id)
    last_status: int | None = None
    for attempt in range(retries + 1):
        response: httpx.Response | None = None
        try:
            response = client.get(endpoint)
            last_status = response.status_code
            if response.is_success:
                return {
                    "status": "retrieved",
                    "attempts": attempt + 1,
                    "http_status": response.status_code,
                    "payload": response.content,
                    "error_code": None,
                }
            if response.status_code in _DEFINITIVE_UNAVAILABLE:
                return {
                    "status": "definitive_unavailable",
                    "attempts": attempt + 1,
                    "http_status": response.status_code,
                    "payload": None,
                    "error_code": f"http_{response.status_code}",
                }
            if response.status_code not in RETRYABLE_STATUS_CODES:
                return {
                    "status": "unresolved",
                    "attempts": attempt + 1,
                    "http_status": response.status_code,
                    "payload": None,
                    "error_code": "non_retryable_http_error",
                }
        except httpx.TransportError:
            response = None
        if attempt < retries:
            sleep(_retry_delay(response, attempt))
    return {
        "status": "unresolved",
        "attempts": retries + 1,
        "http_status": last_status,
        "payload": None,
        "error_code": "retry_budget_exhausted",
    }


def _pmcid_identity(payload: bytes, document_id: str) -> bool:
    try:
        root = safe_xml_fromstring(payload)
    except (DefusedXmlException, ParseError):
        return False
    observed_ids = {
        " ".join("".join(node.itertext()).split()).upper()
        for node in root.findall(".//article-id[@pub-id-type='pmcid']")
    }
    return document_id in observed_ids


def _validate_inputs(
    *,
    parent_manifest_path: Path,
    expected_parent_file_sha256: str,
    provisional_plan_path: Path,
    expected_plan_file_sha256: str,
    fulltext_screen_path: Path,
    expected_screen_file_sha256: str,
) -> tuple[
    dict[str, Any],
    str,
    dict[str, Any],
    str,
    dict[str, Any],
    str,
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    parent, parent_file_sha256 = _load_expected_json(
        parent_manifest_path,
        expected_parent_file_sha256,
        label="original source manifest",
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
    parent_articles = validate_source_manifest(parent)
    if len(parent_articles) != 60:
        raise ValueError("original source manifest must contain exactly 60 articles")
    selected_plan_rows = _validate_plan_commitment(plan)
    screen_records = _screen_records(screen)
    screen_sha256 = canonical_sha256(screen)
    if plan.get("screen_sha256") != screen_sha256:
        raise ValueError("full-text screen commitment differs from the provisional plan")
    if parent.get("source_screen_sha256") != screen_sha256:
        raise ValueError("full-text screen commitment differs from the original manifest")
    if parent.get("plan_sha256") != plan.get("plan_sha256"):
        raise ValueError("provisional plan commitment differs from the original manifest")
    if screen.get("plan_sha256") != plan.get("source_pool_plan_sha256"):
        raise ValueError("full-text screen differs from the plan's original screening pool")

    parent_rows = [article.model_dump(mode="json") for article in parent_articles]
    plan_ids = [row["document_id"] for _, row in selected_plan_rows]
    if [row["document_id"] for row in parent_rows] != plan_ids:
        raise ValueError("original source order differs from the provisional plan")

    selected: list[dict[str, Any]] = []
    for position, (parent_row, (plan_split, plan_row)) in enumerate(
        zip(parent_rows, selected_plan_rows, strict=True),
        start=1,
    ):
        document_id = parent_row["document_id"]
        if parent_row["split"] != plan_split:
            raise ValueError("original source split differs from the provisional plan")
        if parent_row["source_uri"] != _source_uri(document_id):
            raise ValueError("original source URI does not follow the Europe PMC rule")
        if plan_row.get("source_uri") != parent_row["source_uri"]:
            raise ValueError("original source URI differs from the provisional plan")
        screen_row = screen_records.get(document_id)
        if screen_row is None or screen_row.get("machine_eligible_for_annotation") is not True:
            raise ValueError("original selected source is not eligible in the frozen screen")
        expected_sha256, expected_size = _screen_commitment(
            screen_row,
            document_id=document_id,
        )
        if expected_sha256 != parent_row["full_text_sha256"]:
            raise ValueError("original source JATS digest differs from the frozen screen")
        selected.append(
            {
                "pool_role": "selected",
                "document_id": document_id,
                "original_position": position,
                "split": parent_row["split"],
                "expected_full_text_sha256": expected_sha256,
                "expected_size_bytes": expected_size,
            }
        )

    reserves: list[dict[str, Any]] = []
    selected_ids = {row["document_id"] for row in selected}
    reserve_ids: set[str] = set()
    for plan_row in plan["rejected_or_reserve"]:
        if plan_row.get("reason") != RESERVE_REASON:
            continue
        document_id = _document_id(
            plan_row.get("document_id"),
            field="eligible reserve document_id",
        )
        if document_id in selected_ids or document_id in reserve_ids:
            raise ValueError("eligible reserve identifiers must be unique and not selected")
        screen_row = screen_records.get(document_id)
        if screen_row is None or screen_row.get("machine_eligible_for_annotation") is not True:
            raise ValueError("eligible reserve is not eligible in the frozen screen")
        expected_sha256, expected_size = _screen_commitment(
            screen_row,
            document_id=document_id,
        )
        reserve_ids.add(document_id)
        reserves.append(
            {
                "pool_role": "eligible_reserve",
                "document_id": document_id,
                "original_reserve_rank": len(reserves) + 1,
                "expected_full_text_sha256": expected_sha256,
                "expected_size_bytes": expected_size,
            }
        )
    if not reserves:
        raise ValueError("provisional plan contains no eligible reserves")
    return (
        parent,
        parent_file_sha256,
        plan,
        plan_file_sha256,
        screen,
        screen_file_sha256,
        selected,
        reserves,
    )


def _audit_one(
    row: dict[str, Any],
    *,
    client: httpx.Client,
    retries: int,
    sleep: Callable[[float], None],
    matching_cache_dir: Path,
    diagnostic_dir: Path,
) -> dict[str, Any]:
    document_id = row["document_id"]
    retrieval = _retrieve_current(
        document_id,
        client=client,
        retries=retries,
        sleep=sleep,
    )
    payload = retrieval.pop("payload")
    record = {
        **row,
        "retrieval_status": retrieval["status"],
        "attempts": retrieval["attempts"],
        "http_status": retrieval["http_status"],
        "error_code": retrieval["error_code"],
        "observed_full_text_sha256": None,
        "observed_size_bytes": None,
        "pmcid_identity_valid": None,
        "frozen_payload_match": False,
        "cache_bucket": None,
    }
    if payload is None:
        if retrieval["status"] == "definitive_unavailable":
            record["classification"] = "definitive_unavailable"
            record["replacement_required"] = row["pool_role"] == "selected"
            record["currently_valid"] = False
        else:
            record["classification"] = "unresolved"
            record["replacement_required"] = None
            record["currently_valid"] = None
        return record

    observed_sha256 = _sha256_bytes(payload)
    observed_size = len(payload)
    identity_valid = _pmcid_identity(payload, document_id)
    frozen_match = (
        observed_sha256 == row["expected_full_text_sha256"]
        and observed_size == row["expected_size_bytes"]
    )
    record.update(
        {
            "observed_full_text_sha256": observed_sha256,
            "observed_size_bytes": observed_size,
            "pmcid_identity_valid": identity_valid,
            "frozen_payload_match": frozen_match,
        }
    )
    if identity_valid and frozen_match:
        record["classification"] = "current_exact_match"
        record["replacement_required"] = False
        record["currently_valid"] = True
        record["cache_bucket"] = "matching_cache"
        destination = matching_cache_dir / f"{document_id}.xml"
    else:
        record["classification"] = (
            "frozen_payload_drift" if identity_valid else "invalid_pmcid_identity"
        )
        record["replacement_required"] = row["pool_role"] == "selected"
        record["currently_valid"] = False
        record["cache_bucket"] = "diagnostic"
        destination = diagnostic_dir / f"{document_id}.current.xml"
    atomic_write_bytes(destination, payload)
    return record


def validate_audit_report(
    payload: dict[str, Any],
    *,
    require_complete: bool = False,
) -> None:
    """Validate the compact audit commitment and anti-selection-bias invariants."""

    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("source-pool audit schema is invalid")
    stored_digest = payload.get("audit_sha256")
    core = {key: value for key, value in payload.items() if key != "audit_sha256"}
    if not isinstance(stored_digest, str) or stored_digest != canonical_sha256(core):
        raise ValueError("source-pool audit commitment is invalid")
    status = payload.get("status")
    if status not in {"complete", "incomplete"}:
        raise ValueError("source-pool audit status is invalid")
    if require_complete and status != "complete":
        raise ValueError("source-pool audit is incomplete")
    if payload.get("model_output_used") is not False:
        raise ValueError("source-pool audit must not use model output")
    if payload.get("full_text_included") is not False:
        raise ValueError("source-pool audit report must not contain full text")
    if payload.get("private_paths_recorded") is not False:
        raise ValueError("source-pool audit report must not contain private paths")
    _positive_int(payload.get("audit_job_id"), field="audit_job_id")
    if _COMMIT.fullmatch(str(payload.get("source_commit", ""))) is None:
        raise ValueError("source-pool audit source commit is invalid")
    validate_sha256(
        payload.get("source_archive_sha256"),
        field="source-pool audit source archive digest",
    )

    audit_spec = payload.get("audit_spec")
    if not isinstance(audit_spec, dict):
        raise ValueError("source-pool audit spec is missing")
    spec_digest = audit_spec.get("audit_spec_sha256")
    spec_core = {
        key: value for key, value in audit_spec.items() if key != "audit_spec_sha256"
    }
    if not isinstance(spec_digest, str) or spec_digest != canonical_sha256(spec_core):
        raise ValueError("source-pool audit spec commitment is invalid")
    if audit_spec.get("policy_version") != AUDIT_POLICY_VERSION:
        raise ValueError("source-pool audit policy version is invalid")

    selected = payload.get("selected")
    reserves = payload.get("eligible_reserves")
    if not isinstance(selected, list) or len(selected) != 60:
        raise ValueError("source-pool audit must contain exactly 60 selected records")
    if not isinstance(reserves, list) or not reserves:
        raise ValueError("source-pool audit must contain every eligible reserve")
    selected_ids = [row.get("document_id") for row in selected if isinstance(row, dict)]
    reserve_ids = [row.get("document_id") for row in reserves if isinstance(row, dict)]
    if len(selected_ids) != 60 or len(reserve_ids) != len(reserves):
        raise ValueError("source-pool audit records must be JSON objects")
    if len(set([*selected_ids, *reserve_ids])) != len(selected_ids) + len(reserve_ids):
        raise ValueError("source-pool audit document identifiers must be unique")
    if [row.get("original_position") for row in selected] != list(range(1, 61)):
        raise ValueError("selected audit positions are not complete and ordered")
    if [row.get("original_reserve_rank") for row in reserves] != list(
        range(1, len(reserves) + 1)
    ):
        raise ValueError("eligible reserve ranks are not complete and ordered")
    if any(row.get("pool_role") != "selected" for row in selected) or any(
        row.get("pool_role") != "eligible_reserve" for row in reserves
    ):
        raise ValueError("source-pool audit roles are invalid")
    split_counts = dict(sorted(Counter(row.get("split") for row in selected).items()))
    if split_counts != {"development": 30, "locked_test": 20, "validation": 10}:
        raise ValueError("selected audit split counts are invalid")
    if audit_spec.get("selected_count_expected") != 60:
        raise ValueError("audit spec selected count is invalid")
    if audit_spec.get("eligible_reserve_count_expected") != len(reserves):
        raise ValueError("audit spec reserve count is invalid")
    if audit_spec.get("ordered_selected_ids_sha256") != canonical_sha256(selected_ids):
        raise ValueError("audit spec selected order commitment is invalid")
    if audit_spec.get("ordered_reserve_ids_sha256") != canonical_sha256(reserve_ids):
        raise ValueError("audit spec reserve order commitment is invalid")

    records = [*selected, *reserves]
    for row in records:
        document_id = _document_id(row.get("document_id"), field="audit document_id")
        expected_digest = row.get("expected_full_text_sha256")
        validate_sha256(expected_digest, field=f"expected JATS digest for {document_id}")
        _positive_int(row.get("expected_size_bytes"), field="expected JATS size")
        _positive_int(row.get("attempts"), field="retrieval attempts")
        retrieval_status = row.get("retrieval_status")
        http_status = row.get("http_status")
        if http_status is not None and (
            not isinstance(http_status, int)
            or isinstance(http_status, bool)
            or not 100 <= http_status <= 599
        ):
            raise ValueError("source-pool audit HTTP status is invalid")
        bucket = row.get("cache_bucket")
        observed_digest = row.get("observed_full_text_sha256")
        observed_size = row.get("observed_size_bytes")
        if bucket in {"matching_cache", "diagnostic"}:
            validate_sha256(observed_digest, field=f"observed JATS digest for {document_id}")
            _positive_int(observed_size, field="observed JATS size")
            if row.get("pmcid_identity_valid") not in {True, False}:
                raise ValueError("cached audit row has no PMCID identity result")
        elif bucket is not None:
            raise ValueError("source-pool audit cache bucket is invalid")
        elif observed_digest is not None or observed_size is not None:
            raise ValueError("uncached audit row records an observed payload")
        computed_frozen_match = (
            observed_digest == expected_digest
            and observed_size == row.get("expected_size_bytes")
        )
        if row.get("frozen_payload_match") is not computed_frozen_match:
            raise ValueError("audit row frozen-payload match flag is inconsistent")
        classification = row.get("classification")
        if classification == "current_exact_match":
            if not (
                retrieval_status == "retrieved"
                and isinstance(http_status, int)
                and 200 <= http_status <= 299
                and row.get("error_code") is None
                and bucket == "matching_cache"
                and row.get("frozen_payload_match") is True
                and row.get("pmcid_identity_valid") is True
                and row.get("currently_valid") is True
            ):
                raise ValueError("exact-match audit row is inconsistent")
        elif classification in {"frozen_payload_drift", "invalid_pmcid_identity"}:
            if not (
                retrieval_status == "retrieved"
                and isinstance(http_status, int)
                and 200 <= http_status <= 299
                and row.get("error_code") is None
                and bucket == "diagnostic"
                and row.get("currently_valid") is False
            ):
                raise ValueError("diagnostic audit row is inconsistent")
        elif classification == "definitive_unavailable":
            if not (
                retrieval_status == "definitive_unavailable"
                and http_status in _DEFINITIVE_UNAVAILABLE
                and bucket is None
                and row.get("currently_valid") is False
            ):
                raise ValueError("unavailable audit row is inconsistent")
        elif classification == "unresolved":
            if not (
                retrieval_status == "unresolved"
                and bucket is None
                and row.get("currently_valid") is None
            ):
                raise ValueError("unresolved audit row is inconsistent")
        else:
            raise ValueError("source-pool audit classification is invalid")
        expected_replacement = None
        if classification != "unresolved":
            expected_replacement = (
                row["pool_role"] == "selected"
                and classification != "current_exact_match"
            )
        if row.get("replacement_required") is not expected_replacement:
            raise ValueError("audit row replacement-required flag is inconsistent")

    unresolved_count = sum(row["classification"] == "unresolved" for row in records)
    selected_replacement_count = sum(
        row.get("replacement_required") is True for row in selected
    )
    valid_reserve_count = sum(row.get("currently_valid") is True for row in reserves)
    matching_count = sum(row.get("cache_bucket") == "matching_cache" for row in records)
    diagnostic_count = sum(row.get("cache_bucket") == "diagnostic" for row in records)
    summary = payload.get("summary")
    expected_summary_values = {
        "selected_count": 60,
        "eligible_reserve_count": len(reserves),
        "audited_record_count": len(records),
        "selected_split_counts": split_counts,
        "selected_replacement_required_count": selected_replacement_count,
        "selected_exact_match_count": sum(
            row["classification"] == "current_exact_match" for row in selected
        ),
        "valid_reserve_count": valid_reserve_count,
        "unresolved_count": unresolved_count,
        "matching_cache_file_count": matching_count,
        "diagnostic_file_count": diagnostic_count,
        "sufficient_valid_reserves": (
            unresolved_count == 0 and valid_reserve_count >= selected_replacement_count
        ),
    }
    if not isinstance(summary, dict) or any(
        summary.get(key) != value for key, value in expected_summary_values.items()
    ):
        raise ValueError("source-pool audit summary is inconsistent")
    if (status == "complete") != (unresolved_count == 0):
        raise ValueError("source-pool audit status differs from unresolved count")
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
    if payload.get("cache_inventory_sha256") != canonical_sha256(inventory):
        raise ValueError("source-pool audit cache inventory commitment is invalid")


def validate_audit_cache(
    payload: dict[str, Any],
    *,
    matching_cache_dir: Path,
    diagnostic_dir: Path,
    require_complete: bool = False,
) -> None:
    """Verify the private cached bytes against the compact audit inventory."""

    validate_audit_report(payload, require_complete=require_complete)
    expected: dict[Path, dict[str, Any]] = {}
    for row in [*payload["selected"], *payload["eligible_reserves"]]:
        if row["cache_bucket"] == "matching_cache":
            expected[matching_cache_dir / f"{row['document_id']}.xml"] = row
        elif row["cache_bucket"] == "diagnostic":
            expected[diagnostic_dir / f"{row['document_id']}.current.xml"] = row
    for directory in (matching_cache_dir, diagnostic_dir):
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("audit cache directory is missing or is a symlink")
    observed_paths = {
        path
        for directory in (matching_cache_dir, diagnostic_dir)
        for path in directory.iterdir()
    }
    if observed_paths != set(expected):
        raise ValueError("audit cache file inventory differs from the compact report")
    for path, row in expected.items():
        if path.is_symlink() or not path.is_file():
            raise ValueError("audit cache entry is missing or is a symlink")
        payload_bytes = path.read_bytes()
        if _sha256_bytes(payload_bytes) != row["observed_full_text_sha256"]:
            raise ValueError("audit cache entry SHA-256 differs from the compact report")
        if len(payload_bytes) != row["observed_size_bytes"]:
            raise ValueError("audit cache entry size differs from the compact report")
        if _pmcid_identity(payload_bytes, row["document_id"]) != row["pmcid_identity_valid"]:
            raise ValueError("audit cache PMCID identity differs from the compact report")


def audit_frozen_source_pool(
    *,
    parent_manifest_path: Path,
    expected_parent_file_sha256: str,
    provisional_plan_path: Path,
    expected_plan_file_sha256: str,
    fulltext_screen_path: Path,
    expected_screen_file_sha256: str,
    source_commit: str,
    source_archive_sha256: str,
    audit_job_id: int,
    matching_cache_dir: Path,
    diagnostic_dir: Path,
    client: httpx.Client,
    timeout_seconds: float = 45.0,
    retries: int = 5,
    sleep: Callable[[float], None] = time.sleep,
    generated_at: str | None = None,
    http_user_agent: str | None = None,
) -> dict[str, Any]:
    """Return a self-committed audit without embedding source text or private paths."""

    if _COMMIT.fullmatch(source_commit) is None:
        raise ValueError("source_commit must be a full lowercase Git SHA-1")
    validate_sha256(source_archive_sha256, field="source archive digest")
    _positive_int(audit_job_id, field="audit_job_id")
    if not isinstance(retries, int) or isinstance(retries, bool) or not 0 <= retries <= 10:
        raise ValueError("retries must be an integer between zero and ten")
    if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if matching_cache_dir.resolve() == diagnostic_dir.resolve():
        raise ValueError("matching cache and diagnostic directory must be distinct")
    _prepare_empty_private_directory(matching_cache_dir, label="matching cache")
    _prepare_empty_private_directory(diagnostic_dir, label="diagnostic directory")

    (
        parent,
        parent_file_sha256,
        plan,
        plan_file_sha256,
        screen,
        screen_file_sha256,
        selected_rows,
        reserve_rows,
    ) = _validate_inputs(
        parent_manifest_path=parent_manifest_path,
        expected_parent_file_sha256=expected_parent_file_sha256,
        provisional_plan_path=provisional_plan_path,
        expected_plan_file_sha256=expected_plan_file_sha256,
        fulltext_screen_path=fulltext_screen_path,
        expected_screen_file_sha256=expected_screen_file_sha256,
    )
    run_id, artifact_id, artifact_digest = _workflow_identity(parent)
    selected = [
        _audit_one(
            row,
            client=client,
            retries=retries,
            sleep=sleep,
            matching_cache_dir=matching_cache_dir,
            diagnostic_dir=diagnostic_dir,
        )
        for row in selected_rows
    ]
    reserves = [
        _audit_one(
            row,
            client=client,
            retries=retries,
            sleep=sleep,
            matching_cache_dir=matching_cache_dir,
            diagnostic_dir=diagnostic_dir,
        )
        for row in reserve_rows
    ]
    records = [*selected, *reserves]
    unresolved_count = sum(row["classification"] == "unresolved" for row in records)
    selected_replacement_count = sum(
        row["replacement_required"] is True for row in selected
    )
    valid_reserve_count = sum(row["currently_valid"] is True for row in reserves)
    matching_count = sum(row["cache_bucket"] == "matching_cache" for row in records)
    diagnostic_count = sum(row["cache_bucket"] == "diagnostic" for row in records)
    audit_spec_core = {
        "policy_version": AUDIT_POLICY_VERSION,
        "endpoint_template": FULLTEXT_URL,
        "timeout_seconds": float(timeout_seconds),
        "retries_after_first_attempt": retries,
        "retryable_http_statuses": sorted(RETRYABLE_STATUS_CODES),
        "definitive_unavailable_http_statuses": sorted(_DEFINITIVE_UNAVAILABLE),
        "http_user_agent": http_user_agent or user_agent("frozen-source-pool-audit"),
        "selected_count_expected": len(selected_rows),
        "eligible_reserve_count_expected": len(reserve_rows),
        "ordered_selected_ids_sha256": canonical_sha256(
            [row["document_id"] for row in selected_rows]
        ),
        "ordered_reserve_ids_sha256": canonical_sha256(
            [row["document_id"] for row in reserve_rows]
        ),
    }
    audit_spec = {
        **audit_spec_core,
        "audit_spec_sha256": canonical_sha256(audit_spec_core),
    }
    cache_inventory = [
        {
            "document_id": row["document_id"],
            "cache_bucket": row["cache_bucket"],
            "observed_full_text_sha256": row["observed_full_text_sha256"],
            "observed_size_bytes": row["observed_size_bytes"],
        }
        for row in records
        if row["cache_bucket"] is not None
    ]
    summary = {
        "selected_count": len(selected),
        "eligible_reserve_count": len(reserves),
        "audited_record_count": len(records),
        "selected_split_counts": dict(
            sorted(Counter(row["split"] for row in selected).items())
        ),
        "selected_replacement_required_count": selected_replacement_count,
        "selected_exact_match_count": sum(
            row["classification"] == "current_exact_match" for row in selected
        ),
        "valid_reserve_count": valid_reserve_count,
        "unresolved_count": unresolved_count,
        "matching_cache_file_count": matching_count,
        "diagnostic_file_count": diagnostic_count,
        "sufficient_valid_reserves": (
            unresolved_count == 0 and valid_reserve_count >= selected_replacement_count
        ),
    }
    core = {
        "schema_version": SCHEMA_VERSION,
        "status": "complete" if unresolved_count == 0 else "incomplete",
        "generated_at": generated_at or _utc_now(),
        "audit_job_id": audit_job_id,
        "source_commit": source_commit,
        "source_archive_sha256": source_archive_sha256,
        "original_manifest_sha256": parent["manifest_sha256"],
        "original_manifest_file_sha256": parent_file_sha256,
        "provisional_plan_sha256": plan["plan_sha256"],
        "provisional_plan_file_sha256": plan_file_sha256,
        "fulltext_screen_sha256": canonical_sha256(screen),
        "fulltext_screen_file_sha256": screen_file_sha256,
        "source_workflow_run": run_id,
        "source_workflow_artifact_id": artifact_id,
        "source_workflow_artifact_digest": artifact_digest,
        "audit_spec": audit_spec,
        "model_output_used": False,
        "full_text_included": False,
        "private_paths_recorded": False,
        "selected": selected,
        "eligible_reserves": reserves,
        "summary": summary,
        "cache_inventory_sha256": canonical_sha256(cache_inventory),
    }
    result = {**core, "audit_sha256": canonical_sha256(core)}
    validate_audit_cache(
        result,
        matching_cache_dir=matching_cache_dir,
        diagnostic_dir=diagnostic_dir,
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-source-manifest", type=Path, required=True)
    parser.add_argument("--parent-source-manifest-sha256", required=True)
    parser.add_argument("--provisional-plan", type=Path, required=True)
    parser.add_argument("--provisional-plan-sha256", required=True)
    parser.add_argument("--fulltext-screen", type=Path, required=True)
    parser.add_argument("--fulltext-screen-sha256", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-archive-sha256", required=True)
    parser.add_argument("--audit-job-id", type=int, required=True)
    parser.add_argument("--matching-cache-dir", type=Path, required=True)
    parser.add_argument("--diagnostic-dir", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--retries", type=int, default=5)
    args = parser.parse_args()

    output = args.output_report.resolve()
    inputs = {
        args.parent_source_manifest.resolve(),
        args.provisional_plan.resolve(),
        args.fulltext_screen.resolve(),
    }
    directories = {
        args.matching_cache_dir.resolve(),
        args.diagnostic_dir.resolve(),
    }
    if output in inputs or output in directories or len(directories) != 2:
        raise SystemExit("audit outputs must be distinct and must not overwrite inputs")
    if output.exists() or output.is_symlink():
        raise SystemExit("audit report output already exists")

    audit_user_agent = user_agent("frozen-source-pool-audit")
    with httpx.Client(
        timeout=args.timeout,
        headers={"User-Agent": audit_user_agent},
        follow_redirects=True,
    ) as client:
        report = audit_frozen_source_pool(
            parent_manifest_path=args.parent_source_manifest,
            expected_parent_file_sha256=args.parent_source_manifest_sha256,
            provisional_plan_path=args.provisional_plan,
            expected_plan_file_sha256=args.provisional_plan_sha256,
            fulltext_screen_path=args.fulltext_screen,
            expected_screen_file_sha256=args.fulltext_screen_sha256,
            source_commit=args.source_commit,
            source_archive_sha256=args.source_archive_sha256,
            audit_job_id=args.audit_job_id,
            matching_cache_dir=args.matching_cache_dir,
            diagnostic_dir=args.diagnostic_dir,
            client=client,
            timeout_seconds=args.timeout,
            retries=args.retries,
            http_user_agent=audit_user_agent,
        )
    atomic_write_json(args.output_report, report)
    print(
        json.dumps(
            {
                "status": report["status"],
                **report["summary"],
                "audit_sha256": report["audit_sha256"],
                "cache_inventory_sha256": report["cache_inventory_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
