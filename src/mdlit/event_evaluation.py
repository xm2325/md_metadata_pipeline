from __future__ import annotations

import random
from collections import Counter
from typing import Any

from .models import ProtocolEvent

EVENT_FIELDS = (
    "duration_value",
    "temperature_k",
    "pressure_bar",
    "ensemble",
    "time_step_ps",
    "replicates",
)


def event_attribute_keys(
    document_id: str, events: list[ProtocolEvent]
) -> set[tuple[str, str, str, str]]:
    keys: set[tuple[str, str, str, str]] = set()
    for event in events:
        for field in EVENT_FIELDS:
            value = getattr(event, field)
            if value is not None:
                keys.add((document_id, event.phase, field, str(value)))
    return keys


def event_signature(event: ProtocolEvent) -> tuple[Any, ...]:
    return (
        event.phase,
        event.duration_value,
        event.temperature_k,
        event.pressure_bar,
        event.ensemble,
        event.time_step_ps,
        event.replicates,
    )


def _prf(tp: int, fp: int, fn: int) -> dict[str, float | int]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def evaluate_protocol_events(
    predicted: dict[str, list[ProtocolEvent]],
    reference: dict[str, list[ProtocolEvent]],
    *,
    bootstrap_iterations: int = 2000,
    seed: int = 3997,
) -> dict[str, Any]:
    documents = sorted(set(predicted) | set(reference))
    article_counts: dict[str, tuple[int, int, int]] = {}
    exact_tp = exact_fp = exact_fn = 0
    attr_tp = attr_fp = attr_fn = 0
    for document_id in documents:
        pred_signatures = {event_signature(event) for event in predicted.get(document_id, [])}
        ref_signatures = {event_signature(event) for event in reference.get(document_id, [])}
        exact_tp += len(pred_signatures & ref_signatures)
        exact_fp += len(pred_signatures - ref_signatures)
        exact_fn += len(ref_signatures - pred_signatures)

        pred_attrs = event_attribute_keys(document_id, predicted.get(document_id, []))
        ref_attrs = event_attribute_keys(document_id, reference.get(document_id, []))
        counts = (
            len(pred_attrs & ref_attrs),
            len(pred_attrs - ref_attrs),
            len(ref_attrs - pred_attrs),
        )
        article_counts[document_id] = counts
        attr_tp += counts[0]
        attr_fp += counts[1]
        attr_fn += counts[2]

    rng = random.Random(seed)
    bootstrap_f1 = []
    if documents:
        for _ in range(bootstrap_iterations):
            sample = [rng.choice(documents) for _ in documents]
            counts = Counter()
            for document_id in sample:
                tp, fp, fn = article_counts[document_id]
                counts.update({"tp": tp, "fp": fp, "fn": fn})
            bootstrap_f1.append(_prf(counts["tp"], counts["fp"], counts["fn"])["f1"])
    bootstrap_f1.sort()
    lower = bootstrap_f1[int(0.025 * len(bootstrap_f1))] if bootstrap_f1 else 0.0
    upper_index = min(len(bootstrap_f1) - 1, int(0.975 * len(bootstrap_f1))) if bootstrap_f1 else 0
    upper = bootstrap_f1[upper_index] if bootstrap_f1 else 0.0

    return {
        "event_exact": _prf(exact_tp, exact_fp, exact_fn),
        "event_attribute": {
            **_prf(attr_tp, attr_fp, attr_fn),
            "article_bootstrap_95_ci_f1": [lower, upper],
        },
        "article_count": len(documents),
        "bootstrap_iterations": bootstrap_iterations,
        "seed": seed,
    }
