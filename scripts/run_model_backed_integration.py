#!/usr/bin/env python3
"""Integrate a verified model batch with live PDBe, UniProt and SIFTS mappings."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from mdmeta import user_agent
from mdmeta.benchmark import canonical_sha256
from mdmeta.integration import (
    integrate_article,
    parse_jats_paragraphs,
    protocol_paragraphs,
    summarize_integrated_records,
)
from mdmeta.llm_adapter import (
    EvidenceIntegrityError,
    LLMEventResponse,
    SchemaConstrainedEventExtractor,
)
from mdmeta.llm_batch import (
    RESPONSE_SCHEMA_FILENAME,
    RESPONSE_SCHEMA_VERSION,
    SCHEMA_VERSION as MODEL_BATCH_SCHEMA_VERSION,
    atomic_write_json,
    load_committed_response_schema,
    select_articles,
    validate_source_manifest,
)
from mdmeta.models import ProtocolEvent
from mdmeta.protocol_events import Paragraph
from mdmeta.storage import SQLiteRecordStore
from mdmeta.validation import IdentifierValidator


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _prediction_commitment(payload: dict[str, Any]) -> str:
    stored = payload.get("result_sha256")
    core = {key: value for key, value in payload.items() if key != "result_sha256"}
    observed = canonical_sha256(core)
    if stored != observed:
        raise ValueError("model result commitment is invalid")
    return observed


def _paragraph_key(paragraph: Paragraph) -> tuple[str, str, str, str]:
    return (
        paragraph.document_id,
        paragraph.section,
        paragraph.paragraph_id,
        hashlib.sha256(paragraph.text.encode("utf-8")).hexdigest(),
    )


def _task_key(task: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        task["document_id"],
        task["section"],
        task["paragraph_id"],
        task["context_sha256"],
    )


def _validated_event_map(
    prediction: dict[str, Any],
    xml_by_document: dict[str, bytes],
    split_by_document: dict[str, str],
) -> tuple[dict[tuple[str, str, str, str], list[ProtocolEvent]], Counter[str]]:
    batch = prediction.get("batch", {})
    committed_response_schema = load_committed_response_schema(
        Path(__file__).resolve().parents[1] / "schemas" / RESPONSE_SCHEMA_FILENAME
    )
    if batch.get("response_schema_version") != RESPONSE_SCHEMA_VERSION:
        raise ValueError("model result response-schema version is unsupported")
    if batch.get("response_schema_sha256") != canonical_sha256(
        committed_response_schema
    ):
        raise ValueError("model result response-schema commitment is invalid")
    tasks = batch.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("model result does not contain task-level predictions")
    model = prediction.get("model", {})
    repo_id = model.get("repo_id")
    revision = model.get("revision")
    tokenizer_revision = model.get("tokenizer_revision")
    if not isinstance(repo_id, str) or not repo_id.strip():
        raise ValueError("model result does not contain an immutable model identity")
    if not isinstance(revision, str) or re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise ValueError("model result revision is not an immutable commit")
    if tokenizer_revision != revision:
        raise ValueError("model and tokenizer revisions differ")
    extractor = SchemaConstrainedEventExtractor(
        backend=None,  # type: ignore[arg-type] - validation replay performs no model call
        model_id=f"{repo_id}@{revision}",
    )
    by_key: dict[tuple[str, str, str, str], list[ProtocolEvent]] = {}
    tasks_by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    classifications: Counter[str] = Counter()
    for task in tasks:
        key = _task_key(task)
        if key in by_key:
            raise ValueError(f"model result contains a duplicate paragraph task: {key}")
        expected_split = split_by_document.get(task["document_id"])
        if expected_split is None or task.get("split") != expected_split:
            raise ValueError("model task split differs from the frozen source manifest")
        classification = task.get("classification")
        if classification not in {"accepted", "evidence_rejected"}:
            raise ValueError(f"model task has an unusable classification: {classification!r}")
        classifications[classification] += 1
        stored_events = [ProtocolEvent.model_validate(row) for row in task.get("events", [])]
        if classification != "accepted" and stored_events:
            raise ValueError("a rejected model task must not contain accepted events")
        by_key[key] = stored_events
        tasks_by_key[key] = task

    expected: set[tuple[str, str, str, str]] = set()
    paragraphs_by_key: dict[tuple[str, str, str, str], Paragraph] = {}
    for document_id, xml_bytes in xml_by_document.items():
        for paragraph in protocol_paragraphs(parse_jats_paragraphs(document_id, xml_bytes)):
            key = _paragraph_key(paragraph)
            expected.add(key)
            paragraphs_by_key[key] = paragraph
    if set(by_key) != expected:
        missing = len(expected - set(by_key))
        extra = len(set(by_key) - expected)
        raise ValueError(
            f"model paragraph task set differs from JATS: missing={missing}, extra={extra}"
        )
    for key, stored_events in list(by_key.items()):
        paragraph = paragraphs_by_key[key]
        task = tasks_by_key[key]
        expected_task_id = hashlib.sha256(
            "|".join(
                (
                    paragraph.document_id,
                    task["split"],
                    paragraph.section,
                    paragraph.paragraph_id,
                    key[3],
                )
            ).encode("utf-8")
        ).hexdigest()
        if task.get("task_id") != expected_task_id:
            raise ValueError("model task identifier does not reproduce from frozen JATS")
        expected_prompt_sha256 = hashlib.sha256(
            extractor.build_prompt([paragraph]).encode("utf-8")
        ).hexdigest()
        if task.get("prompt_sha256") != expected_prompt_sha256:
            raise ValueError("model task prompt commitment does not reproduce from frozen JATS")
        response = task.get("response")
        if not isinstance(response, dict):
            raise ValueError("model task does not retain its structured raw response")
        if task.get("response_sha256") != canonical_sha256(response):
            raise ValueError("model task response commitment is invalid")
        try:
            LLMEventResponse.model_validate(response)
        except ValueError as error:
            raise ValueError("model task raw response is not schema-valid") from error
        try:
            replayed_events = extractor.validate_response([paragraph], response)
        except EvidenceIntegrityError:
            if task["classification"] != "evidence_rejected":
                raise ValueError("accepted model task fails independent evidence replay")
            replayed_events = []
        else:
            if task["classification"] != "accepted":
                raise ValueError("rejected model task passes independent evidence replay")
        if canonical_sha256([event.model_dump(mode="json") for event in replayed_events]) != (
            canonical_sha256([event.model_dump(mode="json") for event in stored_events])
        ):
            raise ValueError("stored normalized model events differ from replayed raw response")
        if task.get("event_count") != len(replayed_events):
            raise ValueError("model task event count differs from independent replay")
        by_key[key] = replayed_events
        for event in replayed_events:
            for evidence in event.evidence:
                if evidence.document_id != paragraph.document_id:
                    raise ValueError("model event evidence document does not match its task")
                if evidence.section != paragraph.section:
                    raise ValueError("model event evidence section does not match its task")
                if evidence.paragraph_id != paragraph.paragraph_id:
                    raise ValueError("model event evidence paragraph does not match its task")
                if paragraph.text[evidence.start_char : evidence.end_char] != evidence.quote:
                    raise ValueError("model event evidence no longer reproduces from JATS")
                if evidence.context_sha256 != key[3]:
                    raise ValueError("model event evidence context hash does not match JATS")
    return by_key, classifications


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--jats-cache-dir", type=Path, required=True)
    parser.add_argument("--model-result", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--validation-cache-dir", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-archive-sha256", required=True)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--require-validated-pdb", action="store_true")
    parser.add_argument("--require-residue-mapping", action="store_true")
    args = parser.parse_args()

    prediction = json.loads(args.model_result.read_text(encoding="utf-8"))
    prediction_sha256 = _prediction_commitment(prediction)
    if re.fullmatch(r"[0-9a-f]{40}", args.source_commit) is None:
        raise SystemExit("expected source commit is not a full lowercase Git SHA-1")
    if re.fullmatch(r"[0-9a-f]{64}", args.source_archive_sha256) is None:
        raise SystemExit("expected source archive digest is not a lowercase SHA-256")
    if prediction.get("schema_version") != MODEL_BATCH_SCHEMA_VERSION:
        raise SystemExit("model result schema version is unsupported")
    if prediction.get("status") != "pass":
        raise SystemExit("model result did not pass its generation gates")
    if (
        prediction.get("accuracy_evaluated") is not False
        or prediction.get("human_reference_used") is not False
    ):
        raise SystemExit("model batch must not be presented as an accuracy evaluation")
    expected_source = {
        "commit": args.source_commit,
        "archive_sha256": args.source_archive_sha256,
    }
    if prediction.get("source") != expected_source:
        raise SystemExit("model result is not bound to the current verified source archive")

    source_payload = json.loads(args.source_manifest.read_text(encoding="utf-8"))
    all_articles = validate_source_manifest(source_payload)
    selected_ids = prediction.get("corpus", {}).get("selected_document_ids")
    if not isinstance(selected_ids, list) or not selected_ids:
        raise SystemExit("model result has no selected document identifiers")
    articles = select_articles(all_articles, document_ids=selected_ids)
    if prediction["corpus"].get("selected_article_count") != len(articles):
        raise SystemExit("model result selected-article count is inconsistent")
    if prediction["corpus"].get("manifest_sha256") != source_payload["manifest_sha256"]:
        raise SystemExit("model result and source manifest commitments differ")

    xml_by_document: dict[str, bytes] = {}
    for article in articles:
        path = args.jats_cache_dir / f"{article.document_id}.xml"
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != article.full_text_sha256:
            raise SystemExit(f"cached JATS SHA-256 mismatch for {article.document_id}")
        xml_by_document[article.document_id] = payload
    split_by_document = {article.document_id: article.split for article in articles}
    events_by_key, classifications = _validated_event_map(
        prediction,
        xml_by_document,
        split_by_document,
    )
    batch = prediction.get("batch", {})
    task_count = sum(classifications.values())
    event_count = sum(len(events) for events in events_by_key.values())
    if batch.get("task_count") != task_count or batch.get("task_count_classified") != task_count:
        raise SystemExit("model result task counts are inconsistent")
    if batch.get("classification_counts") != dict(sorted(classifications.items())):
        raise SystemExit("model result classification counts are inconsistent")
    if batch.get("event_count") != event_count:
        raise SystemExit("model result event count is inconsistent")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(args.output_dir, 0o700)
    records_dir = args.output_dir / "records"
    records_dir.mkdir(exist_ok=True)
    os.chmod(records_dir, 0o700)
    store = SQLiteRecordStore(args.database)
    records = []
    failures: list[dict[str, Any]] = []
    headers = {"User-Agent": user_agent("model-backed-integration")}
    with httpx.Client(
        timeout=args.timeout,
        headers=headers,
        follow_redirects=True,
    ) as client:
        validator = IdentifierValidator(client, cache_dir=args.validation_cache_dir)
        for article in articles:
            try:
                xml_bytes = xml_by_document[article.document_id]

                def event_extractor(paragraph: Paragraph) -> list[ProtocolEvent]:
                    return events_by_key[_paragraph_key(paragraph)]

                record = integrate_article(
                    article.document_id,
                    xml_bytes,
                    source_uri=article.source_uri,
                    validator=validator,
                    event_extractor=event_extractor,
                )
                document_tasks = [
                    task
                    for task in prediction["batch"]["tasks"]
                    if task["document_id"] == article.document_id
                ]
                rejected = sum(
                    task["classification"] == "evidence_rejected"
                    for task in document_tasks
                )
                completeness = dict(record.completeness)
                completeness["protocol_event_extraction"] = (
                    "complete" if rejected == 0 else "complete_with_evidence_rejections"
                )
                record = record.model_copy(update={"completeness": completeness})
                store.write(record)
                records.append(record)
                atomic_write_json(
                    records_dir / f"{article.document_id}.json",
                    record.model_dump(mode="json"),
                )
            except (httpx.HTTPError, OSError, ValueError, KeyError) as error:
                failures.append(
                    {
                        "document_id": article.document_id,
                        "split": article.split,
                        "error_type": type(error).__name__,
                        "message": str(error),
                    }
                )

    integration_summary = summarize_integrated_records(records, failures)
    checkpoint_result = store.checkpoint()
    integrity_report = store.integrity_report()
    database_passed = (
        checkpoint_result[0] == 0
        and checkpoint_result[1] == checkpoint_result[2]
        and integrity_report["integrity"] == ["ok"]
        and integrity_report["foreign_key_violations"] == []
        and str(integrity_report["journal_mode"]).casefold() == "delete"
    )
    validated_pdb_count = integration_summary["pdb_validation_state_counts"].get(
        "validated", 0
    )
    validated_mapping_count = integration_summary["mapping_validation_state_counts"].get(
        "validated", 0
    )
    identifier_gate_passed = (
        (not args.require_validated_pdb or validated_pdb_count > 0)
        and (
            not args.require_residue_mapping
            or (
                validated_mapping_count > 0
                and integration_summary["residue_mapping_segment_count"] > 0
                and integration_summary["unique_uniprot_accession_count"] > 0
            )
        )
    )
    core = {
        "schema_version": "mdmeta.model-backed-integration.v1",
        "status": (
            "pass"
            if (
                not failures
                and len(records) == len(articles)
                and database_passed
                and identifier_gate_passed
            )
            else "fail"
        ),
        "generated_at": _utc_now(),
        "accuracy_evaluated": False,
        "human_reference_used": False,
        "interpretation": (
            "model-backed end-to-end integration coverage, not extraction accuracy"
        ),
        "slurm": {
            "job_id": os.environ.get("SLURM_JOB_ID"),
            "account": os.environ.get("SLURM_JOB_ACCOUNT"),
            "partition": os.environ.get("SLURM_JOB_PARTITION"),
            "node": os.environ.get("SLURMD_NODENAME"),
        },
        "source_manifest_sha256": source_payload["manifest_sha256"],
        "model_result_sha256": prediction_sha256,
        "source": expected_source,
        "model": prediction["model"],
        "article_count_requested": len(articles),
        "task_classification_counts": dict(sorted(classifications.items())),
        "database": {
            "checkpoint": {
                "busy": checkpoint_result[0],
                "log_frames": checkpoint_result[1],
                "checkpointed_frames": checkpoint_result[2],
            },
            "integrity": integrity_report,
            "portable_single_file_snapshot": database_passed,
        },
        "identifier_integration_gate": {
            "require_validated_pdb": args.require_validated_pdb,
            "require_residue_mapping": args.require_residue_mapping,
            "validated_pdb_count": validated_pdb_count,
            "validated_mapping_count": validated_mapping_count,
            "residue_mapping_segment_count": integration_summary[
                "residue_mapping_segment_count"
            ],
            "passed": identifier_gate_passed,
        },
        "summary": integration_summary,
        "record_index": [
            {
                "document_id": record.article.document_id,
                "title": record.article.title,
                "doi": record.article.doi,
                "record_path": f"records/{record.article.document_id}.json",
                "completeness": record.completeness,
            }
            for record in records
        ],
    }
    result = {**core, "result_sha256": canonical_sha256(core)}
    atomic_write_json(args.output_dir / "summary.json", result)
    print(json.dumps(result["summary"], indent=2))
    if result["status"] != "pass" or store.count_articles() != len(articles):
        raise SystemExit("model-backed integration completeness gate failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
