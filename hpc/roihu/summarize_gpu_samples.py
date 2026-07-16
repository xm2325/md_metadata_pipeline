#!/usr/bin/env python3
"""Create a compact, non-identifying summary of nvidia-smi samples."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

from mdmeta.llm_batch import atomic_write_json


_NUMBER = re.compile(r"[+-]?\d+(?:\.\d+)?")


def _number(value: str) -> float:
    match = _NUMBER.search(value)
    if match is None:
        raise ValueError(f"GPU sample has no numeric value: {value!r}")
    return float(match.group(0))


def _column(row: dict[str, str], prefix: str) -> str:
    matches = [value for key, value in row.items() if key.strip().startswith(prefix)]
    if len(matches) != 1:
        raise ValueError(f"expected one GPU sample column starting with {prefix!r}")
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    with args.input.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise SystemExit("GPU sampler produced no records")
    utilizations = [_number(_column(row, "utilization.gpu")) for row in rows]
    memory_used = [_number(_column(row, "memory.used")) for row in rows]
    power = [_number(_column(row, "power.draw")) for row in rows]
    temperatures = [_number(_column(row, "temperature.gpu")) for row in rows]
    gpu_indices = {str(_column(row, "index")).strip() for row in rows}
    if max(utilizations) <= 0:
        raise SystemExit("GPU sampler never observed non-zero compute utilization")
    result = {
        "schema_version": "mdmeta.roihu.gpu-samples.v1",
        "sample_count": len(rows),
        "visible_gpu_count": len(gpu_indices),
        "mean_gpu_utilization_percent": sum(utilizations) / len(utilizations),
        "max_gpu_utilization_percent": max(utilizations),
        "max_memory_used_mib": max(memory_used),
        "max_power_draw_watts": max(power),
        "max_temperature_celsius": max(temperatures),
        "raw_gpu_uuid_retained_only_in_private_log": True,
    }
    atomic_write_json(args.output, result)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
