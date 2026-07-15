#!/usr/bin/env python3
"""Run a bounded, evidence-producing CUDA smoke test on Roihu-GPU."""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import re
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "mdmeta.roihu.gpu-smoke.v1"
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _bounded_int(value: str, *, minimum: int, maximum: int, name: str) -> int:
    parsed = int(value)
    if not minimum <= parsed <= maximum:
        raise argparse.ArgumentTypeError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _bounded_float(value: str, *, minimum: float, maximum: float, name: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or not minimum <= parsed <= maximum:
        raise argparse.ArgumentTypeError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-archive-sha256", required=True)
    parser.add_argument(
        "--matrix-size",
        type=lambda value: _bounded_int(
            value, minimum=1024, maximum=16384, name="matrix size"
        ),
        default=8192,
    )
    parser.add_argument(
        "--minimum-gemm-seconds",
        type=lambda value: _bounded_float(
            value, minimum=2.0, maximum=60.0, name="minimum GEMM seconds"
        ),
        default=8.0,
    )
    return parser.parse_args()


def _validate_source(source_commit: str, archive_sha256: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("source commit must be a full lowercase Git SHA-1")
    if SHA256_PATTERN.fullmatch(archive_sha256) is None:
        raise ValueError("source archive digest must be a lowercase SHA-256")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        temporary_path.unlink(missing_ok=True)


def _slurm_metadata() -> dict[str, str | None]:
    return {
        "job_id": os.environ.get("SLURM_JOB_ID"),
        "account": os.environ.get("SLURM_JOB_ACCOUNT"),
        "partition": os.environ.get("SLURM_JOB_PARTITION"),
        "node": os.environ.get("SLURMD_NODENAME"),
    }


def _fp32_correctness(torch: Any, device: Any) -> dict[str, Any]:
    torch.manual_seed(20260715)
    torch.set_float32_matmul_precision("highest")
    left_cpu = torch.randn((128, 128), dtype=torch.float32)
    right_cpu = torch.randn((128, 128), dtype=torch.float32)
    expected = left_cpu @ right_cpu
    observed = left_cpu.to(device) @ right_cpu.to(device)
    observed_cpu = observed.cpu()
    maximum_absolute_error = float((expected - observed_cpu).abs().max().item())
    passed = bool(torch.allclose(expected, observed_cpu, rtol=1e-4, atol=1e-4))
    if not passed:
        raise RuntimeError(
            f"FP32 CPU/GPU correctness check failed: max error {maximum_absolute_error}"
        )
    return {
        "status": "pass",
        "shape": [128, 128],
        "maximum_absolute_error": maximum_absolute_error,
    }


def _bf16_gemm(
    torch: Any,
    device: Any,
    *,
    matrix_size: int,
    minimum_seconds: float,
) -> dict[str, Any]:
    torch.manual_seed(20260715)
    left = torch.randn((matrix_size, matrix_size), dtype=torch.bfloat16, device=device)
    right = torch.randn((matrix_size, matrix_size), dtype=torch.bfloat16, device=device)

    for _ in range(2):
        output = left @ right
    torch.cuda.synchronize(device)
    torch.cuda.reset_peak_memory_stats(device)

    started = time.perf_counter()
    iterations = 0
    elapsed = 0.0
    while elapsed < minimum_seconds:
        output = left @ right
        iterations += 1
        if iterations % 4 == 0:
            torch.cuda.synchronize(device)
            elapsed = time.perf_counter() - started
    torch.cuda.synchronize(device)
    elapsed = time.perf_counter() - started

    finite = bool(torch.isfinite(output).all().item())
    if not finite:
        raise RuntimeError("BF16 GEMM produced non-finite output")
    estimated_tflops = (2 * matrix_size**3 * iterations) / elapsed / 1_000_000_000_000
    return {
        "status": "pass",
        "dtype": "bfloat16",
        "matrix_size": matrix_size,
        "iterations": iterations,
        "elapsed_seconds": elapsed,
        "estimated_tflops": estimated_tflops,
        "output_mean": float(output.float().mean().item()),
        "output_finite": finite,
        "peak_memory_bytes": int(torch.cuda.max_memory_allocated(device)),
    }


def _scaled_dot_product_attention(torch: Any, device: Any) -> dict[str, Any]:
    torch.manual_seed(20260715)
    shape = (1, 8, 1024, 128)
    query = torch.randn(shape, dtype=torch.bfloat16, device=device)
    key = torch.randn(shape, dtype=torch.bfloat16, device=device)
    value = torch.randn(shape, dtype=torch.bfloat16, device=device)
    torch.cuda.synchronize(device)
    started = time.perf_counter()
    output = torch.nn.functional.scaled_dot_product_attention(query, key, value)
    torch.cuda.synchronize(device)
    elapsed = time.perf_counter() - started
    finite = bool(torch.isfinite(output).all().item())
    if not finite:
        raise RuntimeError("scaled dot-product attention produced non-finite output")
    return {
        "status": "pass",
        "dtype": "bfloat16",
        "shape": list(shape),
        "elapsed_seconds": elapsed,
        "output_mean": float(output.float().mean().item()),
        "output_finite": finite,
    }


def _run(args: argparse.Namespace, result: dict[str, Any]) -> None:
    _validate_source(args.source_commit, args.source_archive_sha256)
    architecture = platform.machine()
    if architecture != "aarch64":
        raise RuntimeError(f"expected Roihu-GPU aarch64 architecture, found {architecture!r}")

    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("PyTorch reports that CUDA is unavailable")
    visible_device_count = int(torch.cuda.device_count())
    if visible_device_count != 1:
        raise RuntimeError(f"expected exactly one visible GPU, found {visible_device_count}")

    device = torch.device("cuda:0")
    properties = torch.cuda.get_device_properties(device)
    if "GH200" not in properties.name.upper():
        raise RuntimeError(f"expected an NVIDIA GH200, found {properties.name!r}")

    result.update(
        {
            "source": {
                "commit": args.source_commit,
                "archive_sha256": args.source_archive_sha256,
            },
            "slurm": _slurm_metadata(),
            "runtime": {
                "architecture": architecture,
                "python": platform.python_version(),
                "torch": torch.__version__,
                "cuda": torch.version.cuda,
                "cudnn": torch.backends.cudnn.version(),
            },
            "gpu": {
                "name": properties.name,
                "visible_device_count": visible_device_count,
                "compute_capability": f"{properties.major}.{properties.minor}",
                "total_memory_bytes": int(properties.total_memory),
            },
        }
    )

    checks: dict[str, Any] = {}
    result["checks"] = checks
    checks["fp32_correctness"] = _fp32_correctness(torch, device)
    checks["bf16_gemm"] = _bf16_gemm(
        torch,
        device,
        matrix_size=args.matrix_size,
        minimum_seconds=args.minimum_gemm_seconds,
    )
    checks["scaled_dot_product_attention"] = _scaled_dot_product_attention(torch, device)
    result["status"] = "pass"


def main() -> int:
    args = _parse_args()
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "running",
        "started_at": _utc_now(),
    }
    try:
        _run(args, result)
    except Exception as error:
        result["status"] = "fail"
        result["error"] = {
            "type": type(error).__name__,
            "message": str(error),
        }
        raise
    finally:
        result["completed_at"] = _utc_now()
        _atomic_write_json(args.output, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
