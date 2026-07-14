from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from mdmeta.openai_backend import OpenAICompatibleStructuredBackend


TEXT = (
    "The production simulation was run for 100 ns at 300 K and 1 bar in the NPT "
    "ensemble with a 2 fs time step using three replicates."
)

COMPACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["events"],
    "properties": {
        "events": {
            "type": "array",
            "minItems": 1,
            "maxItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "event_type",
                    "paragraph_id",
                    "quote",
                    "duration_raw",
                    "temperature_raw",
                    "pressure_raw",
                    "timestep_raw",
                    "ensemble_raw",
                    "replicates_raw",
                ],
                "properties": {
                    "event_type": {"type": "string", "enum": ["production"]},
                    "paragraph_id": {"type": "string", "enum": ["p1"]},
                    "quote": {"type": "string", "minLength": 1},
                    "duration_raw": {"type": "string", "minLength": 1},
                    "temperature_raw": {"type": "string", "minLength": 1},
                    "pressure_raw": {"type": "string", "minLength": 1},
                    "timestep_raw": {"type": "string", "minLength": 1},
                    "ensemble_raw": {"type": "string", "minLength": 1},
                    "replicates_raw": {"type": "string", "minLength": 1},
                },
            },
        }
    },
}

PROMPT = f"""Extract the explicitly stated molecular-dynamics production event.
Copy one exact contiguous quote from the paragraph. Copy each requested value exactly as written in
that quote. Do not convert units, infer values, or add explanations.

[paragraph_id=p1; section=Methods]
{TEXT}
"""

EXPECTED = {
    "event_type": "production",
    "paragraph_id": "p1",
    "duration_raw": "100 ns",
    "temperature_raw": "300 K",
    "pressure_raw": "1 bar",
    "timestep_raw": "2 fs",
    "ensemble_raw": "NPT",
    "replicates_raw": "three",
}


def run(output: Path, markdown: Path) -> dict[str, Any]:
    backend = OpenAICompatibleStructuredBackend.from_env()
    raw: dict[str, Any] | None = None
    error: dict[str, str] | None = None
    checks: dict[str, bool] = {}
    try:
        raw = backend.complete(PROMPT, COMPACT_SCHEMA)
        events = raw.get("events") if isinstance(raw, dict) else None
        checks["one_event"] = isinstance(events, list) and len(events) == 1
        event = events[0] if checks["one_event"] and isinstance(events[0], dict) else {}
        quote = event.get("quote") if isinstance(event.get("quote"), str) else ""
        checks["quote_is_exact_source_substring"] = bool(quote) and quote in TEXT
        for field, expected in EXPECTED.items():
            checks[f"{field}_exact"] = event.get(field) == expected
        for field in (
            "duration_raw",
            "temperature_raw",
            "pressure_raw",
            "timestep_raw",
            "ensemble_raw",
            "replicates_raw",
        ):
            value = event.get(field)
            checks[f"{field}_inside_quote"] = isinstance(value, str) and value in quote
    except Exception as exc:  # retain the operational result instead of hiding a failure
        error = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        backend.close()

    strict_pass = error is None and bool(checks) and all(checks.values())
    payload = {
        "schema_version": "compact-evidence-first-probe-v1",
        "model_id": backend.model_id,
        "text": TEXT,
        "expected": EXPECTED,
        "raw_model_response": raw,
        "checks": checks,
        "strict_pass": strict_pass,
        "error": error,
        "audit": backend.last_audit.model_dump(mode="json")
        if backend.last_audit is not None
        else None,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "## Live Qwen3.5-0.8B compact evidence-first probe",
        "",
        f"- Strict pass: `{strict_pass}`",
        f"- Error: `{json.dumps(error, ensure_ascii=False)}`",
        f"- Audit: `{json.dumps(payload['audit'], ensure_ascii=False, sort_keys=True)}`",
        "",
        "### Checks",
    ]
    lines.extend(f"- {name}: `{passed}`" for name, passed in sorted(checks.items()))
    lines.extend(
        [
            "",
            "### Raw model response",
            "```json",
            json.dumps(raw, indent=2, ensure_ascii=False, sort_keys=True),
            "```",
            "",
            "This diagnostic uses the same Qwen3.5-0.8B Q8 model and OpenAI-compatible backend, "
            "but asks the model only to copy evidence and raw values. Numeric conversion remains "
            "a deterministic code responsibility.",
        ]
    )
    markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a compact evidence-first Qwen extraction probe")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args()
    payload = run(args.output, args.markdown)
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
