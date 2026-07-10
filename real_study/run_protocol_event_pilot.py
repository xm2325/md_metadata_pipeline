from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from mdlit.extraction import DeterministicExtractor
from mdlit.extraction_v2 import ProtocolAwareExtractor
from mdlit.protocol import build_protocol_events
from mdlit.review_text import parse_review_text

ROOT = Path(__file__).resolve().parents[1]
ANNOTATIONS = ROOT / "real_study/annotations/reference_annotations.json"
REVIEW_DIR = ROOT / "real_study/review_text"
RESULTS = ROOT / "real_study/results/protocol_event_pilot.json"
REPORT = ROOT / "real_study/results/PROTOCOL_EVENT_PILOT.md"


def key(
    field: str, value: Any, unit: str | None, phase: str | None
) -> tuple[str, str, str | None, str]:
    return field, str(value), unit, phase or "unspecified"


def prf(tp: int, fp: int, fn: int) -> dict[str, float | int]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def evaluate_model(
    extractor: Any, gold_by_doc: dict[str, set[tuple[str, str, str | None, str]]]
) -> dict[str, Any]:
    total = Counter()
    duration = Counter()
    phase_counts: dict[str, Counter[str]] = defaultdict(Counter)
    event_counts = Counter()
    articles = []
    for path in sorted(REVIEW_DIR.glob("PMC*.txt")):
        document_id, _, paragraphs = parse_review_text(path)
        facts = extractor.extract(
            paragraphs, document_id, f"https://europepmc.org/articles/{document_id}"
        )
        events = build_protocol_events(facts)
        predicted = {key(f.field_name, f.normalized_value, f.unit, f.phase) for f in facts}
        expected = gold_by_doc[document_id]
        tp_items = predicted & expected
        fp_items = predicted - expected
        fn_items = expected - predicted
        total.update({"tp": len(tp_items), "fp": len(fp_items), "fn": len(fn_items)})

        pred_duration = {item for item in predicted if item[0] == "simulation_duration"}
        gold_duration = {item for item in expected if item[0] == "simulation_duration"}
        duration.update(
            {
                "tp": len(pred_duration & gold_duration),
                "fp": len(pred_duration - gold_duration),
                "fn": len(gold_duration - pred_duration),
            }
        )
        for item in tp_items:
            phase_counts[item[3]]["tp"] += 1
        for item in fp_items:
            phase_counts[item[3]]["fp"] += 1
        for item in fn_items:
            phase_counts[item[3]]["fn"] += 1
        event_counts["events"] += len(events)
        event_counts["events_with_phase"] += sum(event.phase != "unspecified" for event in events)
        event_counts["complete_events"] += sum(event.completeness == "complete" for event in events)
        articles.append(
            {
                "document_id": document_id,
                "predicted_facts": len(predicted),
                "reference_facts": len(expected),
                "protocol_events": len(events),
                **prf(len(tp_items), len(fp_items), len(fn_items)),
            }
        )
    return {
        "micro": prf(total["tp"], total["fp"], total["fn"]),
        "duration_phase_aware": prf(duration["tp"], duration["fp"], duration["fn"]),
        "by_phase": {
            phase: prf(counts["tp"], counts["fp"], counts["fn"])
            for phase, counts in sorted(phase_counts.items())
        },
        "event_summary": dict(event_counts),
        "articles": articles,
    }


def main() -> None:
    payload = json.loads(ANNOTATIONS.read_text(encoding="utf-8"))
    gold_by_doc: dict[str, set[tuple[str, str, str | None, str]]] = {}
    for article in payload["articles"]:
        gold_by_doc[article["document_id"]] = {
            key(
                fact["field_name"],
                fact["normalized_value"],
                fact.get("unit"),
                fact.get("phase"),
            )
            for fact in article["facts"]
            if fact.get("primary_metric", True)
        }

    results = {
        "study_scope": "development_set_phase_aware_diagnostic",
        "article_count": len(gold_by_doc),
        "annotation_status": "single_reviewer_existing_reference_set",
        "independent_test": False,
        "v1": evaluate_model(DeterministicExtractor(), gold_by_doc),
        "v2": evaluate_model(ProtocolAwareExtractor(), gold_by_doc),
    }
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(results, indent=2), encoding="utf-8")

    v1 = results["v1"]
    v2 = results["v2"]
    report = f"""# Protocol-event development diagnostic

This run uses the existing 15-article, single-reviewer reference set. It is a development diagnostic, not an independent test and not the planned 60-article dual-annotation benchmark.

| System | Phase-aware fact precision | Recall | F1 | Duration+phase F1 | Events | Events with explicit phase |
|---|---:|---:|---:|---:|---:|---:|
| v1 baseline | {v1["micro"]["precision"]:.3f} | {v1["micro"]["recall"]:.3f} | {v1["micro"]["f1"]:.3f} | {v1["duration_phase_aware"]["f1"]:.3f} | {v1["event_summary"].get("events", 0)} | {v1["event_summary"].get("events_with_phase", 0)} |
| v2 protocol-aware | {v2["micro"]["precision"]:.3f} | {v2["micro"]["recall"]:.3f} | {v2["micro"]["f1"]:.3f} | {v2["duration_phase_aware"]["f1"]:.3f} | {v2["event_summary"].get("events", 0)} | {v2["event_summary"].get("events_with_phase", 0)} |

## Interpretation

The result measures exact normalized values together with protocol phase. It is intentionally stricter than phase-free field scoring. The event count is an engineering output; it is not an accuracy metric because the current reference set contains fact annotations rather than independently adjudicated event graphs.
"""
    REPORT.write_text(report, encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
