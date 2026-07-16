from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from mdmeta.benchmark import canonical_sha256
from mdmeta.llm_adapter import PROMPT_CONTRACT_VERSION, prompt_contract_sha256
from mdmeta.llm_batch import (
    RESPONSE_SCHEMA_FILENAME,
    RESPONSE_SCHEMA_VERSION,
    SCHEMA_VERSION as MODEL_BATCH_SCHEMA_VERSION,
    load_committed_response_schema,
)
from mdmeta.model_protocol_freeze import (
    FROZEN_IMPLEMENTATION_PATHS,
    authorize_gold20_prediction,
    freeze_model_protocol,
)
from scripts.audit_independent_plan import audit_independent_plan
from scripts.finalize_screened_plan import finalize_screened_plan

ROOT = Path(__file__).parents[1]
SOURCE_COMMIT = "c" * 40
ARCHIVE_BYTES = b"verified source archive fixture"
ARCHIVE_SHA256 = hashlib.sha256(ARCHIVE_BYTES).hexdigest()


def _article(index: int) -> dict:
    return {
        "document_id": f"PMC{index:06d}",
        "title": f"Article {index}",
        "source_uri": f"https://example.test/PMC{index:06d}",
        "software_family": ("gromacs", "amber", "namd", "unknown")[index % 4],
        "licence": "CC BY",
    }


def _study() -> tuple[dict, dict, dict]:
    pool = {
        "plan_sha256": "a" * 64,
        "development": [_article(index) for index in range(110)],
        "validation": [],
        "locked_test": [],
    }
    screen = {
        "plan_sha256": "a" * 64,
        "screening_scope": "machine_triage_not_human_eligibility",
        "records": [
            {
                "document_id": f"PMC{index:06d}",
                "full_text_sha256": f"{index + 1:064x}",
                "machine_eligible_for_annotation": True,
                "machine_screen_status": "strong_biomolecular_protocol_signal",
                "article_type": "research-article",
            }
            for index in range(110)
        ],
    }
    plan = finalize_screened_plan(
        pool,
        screen,
        development_size=80,
        validation_size=0,
        locked_test_size=20,
        study_id="mdmeta-independent-100-v1",
        study_status="independent_100_machine_screened_unreviewed",
        split_strategy="locked_test_stratified",
        split_seed=3997,
    )
    audit = audit_independent_plan(
        plan,
        {"document_ids": ["PMC999999"], "registry_sha256": "b" * 64},
    )
    return plan, screen, audit


def _scale_manifest(plan: dict, screen: dict, audit: dict) -> dict:
    sources = {row["document_id"]: row["full_text_sha256"] for row in screen["records"]}
    core = {
        "schema_version": "mdmeta.independent-scale-source.v1",
        "study_id": "mdmeta-independent-100-scale80-v1",
        "study_status": "independent_scale80_frozen_preinference",
        "parent_study_id": plan["study_id"],
        "parent_plan_sha256": plan["plan_sha256"],
        "parent_audit_sha256": audit["audit_sha256"],
        "source_screen_sha256": plan["screen_sha256"],
        "contains_locked_test_articles": False,
        "contains_human_reference_labels": False,
        "model_output_used_for_selection": False,
        "articles": [
            {
                "document_id": row["document_id"],
                "split": "scale",
                "source_uri": row["source_uri"],
                "full_text_sha256": sources[row["document_id"]],
            }
            for row in plan["development"]
        ],
    }
    return {**core, "manifest_sha256": canonical_sha256(core)}


def _model_manifest() -> dict:
    core = {
        "schema_version": "mdmeta.huggingface-model-snapshot.v1",
        "repo_id": "test/tiny-model",
        "revision": "d" * 40,
        "tokenizer_revision": "d" * 40,
        "license": "apache-2.0",
        "gated": False,
        "trust_remote_code": False,
        "staged_at": "2026-07-16T00:00:00Z",
        "runtime": {"python": "test"},
        "file_count": 2,
        "total_size_bytes": 2,
        "weight_file_count": 1,
        "weight_size_bytes": 1,
        "files": [
            {"path": "config.json", "size_bytes": 1, "sha256": "1" * 64},
            {"path": "model.safetensors", "size_bytes": 1, "sha256": "2" * 64},
        ],
    }
    return {**core, "manifest_sha256": canonical_sha256(core)}


def _scale_result(scale_manifest: dict, model_manifest: dict) -> dict:
    response_schema_sha256 = canonical_sha256(
        load_committed_response_schema(ROOT / "schemas" / RESPONSE_SCHEMA_FILENAME)
    )
    core = {
        "schema_version": MODEL_BATCH_SCHEMA_VERSION,
        "status": "pass",
        "started_at": "2026-07-16T00:00:00Z",
        "completed_at": "2026-07-16T00:05:00Z",
        "accuracy_evaluated": False,
        "human_reference_used": False,
        "interpretation": "operational scale evidence only",
        "source": {"commit": SOURCE_COMMIT, "archive_sha256": ARCHIVE_SHA256},
        "slurm": {"job_id": "1", "partition": "gputest"},
        "runtime": {"python": "3.12", "vllm": "0.19.1", "torch": "2.10"},
        "model": {
            "repo_id": model_manifest["repo_id"],
            "revision": model_manifest["revision"],
            "tokenizer_revision": model_manifest["tokenizer_revision"],
            "license": model_manifest["license"],
            "snapshot_manifest_sha256": model_manifest["manifest_sha256"],
        },
        "corpus": {
            "study_id": scale_manifest["study_id"],
            "study_status": scale_manifest["study_status"],
            "manifest_sha256": scale_manifest["manifest_sha256"],
            "manifest_article_count": 80,
            "selected_article_count": 80,
            "selection_method": "manifest_prefix",
            "selected_document_ids": [
                row["document_id"] for row in scale_manifest["articles"]
            ],
            "selected_split_counts": {"scale": 80},
        },
        "configuration": {
            "batch_size": 32,
            "max_tokens": 4096,
            "max_model_len": 16384,
            "gpu_memory_utilization": 0.8,
            "seed": 3997,
            "temperature": 0.0,
            "determinism_check": True,
            "maximum_generation_rejection_fraction": 0.01,
            "maximum_no_task_article_fraction": 0.025,
            "source_snapshot_policy": "private_cache_with_frozen_sha256_gate",
            "network_allowed_for_jats": False,
            "task_unit": "one_protocol_relevant_jats_paragraph",
        },
        "jats": {
            "article_count": 80,
            "cache_hit_count": 80,
            "downloaded_count": 0,
            "all_frozen_sha256_matched": True,
        },
        "batch": {
            "response_schema_version": RESPONSE_SCHEMA_VERSION,
            "response_schema_sha256": response_schema_sha256,
            "prompt_contract_version": PROMPT_CONTRACT_VERSION,
            "prompt_contract_sha256": prompt_contract_sha256(),
            "task_count": 800,
            "task_count_classified": 800,
            "classification_counts": {"accepted": 800},
            "per_article": {
                row["document_id"]: {"paragraph_count": 10}
                for row in scale_manifest["articles"]
            },
            "no_task_article_gate": {
                "selected_article_count": 80,
                "no_task_article_count": 0,
                "maximum_no_task_article_count": 2,
                "no_task_article_ids": [],
                "treatment": "retained_as_explicit_zero_event_record",
                "passed": True,
            },
            "determinism_check": {"performed": True, "identical": True},
        },
    }
    return {**core, "result_sha256": canonical_sha256(core)}


def _integration(scale_manifest: dict, scale_result: dict) -> dict:
    core = {
        "schema_version": "mdmeta.model-backed-integration.v1",
        "status": "pass",
        "accuracy_evaluated": False,
        "human_reference_used": False,
        "source_manifest_sha256": scale_manifest["manifest_sha256"],
        "model_result_sha256": scale_result["result_sha256"],
        "source": scale_result["source"],
        "article_count_requested": 80,
        "no_task_article_gate": scale_result["batch"]["no_task_article_gate"],
        "database": {"portable_single_file_snapshot": True},
        "identifier_integration_gate": {"passed": True},
        "record_index": [
            {"document_id": row["document_id"]} for row in scale_manifest["articles"]
        ],
    }
    return {**core, "result_sha256": canonical_sha256(core)}


def _source_root(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    root.mkdir()
    (root / ".mdmeta-source-commit").write_text(SOURCE_COMMIT + "\n", encoding="utf-8")
    for relative in FROZEN_IMPLEMENTATION_PATHS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"frozen fixture for {relative}\n", encoding="utf-8")
    return root


def _freeze_fixture(tmp_path: Path) -> tuple[dict, dict, dict, dict, dict, dict]:
    plan, screen, audit = _study()
    scale_manifest = _scale_manifest(plan, screen, audit)
    model_manifest = _model_manifest()
    scale_result = _scale_result(scale_manifest, model_manifest)
    integration = _integration(scale_manifest, scale_result)
    frozen = freeze_model_protocol(
        scale_manifest,
        scale_result,
        integration,
        model_manifest,
        source_root=_source_root(tmp_path),
        source_archive_sha256=ARCHIVE_SHA256,
        scale_manifest_file_sha256="1" * 64,
        scale_result_file_sha256="2" * 64,
        scale_integration_result_file_sha256="3" * 64,
        model_manifest_file_sha256="4" * 64,
        gpu_environment_file_sha256="5" * 64,
        gpu_summary_file_sha256="6" * 64,
        integration_environment_file_sha256="7" * 64,
        integration_database_file_sha256="8" * 64,
        frozen_at_utc="2026-07-16T01:00:00Z",
        operator_run_id="scale80-freeze-1",
    )
    return plan, screen, audit, scale_manifest, scale_result, frozen


def test_scale80_result_freezes_prompt_schema_model_code_and_evaluator(tmp_path: Path) -> None:
    _, _, _, _, _, frozen = _freeze_fixture(tmp_path)
    assert frozen["scale_article_count"] == 80
    assert frozen["prompt_contract"]["sha256"] == prompt_contract_sha256()
    assert len(frozen["implementation_files"]) == len(FROZEN_IMPLEMENTATION_PATHS)
    assert "src/mdmeta/event_evaluation.py" in {
        row["path"] for row in frozen["implementation_files"]
    }
    assert frozen["contains_locked_test_articles"] is False
    assert frozen["contains_human_reference_labels"] is False
    assert frozen["gold_prediction_authorized"] is False


def test_model_freeze_rejects_prompt_contract_drift(tmp_path: Path) -> None:
    plan, screen, audit = _study()
    scale_manifest = _scale_manifest(plan, screen, audit)
    model_manifest = _model_manifest()
    scale_result = _scale_result(scale_manifest, model_manifest)
    scale_result["batch"]["prompt_contract_sha256"] = "0" * 64
    scale_result["result_sha256"] = canonical_sha256(
        {key: value for key, value in scale_result.items() if key != "result_sha256"}
    )
    with pytest.raises(ValueError, match="prompt or response-schema"):
        freeze_model_protocol(
            scale_manifest,
            scale_result,
            _integration(scale_manifest, scale_result),
            model_manifest,
            source_root=_source_root(tmp_path),
            source_archive_sha256=ARCHIVE_SHA256,
            scale_manifest_file_sha256="1" * 64,
            scale_result_file_sha256="2" * 64,
            scale_integration_result_file_sha256="3" * 64,
            model_manifest_file_sha256="4" * 64,
            gpu_environment_file_sha256="5" * 64,
            gpu_summary_file_sha256="6" * 64,
            integration_environment_file_sha256="7" * 64,
            integration_database_file_sha256="8" * 64,
            frozen_at_utc="2026-07-16T01:00:00Z",
            operator_run_id="scale80-freeze-1",
        )


def _reference_receipt(plan: dict, audit: dict) -> dict:
    core = {
        "schema_version": "mdmeta.gold-reference-public-receipt.v1",
        "study_id": plan["study_id"],
        "study_status": "gold20_dual_human_adjudicated_frozen",
        "plan_sha256": plan["plan_sha256"],
        "plan_audit_sha256": audit["audit_sha256"],
        "screen_sha256": plan["screen_sha256"],
        "submission_commitments_sha256": ["1" * 64, "2" * 64],
        "adjudication_sha256": "3" * 64,
        "reference_sha256": "4" * 64,
        "frozen_at_utc": "2026-07-16T02:00:00Z",
        "operator_run_id": "gold-freeze-1",
        "article_count": 20,
        "annotator_count": 2,
        "coverage_complete": True,
        "all_disagreements_resolved": True,
        "human_reference": True,
        "contains_model_predictions": False,
        "labels_disclosed": False,
        "label_statistics_disclosed": False,
        "passed": True,
    }
    return {**core, "receipt_sha256": canonical_sha256(core)}


def test_gold20_manifest_is_authorized_only_after_both_freezes(tmp_path: Path) -> None:
    plan, screen, audit, _, _, frozen = _freeze_fixture(tmp_path)
    gold = authorize_gold20_prediction(
        plan,
        screen,
        audit,
        frozen,
        _reference_receipt(plan, audit),
        authorized_at_utc="2026-07-16T03:00:00Z",
        operator_run_id="gold20-authorization-1",
    )
    assert gold["article_count"] == 20
    assert {row["document_id"] for row in gold["articles"]} == {
        row["document_id"] for row in plan["locked_test"]
    }
    assert {row["split"] for row in gold["articles"]} == {"gold"}
    assert gold["contains_human_reference_labels"] is False
    assert gold["contains_model_predictions"] is False
    assert "reference_sha256" not in gold


def test_gold20_authorization_rejects_incomplete_human_receipt(tmp_path: Path) -> None:
    plan, screen, audit, _, _, frozen = _freeze_fixture(tmp_path)
    receipt = _reference_receipt(plan, audit)
    receipt["coverage_complete"] = False
    receipt["receipt_sha256"] = canonical_sha256(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )
    with pytest.raises(ValueError, match="receipt is incomplete"):
        authorize_gold20_prediction(
            plan,
            screen,
            audit,
            frozen,
            receipt,
            authorized_at_utc="2026-07-16T03:00:00Z",
            operator_run_id="gold20-authorization-1",
        )
