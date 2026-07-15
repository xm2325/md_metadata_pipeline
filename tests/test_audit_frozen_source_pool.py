from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path
from typing import Any

import httpx
import pytest

from mdmeta.benchmark import canonical_sha256
from scripts.audit_frozen_source_pool import (
    audit_frozen_source_pool,
    validate_audit_cache,
    validate_audit_report,
)


GENERATED_AT = "2026-07-15T18:00:00Z"
SPLITS = ("development", "validation", "locked_test")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _xml(document_id: str, body: str = "frozen body") -> bytes:
    return (
        "<article><front><article-meta>"
        f"<article-id pub-id-type='pmcid'>{document_id}</article-id>"
        "</article-meta></front><body><sec><title>Methods</title>"
        f"<p>{body}</p></sec></body></article>"
    ).encode()


def _write_json(path: Path, payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, indent=2, sort_keys=True).encode()
    path.write_bytes(encoded)
    return _sha256(encoded)


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


def _fixture(tmp_path: Path, reserve_count: int = 18) -> dict[str, Any]:
    selected_ids = [f"PMC{index:06d}" for index in range(1, 61)]
    reserve_ids = [f"PMC{index:06d}" for index in range(61, 61 + reserve_count)]
    ordered_ids = [*selected_ids, *reserve_ids]
    payloads = {document_id: _xml(document_id) for document_id in ordered_ids}
    screening_pool_sha256 = "c" * 64
    screen = {
        "study_id": "screen-pool",
        "study_status": "provisional_temporal_isolation",
        "plan_sha256": screening_pool_sha256,
        "screening_scope": "machine_triage_not_human_eligibility",
        "records": [
            {
                "document_id": document_id,
                "split": "development",
                "full_text_sha256": _sha256(payloads[document_id]),
                "xml_size_bytes": len(payloads[document_id]),
                "machine_screen_status": "strong_biomolecular_protocol_signal",
                "machine_eligible_for_annotation": True,
            }
            for document_id in ordered_ids
        ],
        "failures": [],
    }
    screen_sha256 = canonical_sha256(screen)
    selected_articles = [
        {
            "document_id": document_id,
            "title": f"Article {document_id}",
            "source_uri": f"https://europepmc.org/articles/{document_id}",
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
        "development": selected_articles[:30],
        "validation": selected_articles[30:40],
        "locked_test": selected_articles[40:],
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
    split_by_id = {
        row["document_id"]: split
        for split in SPLITS
        for row in plan[split]
    }
    parent_core = {
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
                "source_uri": f"https://europepmc.org/articles/{document_id}",
                "full_text_sha256": _sha256(payloads[document_id]),
            }
            for document_id in selected_ids
        ],
    }
    parent = {**parent_core, "manifest_sha256": canonical_sha256(parent_core)}
    parent_path = tmp_path / "parent.json"
    plan_path = tmp_path / "plan.json"
    screen_path = tmp_path / "screen.json"
    arguments = {
        "parent_manifest_path": parent_path,
        "expected_parent_file_sha256": _write_json(parent_path, parent),
        "provisional_plan_path": plan_path,
        "expected_plan_file_sha256": _write_json(plan_path, plan),
        "fulltext_screen_path": screen_path,
        "expected_screen_file_sha256": _write_json(screen_path, screen),
        "source_commit": "a" * 40,
        "source_archive_sha256": "b" * 64,
        "audit_job_id": 185800,
        "matching_cache_dir": tmp_path / "matching-cache",
        "diagnostic_dir": tmp_path / "diagnostic",
        "timeout_seconds": 10.0,
        "retries": 0,
        "sleep": lambda _: None,
        "generated_at": GENERATED_AT,
        "http_user_agent": "mdmeta-audit-test/1",
    }
    return {
        "arguments": arguments,
        "parent": parent,
        "plan": plan,
        "screen": screen,
        "payloads": payloads,
        "selected_ids": selected_ids,
        "reserve_ids": reserve_ids,
        "ordered_ids": ordered_ids,
    }


def _client(
    case: dict[str, Any],
    overrides: dict[str, Any] | None = None,
) -> tuple[httpx.Client, list[str], dict[str, int]]:
    overrides = overrides or {}
    calls: list[str] = []
    attempts: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        document_id = request.url.path.rstrip("/").split("/")[-2]
        calls.append(document_id)
        attempts[document_id] = attempts.get(document_id, 0) + 1
        response = overrides.get(document_id, case["payloads"][document_id])
        if callable(response):
            response = response(attempts[document_id], request)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, tuple):
            status_code, content, headers = response
            return httpx.Response(
                status_code,
                content=content,
                headers=headers,
                request=request,
            )
        return httpx.Response(200, content=response, request=request)

    return httpx.Client(transport=httpx.MockTransport(handler)), calls, attempts


def _audit(case: dict[str, Any], client: httpx.Client, **updates) -> dict[str, Any]:
    arguments = dict(case["arguments"])
    arguments.update(updates)
    return audit_frozen_source_pool(client=client, **arguments)


def test_complete_exact_audit_requests_every_selected_and_ordered_reserve(
    tmp_path: Path,
) -> None:
    case = _fixture(tmp_path)
    client, calls, _ = _client(case)
    with client:
        report = _audit(case, client)

    assert report["status"] == "complete"
    assert calls == case["ordered_ids"]
    assert report["summary"]["selected_count"] == 60
    assert report["summary"]["eligible_reserve_count"] == 18
    assert report["summary"]["audited_record_count"] == 78
    assert report["summary"]["selected_split_counts"] == {
        "development": 30,
        "locked_test": 20,
        "validation": 10,
    }
    assert report["summary"]["selected_exact_match_count"] == 60
    assert report["summary"]["valid_reserve_count"] == 18
    assert report["summary"]["unresolved_count"] == 0
    assert [row["document_id"] for row in report["eligible_reserves"]] == (
        case["reserve_ids"]
    )
    assert [row["original_reserve_rank"] for row in report["eligible_reserves"]] == list(
        range(1, 19)
    )
    assert len(list(case["arguments"]["matching_cache_dir"].iterdir())) == 78
    assert list(case["arguments"]["diagnostic_dir"].iterdir()) == []
    first_cached = case["arguments"]["matching_cache_dir"] / f"{case['selected_ids'][0]}.xml"
    assert stat.S_IMODE(case["arguments"]["matching_cache_dir"].stat().st_mode) == 0o700
    assert stat.S_IMODE(case["arguments"]["diagnostic_dir"].stat().st_mode) == 0o700
    assert stat.S_IMODE(first_cached.stat().st_mode) == 0o600


def test_drift_and_wrong_identity_use_only_diagnostic_cache_and_report_no_text_or_paths(
    tmp_path: Path,
) -> None:
    case = _fixture(tmp_path, reserve_count=3)
    drifted_id = case["selected_ids"][4]
    wrong_identity_id = case["reserve_ids"][1]
    drifted_payload = _xml(drifted_id, "CURRENT SECRET DRIFTED BODY")
    wrong_identity_payload = _xml("PMC999999", "WRONG SECRET IDENTITY BODY")
    client, _, _ = _client(
        case,
        {
            drifted_id: drifted_payload,
            wrong_identity_id: wrong_identity_payload,
        },
    )
    with client:
        report = _audit(case, client)

    selected = {row["document_id"]: row for row in report["selected"]}
    reserves = {row["document_id"]: row for row in report["eligible_reserves"]}
    assert selected[drifted_id]["classification"] == "frozen_payload_drift"
    assert selected[drifted_id]["replacement_required"] is True
    assert selected[drifted_id]["observed_full_text_sha256"] == _sha256(
        drifted_payload
    )
    assert reserves[wrong_identity_id]["classification"] == "invalid_pmcid_identity"
    assert reserves[wrong_identity_id]["pmcid_identity_valid"] is False
    assert report["summary"]["selected_replacement_required_count"] == 1
    assert report["summary"]["valid_reserve_count"] == 2
    assert report["summary"]["diagnostic_file_count"] == 2
    assert not (case["arguments"]["matching_cache_dir"] / f"{drifted_id}.xml").exists()
    assert not (
        case["arguments"]["matching_cache_dir"] / f"{wrong_identity_id}.xml"
    ).exists()
    assert (
        case["arguments"]["diagnostic_dir"] / f"{drifted_id}.current.xml"
    ).read_bytes() == drifted_payload
    assert (
        case["arguments"]["diagnostic_dir"] / f"{wrong_identity_id}.current.xml"
    ).read_bytes() == wrong_identity_payload
    serialized = json.dumps(report, sort_keys=True)
    assert "CURRENT SECRET DRIFTED BODY" not in serialized
    assert "WRONG SECRET IDENTITY BODY" not in serialized
    assert str(tmp_path) not in serialized
    assert report["full_text_included"] is False
    assert report["private_paths_recorded"] is False
    assert report["model_output_used"] is False
    assert report["audit_sha256"] == canonical_sha256(
        {key: value for key, value in report.items() if key != "audit_sha256"}
    )


def test_transient_retry_recovers_without_changing_audit_order(tmp_path: Path) -> None:
    case = _fixture(tmp_path, reserve_count=2)
    transient_id = case["selected_ids"][0]

    def transient(attempt: int, request: httpx.Request):
        if attempt == 1:
            return 503, b"temporary", {"Retry-After": "0"}
        return case["payloads"][transient_id]

    client, calls, attempts = _client(case, {transient_id: transient})
    delays: list[float] = []
    with client:
        report = _audit(case, client, retries=1, sleep=delays.append)

    assert report["status"] == "complete"
    assert attempts[transient_id] == 2
    assert calls[:2] == [transient_id, transient_id]
    assert calls[2:] == case["ordered_ids"][1:]
    assert delays == [0.0]
    assert report["selected"][0]["attempts"] == 2
    assert report["selected"][0]["classification"] == "current_exact_match"


def test_unresolved_source_continues_through_entire_pool_and_marks_report_incomplete(
    tmp_path: Path,
) -> None:
    case = _fixture(tmp_path, reserve_count=2)
    unresolved_id = case["selected_ids"][1]

    def unavailable(attempt: int, request: httpx.Request):
        return httpx.ConnectError(
            f"transient network failure {attempt}",
            request=request,
        )

    client, calls, attempts = _client(
        case,
        {unresolved_id: unavailable},
    )
    with client:
        report = _audit(case, client, retries=1)

    assert report["status"] == "incomplete"
    assert report["summary"]["unresolved_count"] == 1
    assert attempts[unresolved_id] == 2
    assert set(calls) == set(case["ordered_ids"])
    assert calls[-1] == case["reserve_ids"][-1]
    unresolved = next(
        row for row in report["selected"] if row["document_id"] == unresolved_id
    )
    assert unresolved["classification"] == "unresolved"
    assert unresolved["replacement_required"] is None
    assert unresolved["cache_bucket"] is None


def test_rejects_bad_external_artifact_digest_before_any_request(tmp_path: Path) -> None:
    case = _fixture(tmp_path, reserve_count=2)
    client, calls, _ = _client(case)
    with client, pytest.raises(ValueError, match="file SHA-256"):
        _audit(case, client, expected_plan_file_sha256="0" * 64)

    assert calls == []


def test_rejects_original_plan_order_that_differs_from_parent(tmp_path: Path) -> None:
    case = _fixture(tmp_path, reserve_count=2)
    plan = case["plan"]
    plan["development"][0], plan["development"][1] = (
        plan["development"][1],
        plan["development"][0],
    )
    plan["plan_sha256"] = canonical_sha256(_plan_core(plan))
    parent = case["parent"]
    parent["plan_sha256"] = plan["plan_sha256"]
    parent_core = {
        key: value for key, value in parent.items() if key != "manifest_sha256"
    }
    parent["manifest_sha256"] = canonical_sha256(parent_core)
    plan_sha256 = _write_json(case["arguments"]["provisional_plan_path"], plan)
    parent_sha256 = _write_json(case["arguments"]["parent_manifest_path"], parent)
    client, calls, _ = _client(case)
    with client, pytest.raises(ValueError, match="source order differs"):
        _audit(
            case,
            client,
            expected_plan_file_sha256=plan_sha256,
            expected_parent_file_sha256=parent_sha256,
        )

    assert calls == []


def test_wrong_pmcid_is_classified_and_does_not_stop_later_requests(tmp_path: Path) -> None:
    case = _fixture(tmp_path, reserve_count=2)
    wrong_id = case["selected_ids"][0]
    wrong_payload = _xml("PMC999999")
    client, calls, _ = _client(case, {wrong_id: wrong_payload})
    with client:
        report = _audit(case, client)

    first = report["selected"][0]
    assert first["document_id"] == wrong_id
    assert first["classification"] == "invalid_pmcid_identity"
    assert first["replacement_required"] is True
    assert first["cache_bucket"] == "diagnostic"
    assert calls == case["ordered_ids"]
    assert report["status"] == "complete"


def test_verifiers_reject_tampered_report_and_private_cache(tmp_path: Path) -> None:
    case = _fixture(tmp_path, reserve_count=2)
    client, _, _ = _client(case)
    with client:
        report = _audit(case, client)

    tampered_report = json.loads(json.dumps(report))
    tampered_report["model_output_used"] = True
    with pytest.raises(ValueError, match="commitment"):
        validate_audit_report(tampered_report, require_complete=True)

    semantically_tampered = json.loads(json.dumps(report))
    semantically_tampered["selected"][0]["frozen_payload_match"] = False
    semantically_tampered["audit_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in semantically_tampered.items()
            if key != "audit_sha256"
        }
    )
    with pytest.raises(ValueError, match="frozen-payload match"):
        validate_audit_report(semantically_tampered, require_complete=True)

    first_id = case["selected_ids"][0]
    cache_path = case["arguments"]["matching_cache_dir"] / f"{first_id}.xml"
    original = cache_path.read_bytes()
    cache_path.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    with pytest.raises(ValueError, match="SHA-256"):
        validate_audit_cache(
            report,
            matching_cache_dir=case["arguments"]["matching_cache_dir"],
            diagnostic_dir=case["arguments"]["diagnostic_dir"],
            require_complete=True,
        )
