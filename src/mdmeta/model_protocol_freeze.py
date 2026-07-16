from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

from .benchmark import canonical_sha256
from .gold_reference import validate_gold_source_contract
from .llm_adapter import PROMPT_CONTRACT_VERSION, prompt_contract_sha256
from .llm_batch import (
    RESPONSE_SCHEMA_FILENAME,
    RESPONSE_SCHEMA_VERSION,
    SCHEMA_VERSION as MODEL_BATCH_SCHEMA_VERSION,
    build_no_task_article_gate,
    load_committed_response_schema,
)

FROZEN_IMPLEMENTATION_PATHS = (
    "constraints/hpc-stage.txt",
    "hpc/roihu/llm_extract.sbatch",
    "hpc/roihu/model_integration.sbatch",
    "hpc/roihu/stage_inputs.sbatch",
    "hpc/roihu/stage_model.py",
    "schemas/llm-event-response-v3.schema.json",
    "scripts/evaluate_protocol_events.py",
    "scripts/freeze_independent_model.py",
    "scripts/gold_reference_gate.py",
    "scripts/run_llm_protocol_batch.py",
    "scripts/run_model_backed_integration.py",
    "scripts/stage_frozen_jats.py",
    "src/mdmeta/benchmark.py",
    "src/mdmeta/event_evaluation.py",
    "src/mdmeta/gold_reference.py",
    "src/mdmeta/integration.py",
    "src/mdmeta/llm_adapter.py",
    "src/mdmeta/llm_batch.py",
    "src/mdmeta/model_snapshot.py",
    "src/mdmeta/model_protocol_freeze.py",
    "src/mdmeta/models.py",
    "src/mdmeta/protocol_events.py",
)


def _is_lower_hex(value: object, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def sha256_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"evidence path must be a regular non-symlink file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _check_commitment(payload: dict[str, Any], field: str) -> None:
    core = {key: value for key, value in payload.items() if key != field}
    if payload.get(field) != canonical_sha256(core):
        raise ValueError(f"{field} commitment is invalid")


def _parse_utc(value: str, field: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field} must be RFC 3339") from error
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
        or parsed.utcoffset().total_seconds() != 0
    ):
        raise ValueError(f"{field} must be expressed in UTC")


def _implementation_inventory(source_root: Path, source_commit: str) -> list[dict[str, Any]]:
    if source_root.is_symlink() or not source_root.is_dir():
        raise ValueError("source root must be a real directory")
    marker = source_root / ".mdmeta-source-commit"
    if marker.is_symlink() or not marker.is_file():
        raise ValueError("verified source root lacks .mdmeta-source-commit")
    if marker.read_text(encoding="utf-8").strip() != source_commit:
        raise ValueError("source root commit marker differs from the model result")
    rows: list[dict[str, Any]] = []
    for relative in FROZEN_IMPLEMENTATION_PATHS:
        path = source_root / relative
        nested = source_root
        has_symlink = False
        for part in Path(relative).parts:
            nested = nested / part
            has_symlink = has_symlink or nested.is_symlink()
        if has_symlink or not path.is_file():
            raise ValueError(f"frozen implementation file is missing or a symlink: {relative}")
        rows.append(
            {
                "path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return rows


def _validate_scale_manifest(scale_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    _check_commitment(scale_manifest, "manifest_sha256")
    if scale_manifest.get("schema_version") != "mdmeta.independent-scale-source.v1":
        raise ValueError("unsupported independent scale source schema")
    if (
        scale_manifest.get("contains_locked_test_articles") is not False
        or scale_manifest.get("contains_human_reference_labels") is not False
        or scale_manifest.get("model_output_used_for_selection") is not False
    ):
        raise ValueError("scale source crosses the locked-test or label boundary")
    articles = scale_manifest.get("articles")
    if not isinstance(articles, list) or len(articles) != 80:
        raise ValueError("model freeze requires exactly 80 scale articles")
    identifiers = [row.get("document_id") for row in articles]
    if len(set(identifiers)) != 80 or any(row.get("split") != "scale" for row in articles):
        raise ValueError("scale source identifiers or split labels are invalid")
    return articles


def _validate_model_manifest(model_manifest: dict[str, Any]) -> None:
    _check_commitment(model_manifest, "manifest_sha256")
    if model_manifest.get("schema_version") != "mdmeta.huggingface-model-snapshot.v1":
        raise ValueError("unsupported model snapshot manifest")
    revision = model_manifest.get("revision")
    if not _is_lower_hex(revision, 40) or model_manifest.get("tokenizer_revision") != revision:
        raise ValueError("model and tokenizer revisions are not one immutable commit")
    if (
        not isinstance(model_manifest.get("repo_id"), str)
        or not model_manifest["repo_id"].strip()
        or not isinstance(model_manifest.get("license"), str)
        or not model_manifest["license"].strip()
        or model_manifest.get("gated") is not False
        or model_manifest.get("trust_remote_code") is not False
    ):
        raise ValueError("model manifest violates identity, licence or offline-safety policy")


def _validate_scale_result(
    result: dict[str, Any],
    scale_manifest: dict[str, Any],
    model_manifest: dict[str, Any],
) -> None:
    _check_commitment(result, "result_sha256")
    if result.get("schema_version") != MODEL_BATCH_SCHEMA_VERSION:
        raise ValueError("scale result is not the current model-batch schema")
    if result.get("status") != "pass":
        raise ValueError("scale result did not pass")
    if result.get("accuracy_evaluated") is not False or result.get(
        "human_reference_used"
    ) is not False:
        raise ValueError("scale result must not use a human reference or claim accuracy")
    source = result.get("source", {})
    if not _is_lower_hex(source.get("commit"), 40) or not _is_lower_hex(
        source.get("archive_sha256"), 64
    ):
        raise ValueError("scale result source identity is invalid")
    articles = scale_manifest["articles"]
    corpus = result.get("corpus", {})
    if (
        corpus.get("manifest_sha256") != scale_manifest.get("manifest_sha256")
        or corpus.get("manifest_article_count") != 80
        or corpus.get("selected_article_count") != 80
        or corpus.get("selected_document_ids")
        != [row["document_id"] for row in articles]
        or corpus.get("selected_split_counts") != {"scale": 80}
    ):
        raise ValueError("scale result does not cover the exact frozen scale80 manifest")
    configuration = result.get("configuration", {})
    if (
        configuration.get("temperature") != 0.0
        or configuration.get("network_allowed_for_jats") is not False
        or configuration.get("determinism_check") is not True
    ):
        raise ValueError("scale result decoding or offline-input policy is not frozen")
    jats = result.get("jats", {})
    if (
        jats.get("article_count") != 80
        or jats.get("cache_hit_count") != 80
        or jats.get("downloaded_count") != 0
        or jats.get("all_frozen_sha256_matched") is not True
    ):
        raise ValueError("scale result did not use 80 hash-matched pre-staged JATS inputs")
    batch = result.get("batch", {})
    if (
        batch.get("prompt_contract_version") != PROMPT_CONTRACT_VERSION
        or batch.get("prompt_contract_sha256") != prompt_contract_sha256()
        or batch.get("response_schema_version") != RESPONSE_SCHEMA_VERSION
        or batch.get("response_schema_sha256")
        != canonical_sha256(
            load_committed_response_schema(
                Path(__file__).resolve().parents[2]
                / "schemas"
                / RESPONSE_SCHEMA_FILENAME
            )
        )
    ):
        raise ValueError("scale result prompt or response-schema contract is invalid")
    task_count = batch.get("task_count")
    if (
        not isinstance(task_count, int)
        or task_count < 1
        or batch.get("task_count_classified") != task_count
        or batch.get("classification_counts", {}).get("schema_rejected", 0) != 0
    ):
        raise ValueError("scale result task accounting is incomplete")
    maximum_no_task_fraction = configuration.get("maximum_no_task_article_fraction")
    if (
        isinstance(maximum_no_task_fraction, bool)
        or not isinstance(maximum_no_task_fraction, (int, float))
        or not 0.0 <= maximum_no_task_fraction <= 0.025
    ):
        raise ValueError("scale result no-task article tolerance is missing or too broad")
    try:
        expected_no_task_gate = build_no_task_article_gate(
            batch.get("per_article", {}),
            selected_document_ids=corpus["selected_document_ids"],
            maximum_fraction=maximum_no_task_fraction,
        )
    except ValueError as error:
        raise ValueError("scale result no-task article accounting is invalid") from error
    if batch.get("no_task_article_gate") != expected_no_task_gate or not (
        expected_no_task_gate["passed"]
    ):
        raise ValueError("scale result no-task article gate did not pass")
    determinism = batch.get("determinism_check", {})
    if determinism.get("performed") is not True or determinism.get("identical") is not True:
        raise ValueError("scale result in-run determinism gate did not pass")
    model = result.get("model", {})
    expected_model = {
        "repo_id": model_manifest["repo_id"],
        "revision": model_manifest["revision"],
        "tokenizer_revision": model_manifest["tokenizer_revision"],
        "license": model_manifest["license"],
        "snapshot_manifest_sha256": model_manifest["manifest_sha256"],
    }
    if any(model.get(field) != value for field, value in expected_model.items()):
        raise ValueError("scale result model identity differs from the frozen snapshot")


def _validate_integration_result(
    integration: dict[str, Any],
    scale_result: dict[str, Any],
    scale_manifest: dict[str, Any],
) -> None:
    _check_commitment(integration, "result_sha256")
    if (
        integration.get("schema_version") != "mdmeta.model-backed-integration.v1"
        or integration.get("status") != "pass"
        or integration.get("accuracy_evaluated") is not False
        or integration.get("human_reference_used") is not False
        or integration.get("article_count_requested") != 80
        or integration.get("model_result_sha256") != scale_result.get("result_sha256")
        or integration.get("source_manifest_sha256")
        != scale_manifest.get("manifest_sha256")
        or integration.get("source") != scale_result.get("source")
        or integration.get("no_task_article_gate")
        != scale_result.get("batch", {}).get("no_task_article_gate")
        or integration.get("database", {}).get("portable_single_file_snapshot") is not True
        or integration.get("identifier_integration_gate", {}).get("passed") is not True
        or len(integration.get("record_index", [])) != 80
    ):
        raise ValueError("scale80 integration result did not pass the complete bound chain")


def freeze_model_protocol(
    scale_manifest: dict[str, Any],
    scale_result: dict[str, Any],
    integration_result: dict[str, Any],
    model_manifest: dict[str, Any],
    *,
    source_root: Path,
    source_archive_sha256: str,
    scale_manifest_file_sha256: str,
    scale_result_file_sha256: str,
    scale_integration_result_file_sha256: str,
    model_manifest_file_sha256: str,
    gpu_environment_file_sha256: str,
    gpu_summary_file_sha256: str,
    integration_environment_file_sha256: str,
    integration_database_file_sha256: str,
    frozen_at_utc: str,
    operator_run_id: str,
) -> dict[str, Any]:
    _parse_utc(frozen_at_utc, "frozen_at_utc")
    if not operator_run_id.strip():
        raise ValueError("operator_run_id is required")
    evidence_hashes = {
        "source_archive": source_archive_sha256,
        "scale_source_manifest": scale_manifest_file_sha256,
        "scale_gpu_result": scale_result_file_sha256,
        "scale_cpu_integration_result": scale_integration_result_file_sha256,
        "model_manifest": model_manifest_file_sha256,
        "gpu_environment": gpu_environment_file_sha256,
        "gpu_summary": gpu_summary_file_sha256,
        "integration_environment": integration_environment_file_sha256,
        "integration_database": integration_database_file_sha256,
    }
    invalid_hashes = sorted(
        name for name, value in evidence_hashes.items() if not _is_lower_hex(value, 64)
    )
    if invalid_hashes:
        raise ValueError(f"invalid scale evidence file SHA-256 values: {invalid_hashes}")
    articles = _validate_scale_manifest(scale_manifest)
    _validate_model_manifest(model_manifest)
    _validate_scale_result(scale_result, scale_manifest, model_manifest)
    _validate_integration_result(integration_result, scale_result, scale_manifest)
    source = scale_result["source"]
    if source["archive_sha256"] != source_archive_sha256:
        raise ValueError("observed source archive differs from the scale result")
    implementation = _implementation_inventory(source_root, source["commit"])
    core = {
        "schema_version": "mdmeta.independent-model-protocol-freeze.v1",
        "study_id": scale_manifest["parent_study_id"],
        "study_status": "scale80_passed_model_protocol_frozen_pre_gold_inference",
        "parent_plan_sha256": scale_manifest["parent_plan_sha256"],
        "parent_audit_sha256": scale_manifest["parent_audit_sha256"],
        "source_screen_sha256": scale_manifest["source_screen_sha256"],
        "scale_source_manifest_sha256": scale_manifest["manifest_sha256"],
        "scale_article_count": len(articles),
        "scale_result_sha256": scale_result["result_sha256"],
        "scale_integration_result_sha256": integration_result["result_sha256"],
        "source_commit": source["commit"],
        "source_archive_sha256": source_archive_sha256,
        "scale_evidence_file_sha256": evidence_hashes,
        "model": {
            "repo_id": model_manifest["repo_id"],
            "revision": model_manifest["revision"],
            "tokenizer_revision": model_manifest["tokenizer_revision"],
            "license": model_manifest["license"],
            "snapshot_manifest_sha256": model_manifest["manifest_sha256"],
        },
        "prompt_contract": {
            "version": PROMPT_CONTRACT_VERSION,
            "sha256": prompt_contract_sha256(),
        },
        "response_schema": {
            "version": RESPONSE_SCHEMA_VERSION,
            "sha256": scale_result["batch"]["response_schema_sha256"],
        },
        "batch_schema_version": MODEL_BATCH_SCHEMA_VERSION,
        "configuration": scale_result["configuration"],
        "runtime": scale_result["runtime"],
        "implementation_files": implementation,
        "implementation_bundle_sha256": canonical_sha256(implementation),
        "frozen_at_utc": frozen_at_utc,
        "operator_run_id": operator_run_id,
        "contains_locked_test_articles": False,
        "contains_human_reference_labels": False,
        "gold_predictions_generated": False,
        "gold_prediction_authorized": False,
        "passed": True,
    }
    return {**core, "freeze_sha256": canonical_sha256(core)}


def authorize_gold20_prediction(
    plan: dict[str, Any],
    screen: dict[str, Any],
    plan_audit: dict[str, Any],
    model_freeze: dict[str, Any],
    public_reference_receipt: dict[str, Any],
    *,
    authorized_at_utc: str,
    operator_run_id: str,
) -> dict[str, Any]:
    _parse_utc(authorized_at_utc, "authorized_at_utc")
    if not operator_run_id.strip():
        raise ValueError("operator_run_id is required")
    expected_sources = validate_gold_source_contract(plan, screen, plan_audit)
    _check_commitment(model_freeze, "freeze_sha256")
    _check_commitment(public_reference_receipt, "receipt_sha256")
    if (
        model_freeze.get("schema_version")
        != "mdmeta.independent-model-protocol-freeze.v1"
        or model_freeze.get("passed") is not True
        or model_freeze.get("gold_predictions_generated") is not False
        or model_freeze.get("contains_locked_test_articles") is not False
        or model_freeze.get("parent_plan_sha256") != plan.get("plan_sha256")
        or model_freeze.get("parent_audit_sha256") != plan_audit.get("audit_sha256")
        or model_freeze.get("source_screen_sha256") != plan.get("screen_sha256")
    ):
        raise ValueError("model protocol freeze does not bind the accepted pre-gold study")
    receipt = public_reference_receipt
    if (
        receipt.get("schema_version") != "mdmeta.gold-reference-public-receipt.v1"
        or receipt.get("passed") is not True
        or receipt.get("article_count") != 20
        or receipt.get("annotator_count") != 2
        or receipt.get("coverage_complete") is not True
        or receipt.get("all_disagreements_resolved") is not True
        or receipt.get("human_reference") is not True
        or receipt.get("contains_model_predictions") is not False
        or receipt.get("labels_disclosed") is not False
        or receipt.get("label_statistics_disclosed") is not False
        or receipt.get("plan_sha256") != plan.get("plan_sha256")
        or receipt.get("plan_audit_sha256") != plan_audit.get("audit_sha256")
        or receipt.get("screen_sha256") != plan.get("screen_sha256")
    ):
        raise ValueError("human-reference receipt is incomplete, leaky or from another study")
    gold_rows = {row["document_id"]: row for row in plan["locked_test"]}
    articles = [
        {
            "document_id": document_id,
            "split": "gold",
            "source_uri": gold_rows[document_id]["source_uri"],
            "full_text_sha256": expected_sources[document_id],
        }
        for document_id in sorted(expected_sources)
    ]
    core = {
        "schema_version": "mdmeta.independent-gold20-prediction-source.v1",
        "study_id": plan["study_id"],
        "study_status": "gold20_prediction_authorized_preinference",
        "parent_plan_sha256": plan["plan_sha256"],
        "parent_audit_sha256": plan_audit["audit_sha256"],
        "source_screen_sha256": plan["screen_sha256"],
        "model_protocol_freeze_sha256": model_freeze["freeze_sha256"],
        "human_reference_receipt_sha256": receipt["receipt_sha256"],
        "human_reference_sha256": receipt["reference_sha256"],
        "model_source_commit": model_freeze["source_commit"],
        "model_source_archive_sha256": model_freeze["source_archive_sha256"],
        "prompt_contract": model_freeze["prompt_contract"],
        "response_schema": model_freeze["response_schema"],
        "model": model_freeze["model"],
        "authorization_sequence": [
            "scale80_passed",
            "model_protocol_frozen",
            "dual_human_reference_frozen",
            "gold20_source_released_without_labels",
        ],
        "authorized_at_utc": authorized_at_utc,
        "operator_run_id": operator_run_id,
        "article_count": len(articles),
        "contains_human_reference_labels": False,
        "contains_model_predictions": False,
        "articles": articles,
    }
    return {**core, "manifest_sha256": canonical_sha256(core)}
