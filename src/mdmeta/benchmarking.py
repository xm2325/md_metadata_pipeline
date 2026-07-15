from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any

from .event_evaluation import evaluate_events, event_signature
from .integration import IntegratedMDRecord
from .models import ProtocolEvent


def _events(rows: Any) -> list[ProtocolEvent]:
    if not isinstance(rows, list):
        raise ValueError("events must be a list")
    return [ProtocolEvent.model_validate(row) for row in rows]


def load_event_run(path: str | Path) -> tuple[dict[str, list[ProtocolEvent]], dict[str, Any]]:
    """Load repository LLM runs, integrated records, or canonical document/event mappings."""

    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    documents: dict[str, list[ProtocolEvent]] = {}
    metadata: dict[str, Any] = {"source": str(source)}

    if isinstance(payload, dict) and payload.get("schema_version") == "integrated-md-record-v1":
        record = IntegratedMDRecord.model_validate(payload)
        documents[record.article.document_id] = record.protocol_events
        metadata["schema_version"] = record.schema_version
        return documents, metadata

    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        records = [IntegratedMDRecord.model_validate(row) for row in payload["records"]]
        for record in records:
            documents[record.article.document_id] = record.protocol_events
        metadata["schema_version"] = payload.get("schema_version")
        return documents, metadata

    if isinstance(payload, dict) and isinstance(payload.get("documents"), list):
        for document in payload["documents"]:
            if not isinstance(document, dict) or not isinstance(document.get("document_id"), str):
                raise ValueError("document entries require document_id")
            documents[document["document_id"]] = _events(document.get("events", []))
        metadata.update(
            {
                "schema_version": payload.get("schema_version"),
                "model_id": payload.get("model_id"),
                "completions": payload.get("completions", []),
            }
        )
        return documents, metadata

    if isinstance(payload, dict) and payload and all(
        isinstance(document_id, str) and isinstance(rows, list)
        for document_id, rows in payload.items()
    ):
        for document_id, rows in payload.items():
            documents[document_id] = _events(rows)
        metadata["schema_version"] = "canonical-document-event-map-v1"
        return documents, metadata

    raise ValueError(f"unsupported event-run format: {source}")


def validated_union(
    left: dict[str, list[ProtocolEvent]],
    right: dict[str, list[ProtocolEvent]],
) -> dict[str, list[ProtocolEvent]]:
    """Union already validated events without allowing duplicate inflation."""

    output: dict[str, list[ProtocolEvent]] = {}
    for document_id in sorted(set(left) | set(right)):
        unique: dict[tuple[str, ...], ProtocolEvent] = {}
        for event in left.get(document_id, []) + right.get(document_id, []):
            unique[event_signature(event)] = event
        output[document_id] = [unique[key] for key in sorted(unique)]
    return output


def operational_summary(
    events: dict[str, list[ProtocolEvent]], metadata: dict[str, Any]
) -> dict[str, Any]:
    completions = metadata.get("completions")
    audits = completions if isinstance(completions, list) else []
    latencies = [
        float(item["latency_ms"])
        for item in audits
        if isinstance(item, dict) and isinstance(item.get("latency_ms"), (int, float))
    ]
    token_totals = [
        int(item["total_tokens"])
        for item in audits
        if isinstance(item, dict) and isinstance(item.get("total_tokens"), int)
    ]
    finish_reasons = Counter(
        str(item.get("finish_reason", "unknown"))
        for item in audits
        if isinstance(item, dict)
    )
    return {
        "document_count": len(events),
        "event_count": sum(len(rows) for rows in events.values()),
        "zero_event_document_count": sum(not rows for rows in events.values()),
        "completion_count": len(audits),
        "median_latency_ms": median(latencies) if latencies else None,
        "total_tokens": sum(token_totals) if token_totals else None,
        "finish_reason_counts": dict(sorted(finish_reasons.items())),
        "model_id": metadata.get("model_id"),
        "source": metadata.get("source"),
    }


def _article_counts(
    predictions: dict[str, list[ProtocolEvent]],
    references: dict[str, list[ProtocolEvent]],
) -> dict[str, tuple[int, int, int]]:
    counts: dict[str, tuple[int, int, int]] = {}
    for document_id in sorted(set(predictions) | set(references)):
        result = evaluate_events(
            {document_id: predictions.get(document_id, [])},
            {document_id: references.get(document_id, [])},
            bootstrap_iterations=0,
        )["event_attribute"]
        counts[document_id] = (int(result["tp"]), int(result["fp"]), int(result["fn"]))
    return counts


def _f1(tp: int, fp: int, fn: int) -> float:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def paired_bootstrap_delta(
    candidate: dict[str, list[ProtocolEvent]],
    baseline: dict[str, list[ProtocolEvent]],
    references: dict[str, list[ProtocolEvent]],
    *,
    iterations: int = 2000,
    seed: int = 3997,
) -> dict[str, Any]:
    documents = sorted(set(candidate) | set(baseline) | set(references))
    candidate_counts = _article_counts(candidate, references)
    baseline_counts = _article_counts(baseline, references)
    rng = random.Random(seed)
    deltas: list[float] = []
    if documents:
        for _ in range(iterations):
            candidate_total = Counter()
            baseline_total = Counter()
            for _ in documents:
                document_id = rng.choice(documents)
                c_tp, c_fp, c_fn = candidate_counts[document_id]
                b_tp, b_fp, b_fn = baseline_counts[document_id]
                candidate_total.update(tp=c_tp, fp=c_fp, fn=c_fn)
                baseline_total.update(tp=b_tp, fp=b_fp, fn=b_fn)
            deltas.append(
                _f1(candidate_total["tp"], candidate_total["fp"], candidate_total["fn"])
                - _f1(baseline_total["tp"], baseline_total["fp"], baseline_total["fn"])
            )
    deltas.sort()
    if deltas:
        lower = deltas[int(0.025 * (len(deltas) - 1))]
        upper = deltas[int(0.975 * (len(deltas) - 1))]
        probability_positive = sum(delta > 0 for delta in deltas) / len(deltas)
    else:
        lower = upper = probability_positive = 0.0
    observed_candidate = evaluate_events(
        candidate, references, bootstrap_iterations=0
    )["event_attribute"]["f1"]
    observed_baseline = evaluate_events(
        baseline, references, bootstrap_iterations=0
    )["event_attribute"]["f1"]
    return {
        "metric": "phase-aware event-attribute F1",
        "observed_delta": observed_candidate - observed_baseline,
        "paired_article_bootstrap_95_ci": [lower, upper],
        "bootstrap_probability_delta_gt_zero": probability_positive,
        "iterations": iterations,
        "seed": seed,
    }


def compare_systems(
    references: dict[str, list[ProtocolEvent]],
    systems: dict[str, tuple[dict[str, list[ProtocolEvent]], dict[str, Any]]],
    *,
    baseline_name: str | None = None,
    bootstrap_iterations: int = 2000,
    seed: int = 3997,
) -> dict[str, Any]:
    if not systems:
        raise ValueError("at least one system is required")
    if baseline_name is not None and baseline_name not in systems:
        raise ValueError(f"unknown baseline system: {baseline_name}")

    results: dict[str, Any] = {}
    for name, (events, metadata) in sorted(systems.items()):
        results[name] = {
            "operational": operational_summary(events, metadata),
            "scientific": evaluate_events(
                events,
                references,
                bootstrap_iterations=bootstrap_iterations,
                seed=seed,
            ),
        }

    deltas: dict[str, Any] = {}
    if baseline_name is not None:
        baseline_events = systems[baseline_name][0]
        for name, (events, _) in sorted(systems.items()):
            if name == baseline_name:
                continue
            deltas[name] = paired_bootstrap_delta(
                events,
                baseline_events,
                references,
                iterations=bootstrap_iterations,
                seed=seed,
            )

    return {
        "schema_version": "extractor-comparison-v1",
        "reference_document_count": len(references),
        "systems": results,
        "baseline": baseline_name,
        "paired_deltas_vs_baseline": deltas,
        "scientific_boundary": (
            "Metrics are valid only to the extent that the supplied reference is independently "
            "annotated and adjudicated. AI-consensus references remain exploratory."
        ),
    }
