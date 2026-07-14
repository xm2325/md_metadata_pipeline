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
    "duration": "100 ns",
    "temperature": "300 K",
    "pressure": "1 bar",
    "timestep": "2 fs",
    "ensemble": "NPT",
    "replicates": "three",
}


def _extract_json(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    value = json.loads(stripped)
    if not isinstance(value, dict):
        raise ValueError("response is not a JSON object")
    return value


def run(output: Path, markdown: Path) -> dict[str, Any]:
    base_url = os.environ.get("MDMETA_LLM_BASE_URL", "http://127.0.0.1:8081/v1").rstrip("/")
    model = os.environ.get("MDMETA_LLM_MODEL", "Qwen/Qwen3.5-0.8B")
    endpoint = f"{base_url}/chat/completions"
    prompt = (
        "Return only compact JSON with keys duration, temperature, pressure, timestep, ensemble, "
        "replicates. Copy values exactly from this sentence: " + TEXT
    )
    request = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "top_p": 1,
        "seed": 0,
        "max_tokens": 80,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }

    raw: str | None = None
    parsed: dict[str, Any] | None = None
    error: dict[str, str] | None = None
    metadata: dict[str, Any] | None = None
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=180.0) as client:
            response = client.post(endpoint, json=request)
            response.raise_for_status()
            envelope = response.json()
        choice = envelope["choices"][0]
        raw = choice["message"]["content"]
        parsed = _extract_json(raw)
        metadata = {
            "completion_id": envelope.get("id"),
            "finish_reason": choice.get("finish_reason"),
            "usage": envelope.get("usage"),
        }
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
    latency_ms = (time.perf_counter() - started) * 1000

    checks = {
        key: parsed is not None and parsed.get(key) == expected
        for key, expected in EXPECTED.items()
    }
    strict_pass = error is None and all(checks.values())
    payload = {
        "schema_version": "minimal-positive-capability-v1",
        "model_id": model,
        "latency_ms": latency_ms,
        "raw_content": raw,
        "parsed": parsed,
        "expected": EXPECTED,
        "checks": checks,
        "strict_pass": strict_pass,
        "error": error,
        "response_metadata": metadata,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "## Live Qwen3.5-0.8B minimal positive capability probe",
        "",
        f"- Strict pass: `{strict_pass}`",
        f"- Latency: `{latency_ms:.1f} ms`",
        f"- Error: `{json.dumps(error, ensure_ascii=False)}`",
        f"- Response metadata: `{json.dumps(metadata, ensure_ascii=False, sort_keys=True)}`",
        "",
        "### Field checks",
    ]
    lines.extend(f"- {key}: `{passed}`" for key, passed in sorted(checks.items()))
    lines.extend(
        [
            "",
            "### Raw content",
            "```text",
            raw or "null",
            "```",
            "",
            "### Parsed JSON",
            "```json",
            json.dumps(parsed, indent=2, ensure_ascii=False, sort_keys=True),
            "```",
            "",
            "This deliberately short control tests field recognition only. It does not satisfy the "
            "repository's exact-span evidence contract and must not be used as a production result.",
        ]
    )
    markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a minimal positive Qwen capability probe")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output, args.markdown)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
