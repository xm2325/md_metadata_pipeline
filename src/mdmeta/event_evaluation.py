from __future__ import annotations

import random
from collections import Counter, defaultdict
from typing import Any, Hashable

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
_MISSED = "__missed__"
_SPURIOUS = "__spurious__"


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


def _counter_metric(
    predicted: Counter[Hashable], reference: Counter[Hashable]
) -> tuple[int, int, int]:
    true_positive = sum((predicted & reference).values())
    false_positive = sum((predicted - reference).values())
    false_negative = sum((reference - predicted).values())
    return true_positive, false_positive, false_negative


def event_attribute_counter(
    document_id: str, events: list[ProtocolEvent]
) -> Counter[tuple[str, str, str, str]]:
    output: Counter[tuple[str, str, str, str]] = Counter()
    for event in events:
        for attribute in _EVENT_ATTRIBUTES:
            value = getattr(event, attribute)
            if value is not None:
                output[(document_id, event.event_type.value, attribute, _value(value))] += 1
    return output


def event_attribute_keys(
    document_id: str, events: list[ProtocolEvent]
) -> set[tuple[str, str, str, str]]:
    """Return unique attribute keys for exploratory inspection.

    Evaluation uses :func:`event_attribute_counter` so repeated events are not lost.
    """
    return set(event_attribute_counter(document_id, events))


def _duration_phase_counter(
    document_id: str, events: list[ProtocolEvent]
) -> Counter[tuple[str, str, str]]:
    return Counter(
        (document_id, event.event_type.value, _value(event.duration_ps))
        for event in events
        if event.duration_ps is not None
    )


def _phase_confusion_for_article(
    predicted: list[ProtocolEvent], reference: list[ProtocolEvent]
) -> Counter[tuple[str, str]]:
    predicted_by_duration: dict[str, Counter[str]] = defaultdict(Counter)
    reference_by_duration: dict[str, Counter[str]] = defaultdict(Counter)
    for event in predicted:
        if event.duration_ps is not None:
            predicted_by_duration[_value(event.duration_ps)][event.event_type.value] += 1
    for event in reference:
        if event.duration_ps is not None:
            reference_by_duration[_value(event.duration_ps)][event.event_type.value] += 1

    confusion: Counter[tuple[str, str]] = Counter()
    for duration in sorted(set(predicted_by_duration) | set(reference_by_duration)):
        predicted_phases = predicted_by_duration[duration].copy()
        reference_phases = reference_by_duration[duration].copy()

        for phase in sorted(set(predicted_phases) & set(reference_phases)):
            matched = min(predicted_phases[phase], reference_phases[phase])
            if matched:
                confusion[(phase, phase)] += matched
                predicted_phases[phase] -= matched
                reference_phases[phase] -= matched

        remaining_predicted = [
            phase
            for phase, count in sorted(predicted_phases.items())
            for _ in range(count)
            if count > 0
        ]
        remaining_reference = [
            phase
            for phase, count in sorted(reference_phases.items())
            for _ in range(count)
            if count > 0
        ]
        paired = min(len(remaining_predicted), len(remaining_reference))
        for index in range(paired):
            confusion[(remaining_reference[index], remaining_predicted[index])] += 1
        for phase in remaining_reference[paired:]:
            confusion[(phase, _MISSED)] += 1
        for phase in remaining_predicted[paired:]:
            confusion[(_SPURIOUS, phase)] += 1
    return confusion


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
    phase_confusion: Counter[tuple[str, str]] = Counter()
    per_article: dict[str, tuple[int, int, int]] = {}

    for document_id in documents:
        pred_events = predictions.get(document_id, [])
        ref_events = references.get(document_id, [])
        pred_exact = Counter(event_signature(event) for event in pred_events)
        ref_exact = Counter(event_signature(event) for event in ref_events)
        tp, fp, fn = _counter_metric(pred_exact, ref_exact)
        exact.update(tp=tp, fp=fp, fn=fn)

        pred_attributes = event_attribute_counter(document_id, pred_events)
        ref_attributes = event_attribute_counter(document_id, ref_events)
        counts = _counter_metric(pred_attributes, ref_attributes)
        per_article[document_id] = counts
        attributes.update(tp=counts[0], fp=counts[1], fn=counts[2])

        pred_duration = _duration_phase_counter(document_id, pred_events)
        ref_duration = _duration_phase_counter(document_id, ref_events)
        duration_counts = _counter_metric(pred_duration, ref_duration)
        duration_phase.update(
            tp=duration_counts[0],
            fp=duration_counts[1],
            fn=duration_counts[2],
        )
        phase_confusion.update(_phase_confusion_for_article(pred_events, ref_events))

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

    confusion_rows: dict[str, dict[str, int]] = defaultdict(dict)
    for (reference_phase, predicted_phase), count in sorted(phase_confusion.items()):
        confusion_rows[reference_phase][predicted_phase] = count

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
        "duration_phase_confusion": dict(sorted(confusion_rows.items())),
        "bootstrap_iterations": bootstrap_iterations,
        "bootstrap_seed": seed,
        "counting_semantics": "multiset; repeated identical events and attributes are retained",
    }
