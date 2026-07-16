from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from mdmeta.benchmark import canonical_sha256


ROOT = Path(__file__).parents[1]
STUDY = ROOT / "study" / "independent_100"
EVIDENCE_FILES = (
    "scale80_source_manifest.json",
    "scale80_gpu_summary.json",
    "scale80_gpu_hardware_summary.json",
    "scale80_integration_summary.json",
    "model_protocol_freeze.json",
)
SHA256 = re.compile(r"[0-9a-f]{64}")


def _read(name: str) -> dict:
    payload = json.loads((STUDY / name).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _sha256(name: str) -> str:
    return hashlib.sha256((STUDY / name).read_bytes()).hexdigest()


def _assert_commitment(payload: dict, field: str) -> None:
    core = {key: value for key, value in payload.items() if key != field}
    assert payload[field] == canonical_sha256(core)


def test_public_scale80_evidence_is_hash_bound_and_source_free() -> None:
    report = _read("run_report.json")
    expected_files = report["scale80_execution"]["public_evidence_file_sha256"]
    assert set(expected_files) == set(EVIDENCE_FILES)
    assert {name: _sha256(name) for name in EVIDENCE_FILES} == expected_files

    for name in EVIDENCE_FILES:
        text = (STUDY / name).read_text(encoding="utf-8")
        assert "/scratch/" not in text
        assert "/projappl/" not in text
        assert "xiaomei" not in text
        assert "private_key" not in text.casefold()

    scale_manifest = _read("scale80_source_manifest.json")
    gpu = _read("scale80_gpu_summary.json")
    hardware = _read("scale80_gpu_hardware_summary.json")
    integration = _read("scale80_integration_summary.json")
    freeze = _read("model_protocol_freeze.json")

    _assert_commitment(scale_manifest, "manifest_sha256")
    _assert_commitment(integration, "result_sha256")
    _assert_commitment(freeze, "freeze_sha256")
    assert "tasks" not in gpu["batch"]
    assert "response" not in gpu["batch"]

    manifest_ids = [row["document_id"] for row in scale_manifest["articles"]]
    gpu_ids = gpu["corpus"]["selected_document_ids"]
    integration_ids = [row["document_id"] for row in integration["record_index"]]
    assert manifest_ids == gpu_ids == integration_ids
    assert len(manifest_ids) == len(set(manifest_ids)) == 80
    assert {row["split"] for row in scale_manifest["articles"]} == {"scale"}
    assert scale_manifest["contains_human_reference_labels"] is False
    assert scale_manifest["contains_locked_test_articles"] is False
    assert scale_manifest["model_output_used_for_selection"] is False

    gate = gpu["batch"]["no_task_article_gate"]
    assert gate == integration["no_task_article_gate"]
    assert gate["selected_article_count"] == 80
    assert gate["no_task_article_count"] == 1
    assert gate["maximum_no_task_article_count"] == 2
    assert gate["passed"] is True
    assert gpu["configuration"]["maximum_no_task_article_fraction"] == 0.025
    assert gpu["status"] == integration["status"] == "pass"
    assert gpu["batch"]["task_count"] == gpu["batch"]["task_count_classified"] == 1216
    assert integration["article_count_requested"] == 80
    assert integration["summary"]["article_count_succeeded"] == 80
    assert integration["summary"]["failure_count"] == 0
    assert integration["database"]["portable_single_file_snapshot"] is True
    assert integration["identifier_integration_gate"]["passed"] is True

    assert gpu["result_sha256"] == freeze["scale_result_sha256"]
    assert integration["result_sha256"] == freeze["scale_integration_result_sha256"]
    bound_files = freeze["scale_evidence_file_sha256"]
    assert bound_files["scale_source_manifest"] == _sha256(
        "scale80_source_manifest.json"
    )
    assert bound_files["gpu_summary"] == _sha256("scale80_gpu_hardware_summary.json")
    assert bound_files["scale_cpu_integration_result"] == _sha256(
        "scale80_integration_summary.json"
    )
    assert SHA256.fullmatch(bound_files["scale_gpu_result"])
    assert hardware["visible_gpu_count"] == 1
    assert hardware["max_gpu_utilization_percent"] > 0

    assert freeze["study_status"] == (
        "scale80_passed_model_protocol_frozen_pre_gold_inference"
    )
    assert freeze["scale_article_count"] == 80
    assert freeze["contains_locked_test_articles"] is False
    assert freeze["contains_human_reference_labels"] is False
    assert freeze["gold_predictions_generated"] is False
    assert freeze["gold_prediction_authorized"] is False
    assert freeze["passed"] is True
    assert gpu["accuracy_evaluated"] is integration["accuracy_evaluated"] is False
    assert gpu["human_reference_used"] is integration["human_reference_used"] is False
