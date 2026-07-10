from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .models import FieldName, ProtocolPhase


class AnnotationFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    annotation_id: str
    document_id: str
    annotator_id: str
    field_name: FieldName
    normalized_value: str | int | float
    unit: str | None = None
    phase: ProtocolPhase = "unspecified"
    paragraph_id: str
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    quote: str = Field(min_length=1)
    note: str | None = None

    def comparison_key(self) -> tuple[Any, ...]:
        return (
            self.document_id,
            self.field_name,
            str(self.normalized_value),
            self.unit,
            self.phase,
            self.paragraph_id,
            self.start_char,
            self.end_char,
        )


def load_annotations(path: str | Path) -> list[AnnotationFact]:
    path = Path(path)
    if path.suffix == ".jsonl":
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload["facts"] if isinstance(payload, dict) else payload
    return [AnnotationFact.model_validate(row) for row in rows]


def compare_annotators(
    annotations_a: list[AnnotationFact], annotations_b: list[AnnotationFact]
) -> dict[str, Any]:
    keys_a = {item.comparison_key(): item for item in annotations_a}
    keys_b = {item.comparison_key(): item for item in annotations_b}
    agreed = sorted(set(keys_a) & set(keys_b))
    only_a = sorted(set(keys_a) - set(keys_b))
    only_b = sorted(set(keys_b) - set(keys_a))

    by_field: dict[str, dict[str, int | float]] = defaultdict(
        lambda: {"agreed": 0, "only_a": 0, "only_b": 0}
    )
    for key in agreed:
        by_field[key[1]]["agreed"] += 1
    for key in only_a:
        by_field[key[1]]["only_a"] += 1
    for key in only_b:
        by_field[key[1]]["only_b"] += 1
    for stats in by_field.values():
        denominator = stats["agreed"] + stats["only_a"] + stats["only_b"]
        stats["set_agreement"] = stats["agreed"] / denominator if denominator else 1.0

    denominator = len(agreed) + len(only_a) + len(only_b)
    return {
        "agreement_definition": "exact normalized fact, phase, paragraph and character span",
        "annotator_a_count": len(annotations_a),
        "annotator_b_count": len(annotations_b),
        "agreed_count": len(agreed),
        "only_a_count": len(only_a),
        "only_b_count": len(only_b),
        "set_agreement": len(agreed) / denominator if denominator else 1.0,
        "by_field": dict(sorted(by_field.items())),
        "disagreements": {
            "only_a": [keys_a[key].model_dump(mode="json") for key in only_a],
            "only_b": [keys_b[key].model_dump(mode="json") for key in only_b],
        },
    }


def write_adjudication_template(comparison: dict[str, Any], path: str | Path) -> None:
    rows = []
    for source in ("only_a", "only_b"):
        for item in comparison["disagreements"][source]:
            rows.append(
                {
                    "source": source,
                    "candidate": item,
                    "decision": "pending",
                    "adjudicated_fact": None,
                    "adjudicator_note": None,
                }
            )
    Path(path).write_text(json.dumps({"items": rows}, indent=2), encoding="utf-8")
