from __future__ import annotations

import random
from collections import Counter
from typing import Any

from .models import ProtocolEvent

_EVENT_ATTRIBUTES = (
    "duration_ps",
    "temperature_k",
    "pressure_bar",
    "timestep_fs",
    "ensemble",
    "restraints",
    "replicates",
)


def _metric(tp: int, fp: int, fn: int) -> dict[str, int | float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def _value(value: Any) -> str:
    if isinstance(value, float):
        return format(value, ".12g")
    return str(value)


def event_signature(event: ProtocolEvent) -> tuple[str, ...]:
    return (
        event.event_type.value,
        _value(event.duration_ps),
        _value(event.temperature_k),
        _value(event.pressure_bar),
        _value(event.timestep_fs),
        _value(event.ensemble),
        _value(event.restraints),
        _value(event.replicates),
    )


def event_attribute_keys(document_id: str, events: list[ProtocolEvent]) -> set[tuple[str, str, str, str]]:
    output: set[tuple[str, str, str, str]] = set()
    for event in events:
        for attribute in _EVENT_ATTRIBUTES:
            value = getattr(event, attribute)
            if value is not None:
                output.add((document_id, event.event_type.value, attribute, _value(value)))
    return output


def evaluate_events(
    predictions: dict[str, list[ProtocolEvent]],
    references: dict[str, list[ProtocolEvent]],
    *,
    bootstrap_iterations: int = 2000,
    seed: int = 3997,
) -> dict[str, Any]:
    documents = sorted(set(predictions) | set(references))
    exact = Counter()
    attributes = Counter()
    duration_phase = Counter()
    per_article: dict[str, tuple[int, int, int]] = {}

    for document_id in documents:
        pred_events = predictions.get(document_id, [])
        ref_events = references.get(document_id, [])
        pred_exact = {event_signature(event) for event in pred_events}
        ref_exact = {event_signature(event) for event in ref_events}
        exact.update(
            tp=len(pred_exact & ref_exact),
            fp=len(pred_exact - ref_exact),
            fn=len(ref_exact - pred_exact),
        )

        pred_attributes = event_attribute_keys(document_id, pred_events)
        ref_attributes = event_attribute_keys(document_id, ref_events)
        counts = (
            len(pred_attributes & ref_attributes),
            len(pred_attributes - ref_attributes),
            len(ref_attributes - pred_attributes),
        )
        per_article[document_id] = counts
        attributes.update(tp=counts[0], fp=counts[1], fn=counts[2])

        pred_duration = {item for item in pred_attributes if item[2] == "duration_ps"}
        ref_duration = {item for item in ref_attributes if item[2] == "duration_ps"}
        duration_phase.update(
            tp=len(pred_duration & ref_duration),
            fp=len(pred_duration - ref_duration),
            fn=len(ref_duration - pred_duration),
        )

    rng = random.Random(seed)
    bootstrap_f1: list[float] = []
    if documents and bootstrap_iterations > 0:
        for _ in range(bootstrap_iterations):
            sample_counts = Counter()
            for _ in documents:
                document_id = rng.choice(documents)
                tp, fp, fn = per_article[document_id]
                sample_counts.update(tp=tp, fp=fp, fn=fn)
            bootstrap_f1.append(
                float(_metric(sample_counts["tp"], sample_counts["fp"], sample_counts["fn"])["f1"])
            )
    bootstrap_f1.sort()
    if bootstrap_f1:
        lower_index = int(0.025 * (len(bootstrap_f1) - 1))
        upper_index = int(0.975 * (len(bootstrap_f1) - 1))
        confidence_interval = [bootstrap_f1[lower_index], bootstrap_f1[upper_index]]
    else:
        confidence_interval = [0.0, 0.0]

    return {
        "article_count": len(documents),
        "event_exact": _metric(exact["tp"], exact["fp"], exact["fn"]),
        "event_attribute": {
            **_metric(attributes["tp"], attributes["fp"], attributes["fn"]),
            "article_bootstrap_95_ci_f1": confidence_interval,
        },
        "duration_phase": _metric(
            duration_phase["tp"], duration_phase["fp"], duration_phase["fn"]
        ),
        "bootstrap_iterations": bootstrap_iterations,
        "bootstrap_seed": seed,
    }
