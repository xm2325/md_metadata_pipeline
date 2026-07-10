from __future__ import annotations

from collections import defaultdict
from typing import Any

from .models import MDRecord


def _key(field_name: str, value: Any, unit: str | None) -> tuple[str, str, str | None]:
    return field_name, str(value), unit


def evaluate(record: MDRecord, gold: dict[str, Any]) -> dict[str, Any]:
    predicted = {_key(f.field_name, f.normalized_value, f.unit) for f in record.facts}
    expected = {
        _key(item["field_name"], item["normalized_value"], item.get("unit"))
        for item in gold["facts"]
    }
    true_positive = predicted & expected
    false_positive = predicted - expected
    false_negative = expected - predicted
    precision = len(true_positive) / len(predicted) if predicted else 0.0
    recall = len(true_positive) / len(expected) if expected else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    by_field: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    for item in true_positive:
        by_field[item[0]]["tp"] += 1
    for item in false_positive:
        by_field[item[0]]["fp"] += 1
    for item in false_negative:
        by_field[item[0]]["fn"] += 1

    evidence_valid = all(
        evidence.end_char - evidence.start_char == len(evidence.quote)
        for fact in record.facts
        for evidence in fact.evidence
    )
    return {
        "evaluation_scope": "synthetic_software_regression_only"
        if gold.get("synthetic")
        else "curated_corpus",
        "tp": len(true_positive),
        "fp": len(false_positive),
        "fn": len(false_negative),
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "evidence_offset_integrity": evidence_valid,
        "by_field": dict(sorted(by_field.items())),
        "false_positive_items": sorted(false_positive),
        "false_negative_items": sorted(false_negative),
    }
