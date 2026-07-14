from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from mdmeta.llm_adapter import (
    LLMEventResponse,
    SchemaConstrainedEventExtractor,
)
from mdmeta.openai_backend import OpenAICompatibleStructuredBackend
from mdmeta.protocol_events import Paragraph


CASES: list[dict[str, Any]] = [
    {
        "case_id": "single_production_complete",
        "text": (
            "The production simulation was run for 100 ns at 300 K and 1 bar in the NPT "
            "ensemble with a 2 fs time step using three replicates."
        ),
        "expected": [
            {
                "event_type": "production",
                "duration_ps": 100000.0,
                "temperature_k": 300.0,
                "pressure_bar": 1.0,
                "timestep_fs": 2.0,
                "ensemble": "NPT",
                "replicates": 3,
            }
        ],
    },
    {
        "case_id": "three_phases",
        "text": (
            "The system was heated from 0 to 300 K over 100 ps, equilibrated for 2 ns in "
            "the NPT ensemble at 1 bar, and then simulated for 500 ns in the NVT ensemble."
        ),
        "expected": [
            {"event_type": "heating", "duration_ps": 100.0, "temperature_k": 300.0},
            {
                "event_type": "equilibration",
                "duration_ps": 2000.0,
                "pressure_bar": 1.0,
                "ensemble": "NPT",
            },
            {"event_type": "production", "duration_ps": 500000.0, "ensemble": "NVT"},
        ],
    },
    {
        "case_id": "sampling_vs_timestep",
        "text": (
            "Coordinates were saved every 10 ps during a 200 ns production simulation "
            "performed at 310 K with a 2 fs integration time step."
        ),
        "expected": [
            {
                "event_type": "production",
                "duration_ps": 200000.0,
                "temperature_k": 310.0,
                "timestep_fs": 2.0,
            },
            {"event_type": "sampling_interval", "duration_ps": 10.0},
        ],
    },
    {
        "case_id": "analysis_window",
        "text": "Only the final 50 ns of each 250 ns trajectory were used for analysis.",
        "expected": [{"event_type": "analysis_window", "duration_ps": 50000.0}],
    },
    {
        "case_id": "non_md_negative",
        "text": "The crystal structure was determined at 2.1 Å resolution and deposited as PDB 6VSB.",
        "expected": [],
    },
    {
        "case_id": "equilibration_restraints",
        "text": (
            "During the 5 ns equilibration, protein heavy atoms were restrained with a "
            "harmonic force constant while the system was maintained at 300 K."
        ),
        "expected": [
            {
                "event_type": "equilibration",
                "duration_ps": 5000.0,
                "temperature_k": 300.0,
            }
        ],
    },
    {
        "case_id": "coupling_time_trap",
        "text": (
            "A thermostat coupling time of 2 ps was used with a 2 fs integration step for "
            "a 100 ns production run."
        ),
        "expected": [
            {"event_type": "production", "duration_ps": 100000.0, "timestep_fs": 2.0}
        ],
    },
    {
        "case_id": "replicate_word_count",
        "text": "Five independent 20 ns production simulations were performed at 298 K.",
        "expected": [
            {
                "event_type": "production",
                "duration_ps": 20000.0,
                "temperature_k": 298.0,
                "replicates": 5,
            }
        ],
    },
]


class StaticBackend:
    def __init__(self, payload: dict[str, Any], model_id: str) -> None:
        self.payload = payload
        self.model_id = model_id
        self.last_audit = None

    def complete(self, prompt: str, json_schema: dict[str, Any]) -> dict[str, Any]:
        del prompt, json_schema
        return self.payload


def _matches(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    if actual.get("event_type") != expected["event_type"]:
        return False
    for key, expected_value in expected.items():
        if key == "event_type":
            continue
        actual_value = actual.get(key)
        if isinstance(expected_value, float):
            if actual_value is None or abs(float(actual_value) - expected_value) > 1e-6:
                return False
        elif actual_value != expected_value:
            return False
    return True


def _strict_case_match(events: list[dict[str, Any]], expected: list[dict[str, Any]]) -> bool:
    if len(events) != len(expected):
        return False
    remaining = events.copy()
    for target in expected:
        index = next((i for i, event in enumerate(remaining) if _matches(event, target)), None)
        if index is None:
            return False
        remaining.pop(index)
    return not remaining


def run(output: Path) -> dict[str, Any]:
    backend = OpenAICompatibleStructuredBackend.from_env()
    results: list[dict[str, Any]] = []
    try:
        for case in CASES:
            paragraph = Paragraph(
                document_id=f"SMOKE-{case['case_id']}",
                section="Methods",
                paragraph_id="p1",
                text=case["text"],
            )
            prompt = SchemaConstrainedEventExtractor._prompt([paragraph])
            raw: dict[str, Any] | None = None
            accepted: list[dict[str, Any]] = []
            error: dict[str, str] | None = None
            try:
                raw = backend.complete(prompt, LLMEventResponse.model_json_schema())
                extractor = SchemaConstrainedEventExtractor(
                    StaticBackend(raw, backend.model_id), backend.model_id
                )
                accepted = [
                    event.model_dump(mode="json") for event in extractor.extract([paragraph])
                ]
            except Exception as exc:  # diagnostic benchmark must retain all cases
                error = {"type": type(exc).__name__, "message": str(exc)}
            strict_match = error is None and _strict_case_match(accepted, case["expected"])
            results.append(
                {
                    "case_id": case["case_id"],
                    "text": case["text"],
                    "expected": case["expected"],
                    "raw_model_response": raw,
                    "accepted_events": accepted,
                    "validation_error": error,
                    "strict_case_match": strict_match,
                    "audit": backend.last_audit.model_dump(mode="json")
                    if backend.last_audit is not None
                    else None,
                }
            )
    finally:
        backend.close()

    valid_cases = sum(item["validation_error"] is None for item in results)
    strict_matches = sum(item["strict_case_match"] for item in results)
    payload = {
        "schema_version": "qwen-live-smoke-v1",
        "model_id": backend.model_id,
        "case_count": len(results),
        "validator_accepted_case_count": valid_cases,
        "validator_rejected_case_count": len(results) - valid_cases,
        "strict_case_match_count": strict_matches,
        "strict_case_accuracy": strict_matches / len(results),
        "cases": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def _summary(payload: dict[str, Any]) -> str:
    lines = [
        "# Live Qwen3.5-0.8B MD extraction smoke test",
        "",
        f"- Cases: {payload['case_count']}",
        f"- Validator accepted: {payload['validator_accepted_case_count']}",
        f"- Validator rejected: {payload['validator_rejected_case_count']}",
        f"- Strict case matches: {payload['strict_case_match_count']}",
        f"- Strict case accuracy: {payload['strict_case_accuracy']:.3f}",
        "",
        "| Case | Validator | Strict match | Accepted events |",
        "|---|---:|---:|---:|",
    ]
    for case in payload["cases"]:
        lines.append(
            f"| {case['case_id']} | "
            f"{'PASS' if case['validation_error'] is None else 'REJECT'} | "
            f"{'YES' if case['strict_case_match'] else 'NO'} | "
            f"{len(case['accepted_events'])} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a real open-weight Qwen MD extraction smoke test")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()
    payload = run(args.output)
    summary = _summary(payload)
    print(summary)
    if args.summary is not None:
        args.summary.write_text(summary, encoding="utf-8")


if __name__ == "__main__":
    main()
