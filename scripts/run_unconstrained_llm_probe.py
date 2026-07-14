from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx


TEXT = (
    "The production simulation was run for 100 ns at 300 K and 1 bar in the NPT "
    "ensemble with a 2 fs time step using three replicates."
)

EXPECTED = {
    "event_type": "production",
    "quote": TEXT,
    "duration_raw": "100 ns",
    "temperature_raw": "300 K",
    "pressure_raw": "1 bar",
    "timestep_raw": "2 fs",
    "ensemble_raw": "NPT",
    "replicates_raw": "three",
}


def _extract_json(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    payload = json.loads(stripped)
    if not isinstance(payload, dict):
        raise ValueError("model output must be a JSON object")
    return payload


def run(output: Path, markdown: Path) -> dict[str, Any]:
    base_url = os.environ.get("MDMETA_LLM_BASE_URL", "http://127.0.0.1:8081/v1").rstrip("/")
    model_id = os.environ.get("MDMETA_LLM_MODEL", "Qwen/Qwen3.5-0.8B")
    endpoint = f"{base_url}/chat/completions"
    prompt = f"""Extract the molecular-dynamics production event from the paragraph below.
Return only one JSON object with exactly these string fields: event_type, quote, duration_raw,
temperature_raw, pressure_raw, timestep_raw, ensemble_raw, replicates_raw. Copy quote and all raw
values exactly from the source. Do not convert units and do not add Markdown.

SOURCE:
{TEXT}
"""
    request = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": "Return only valid JSON with no explanation."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "top_p": 1,
        "seed": 0,
        "max_tokens": 200,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }

    raw_content: str | None = None
    parsed: dict[str, Any] | None = None
    error: dict[str, str] | None = None
    response_metadata: dict[str, Any] | None = None
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=180.0) as client:
            response = client.post(endpoint, json=request)
            response.raise_for_status()
            envelope = response.json()
        choice = envelope["choices"][0]
        raw_content = choice["message"]["content"]
        parsed = _extract_json(raw_content)
        response_metadata = {
            "completion_id": envelope.get("id"),
            "finish_reason": choice.get("finish_reason"),
            "usage": envelope.get("usage"),
        }
    except Exception as exc:  # retain operational evidence
        error = {"type": type(exc).__name__, "message": str(exc)}
    latency_ms = (time.perf_counter() - started) * 1000

    checks: dict[str, bool] = {}
    if parsed is not None:
        for field, expected in EXPECTED.items():
            checks[f"{field}_exact"] = parsed.get(field) == expected
        quote = parsed.get("quote") if isinstance(parsed.get("quote"), str) else ""
        checks["quote_is_source_substring"] = bool(quote) and quote in TEXT
        for field in (
            "duration_raw",
            "temperature_raw",
            "pressure_raw",
            "timestep_raw",
            "ensemble_raw",
            "replicates_raw",
        ):
            value = parsed.get(field)
            checks[f"{field}_inside_quote"] = isinstance(value, str) and value in quote
    strict_pass = error is None and bool(checks) and all(checks.values())

    payload = {
        "schema_version": "unconstrained-json-control-v1",
        "model_id": model_id,
        "endpoint": endpoint,
        "latency_ms": latency_ms,
        "text": TEXT,
        "expected": EXPECTED,
        "raw_content": raw_content,
        "parsed": parsed,
        "checks": checks,
        "strict_pass": strict_pass,
        "error": error,
        "response_metadata": response_metadata,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "## Live Qwen3.5-0.8B unconstrained JSON control",
        "",
        f"- Strict pass: `{strict_pass}`",
        f"- Latency: `{latency_ms:.1f} ms`",
        f"- Error: `{json.dumps(error, ensure_ascii=False)}`",
        f"- Response metadata: `{json.dumps(response_metadata, ensure_ascii=False, sort_keys=True)}`",
        "",
        "### Checks",
    ]
    lines.extend(f"- {name}: `{passed}`" for name, passed in sorted(checks.items()))
    lines.extend(
        [
            "",
            "### Raw content",
            "```text",
            raw_content or "null",
            "```",
            "",
            "### Parsed JSON",
            "```json",
            json.dumps(parsed, indent=2, ensure_ascii=False, sort_keys=True),
            "```",
            "",
            "This control uses the same model and source paragraph but omits JSON Schema constrained "
            "decoding. It is diagnostic only; production candidates must still pass deterministic "
            "evidence and value validation.",
        ]
    )
    markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an unconstrained Qwen JSON control probe")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args()
    payload = run(args.output, args.markdown)
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
