from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import EventType


class AnnotationFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    annotation_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    annotator_id: str = Field(min_length=1)
    field_name: str = Field(min_length=1)
    normalized_value: str | int | float
    unit: str | None = None
    event_type: EventType = EventType.UNKNOWN
    paragraph_id: str = Field(min_length=1)
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    quote: str = Field(min_length=1)
    note: str | None = None

    @model_validator(mode="after")
    def check_span(self) -> "AnnotationFact":
        if self.end_char - self.start_char != len(self.quote):
            raise ValueError("quote length must equal annotation span length")
        return self

    def semantic_key(self) -> tuple[str, str, str, str | None, str]:
        return (
            self.document_id,
            self.field_name,
            json.dumps(self.normalized_value, sort_keys=True),
            self.unit,
            self.event_type.value,
        )

    def exact_key(self) -> tuple[str, str, str, str | None, str, str, int, int]:
        return (*self.semantic_key(), self.paragraph_id, self.start_char, self.end_char)


def load_annotations(path: str | Path) -> list[AnnotationFact]:
    path = Path(path)
    if path.suffix.lower() == ".jsonl":
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload["facts"] if isinstance(payload, dict) else payload
    return [AnnotationFact.model_validate(row) for row in rows]


def _agreement(count_agreed: int, count_a: int, count_b: int) -> float:
    denominator = count_agreed + count_a + count_b
    return count_agreed / denominator if denominator else 1.0


def compare_annotators(
    annotations_a: list[AnnotationFact],
    annotations_b: list[AnnotationFact],
) -> dict[str, Any]:
    exact_a = {fact.exact_key(): fact for fact in annotations_a}
    exact_b = {fact.exact_key(): fact for fact in annotations_b}
    semantic_a = {fact.semantic_key() for fact in annotations_a}
    semantic_b = {fact.semantic_key() for fact in annotations_b}

    agreed_exact = set(exact_a) & set(exact_b)
    only_a = set(exact_a) - set(exact_b)
    only_b = set(exact_b) - set(exact_a)
    agreed_semantic = semantic_a & semantic_b

    by_field: dict[str, dict[str, int | float]] = defaultdict(
        lambda: {"agreed": 0, "only_a": 0, "only_b": 0}
    )
    for key in agreed_exact:
        by_field[key[1]]["agreed"] += 1
    for key in only_a:
        by_field[key[1]]["only_a"] += 1
    for key in only_b:
        by_field[key[1]]["only_b"] += 1
    for counts in by_field.values():
        counts["exact_set_agreement"] = _agreement(
            int(counts["agreed"]), int(counts["only_a"]), int(counts["only_b"])
        )

    return {
        "agreement_definitions": {
            "exact": "normalized fact, unit, event type, paragraph, and character span",
            "semantic": "normalized fact, unit, and event type; evidence location ignored",
        },
        "annotator_a_count": len(annotations_a),
        "annotator_b_count": len(annotations_b),
        "exact_agreed_count": len(agreed_exact),
        "exact_only_a_count": len(only_a),
        "exact_only_b_count": len(only_b),
        "exact_set_agreement": _agreement(len(agreed_exact), len(only_a), len(only_b)),
        "semantic_agreed_count": len(agreed_semantic),
        "semantic_only_a_count": len(semantic_a - semantic_b),
        "semantic_only_b_count": len(semantic_b - semantic_a),
        "semantic_set_agreement": _agreement(
            len(agreed_semantic), len(semantic_a - semantic_b), len(semantic_b - semantic_a)
        ),
        "by_field": dict(sorted(by_field.items())),
        "disagreements": {
            "only_a": [exact_a[key].model_dump(mode="json") for key in sorted(only_a)],
            "only_b": [exact_b[key].model_dump(mode="json") for key in sorted(only_b)],
        },
    }


def write_adjudication_template(comparison: dict[str, Any], path: str | Path) -> None:
    items = []
    for source in ("only_a", "only_b"):
        for candidate in comparison["disagreements"][source]:
            items.append(
                {
                    "source": source,
                    "candidate": candidate,
                    "decision": "pending",
                    "adjudicated_fact": None,
                    "adjudicator_note": None,
                }
            )
    output = {
        "status": "not_adjudicated",
        "allowed_decisions": ["accept", "reject", "replace"],
        "items": items,
    }
    Path(path).write_text(json.dumps(output, indent=2), encoding="utf-8")
