#!/usr/bin/env python3
"""Run an evidence-gated offline vLLM protocol-extraction batch."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
from collections import Counter
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

import httpx

from mdmeta import user_agent
from mdmeta.benchmark import canonical_sha256
from mdmeta.llm_adapter import SchemaConstrainedEventExtractor, VLLMStructuredBackend
from mdmeta.llm_batch import (
    RESPONSE_SCHEMA_FILENAME,
    SCHEMA_VERSION,
    atomic_write_json,
    compact_summary,
    fetch_frozen_jats,
    load_committed_response_schema,
    run_model_batch,
    select_articles,
    validate_sha256,
    validate_source_manifest,
)
from mdmeta.model_snapshot import load_and_verify_model_snapshot


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _version(distribution: str) -> str | None:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return None


def _bounded_int(value: str, *, minimum: int, maximum: int, name: str) -> int:
    parsed = int(value)
    if not minimum <= parsed <= maximum:
        raise argparse.ArgumentTypeError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _bounded_float(value: str, *, minimum: float, maximum: float, name: str) -> float:
    parsed = float(value)
    if not minimum <= parsed <= maximum:
        raise argparse.ArgumentTypeError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--jats-cache-dir", type=Path, required=True)
    parser.add_argument("--model-snapshot-dir", type=Path, required=True)
    parser.add_argument("--model-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    parser.add_argument("--checkpoint-output", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-archive-sha256", required=True)
    parser.add_argument(
        "--article-limit",
        type=lambda value: _bounded_int(
            value, minimum=1, maximum=10_000, name="article limit"
        ),
    )
    parser.add_argument("--document-id", action="append", default=[])
    parser.add_argument(
        "--batch-size",
        type=lambda value: _bounded_int(value, minimum=1, maximum=512, name="batch size"),
        default=32,
    )
    parser.add_argument(
        "--max-tokens",
        type=lambda value: _bounded_int(
            value, minimum=128, maximum=16_384, name="maximum output tokens"
        ),
        default=4_096,
    )
    parser.add_argument(
        "--max-model-len",
        type=lambda value: _bounded_int(
            value, minimum=2_048, maximum=32_768, name="maximum model length"
        ),
        default=16_384,
    )
    parser.add_argument(
        "--gpu-memory-utilization",
        type=lambda value: _bounded_float(
            value,
            minimum=0.5,
            maximum=0.95,
            name="GPU memory utilization",
        ),
        default=0.8,
    )
    parser.add_argument("--seed", type=int, default=3997)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--no-determinism-check", action="store_true")
    parser.add_argument("--require-cached-jats", action="store_true")
    parser.add_argument(
        "--maximum-generation-rejection-fraction",
        type=lambda value: _bounded_float(
            value,
            minimum=0.0,
            maximum=1.0,
            name="maximum generation rejection fraction",
        ),
        default=0.01,
    )
    parser.add_argument(
        "--minimum-event-count",
        type=lambda value: _bounded_int(
            value, minimum=0, maximum=1_000_000, name="minimum event count"
        ),
        default=1,
    )
    return parser.parse_args()


def _slurm_metadata() -> dict[str, str | None]:
    return {
        "job_id": os.environ.get("SLURM_JOB_ID"),
        "account": os.environ.get("SLURM_JOB_ACCOUNT"),
        "partition": os.environ.get("SLURM_JOB_PARTITION"),
        "node": os.environ.get("SLURMD_NODENAME"),
    }


def _validate_source_identity(commit: str, archive_sha256: str) -> None:
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError("source commit must be a full lowercase Git SHA-1")
    validate_sha256(archive_sha256, field="source archive digest")


def _sanitized_model_provenance(
    manifest: dict[str, Any],
    backend: VLLMStructuredBackend,
) -> dict[str, Any]:
    backend_provenance = backend.provenance
    backend_provenance["model"] = manifest["repo_id"]
    backend_provenance["local_snapshot_path_recorded"] = False
    return {
        "repo_id": manifest["repo_id"],
        "revision": manifest["revision"],
        "tokenizer_revision": manifest["tokenizer_revision"],
        "license": manifest["license"],
        "gated": manifest["gated"],
        "trust_remote_code": manifest["trust_remote_code"],
        "snapshot_manifest_sha256": manifest["manifest_sha256"],
        "file_count": manifest["file_count"],
        "total_size_bytes": manifest["total_size_bytes"],
        "weight_file_count": manifest["weight_file_count"],
        "weight_size_bytes": manifest["weight_size_bytes"],
        "backend": backend_provenance,
    }


def main() -> int:
    args = _parse_args()
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "running",
        "started_at": _utc_now(),
        "accuracy_evaluated": False,
        "human_reference_used": False,
        "interpretation": (
            "model integration, schema/evidence validation and throughput evidence only"
        ),
    }
    exit_code = 0
    try:
        _validate_source_identity(args.source_commit, args.source_archive_sha256)
        source_payload = json.loads(args.source_manifest.read_text(encoding="utf-8"))
        response_schema = load_committed_response_schema(
            Path(__file__).resolve().parents[1] / "schemas" / RESPONSE_SCHEMA_FILENAME
        )
        all_articles = validate_source_manifest(source_payload)
        articles = select_articles(
            all_articles,
            limit=args.article_limit,
            document_ids=args.document_id,
        )
        result["source"] = {
            "commit": args.source_commit,
            "archive_sha256": args.source_archive_sha256,
        }
        result["slurm"] = _slurm_metadata()
        result["runtime"] = {
            "architecture": platform.machine(),
            "python": platform.python_version(),
            "vllm": _version("vllm"),
            "torch": _version("torch"),
            "transformers": _version("transformers"),
            "pydantic": _version("pydantic"),
            "httpx": _version("httpx"),
        }
        result["corpus"] = {
            "study_id": source_payload.get("study_id"),
            "study_status": source_payload.get("study_status"),
            "manifest_sha256": source_payload["manifest_sha256"],
            "manifest_article_count": len(all_articles),
            "selected_article_count": len(articles),
            "selection_method": (
                "explicit_document_id_order" if args.document_id else "manifest_prefix"
            ),
            "selected_document_ids": [article.document_id for article in articles],
            "selected_split_counts": dict(
                sorted(Counter(article.split for article in articles).items())
            ),
        }
        result["configuration"] = {
            "batch_size": args.batch_size,
            "max_tokens": args.max_tokens,
            "max_model_len": args.max_model_len,
            "gpu_memory_utilization": args.gpu_memory_utilization,
            "seed": args.seed,
            "temperature": 0.0,
            "determinism_check": not args.no_determinism_check,
            "maximum_generation_rejection_fraction": (
                args.maximum_generation_rejection_fraction
            ),
            "source_snapshot_policy": "private_cache_with_frozen_sha256_gate",
            "network_allowed_for_jats": not args.require_cached_jats,
            "task_unit": "one_protocol_relevant_jats_paragraph",
        }

        model_manifest = load_and_verify_model_snapshot(
            args.model_snapshot_dir,
            args.model_manifest,
        )
        xml_by_document: dict[str, bytes] = {}
        cache_hits = 0
        downloaded = 0
        headers = {"User-Agent": user_agent("roihu-llm-protocol-batch")}
        with httpx.Client(
            timeout=args.timeout,
            headers=headers,
            follow_redirects=True,
        ) as client:
            for article in articles:
                xml_bytes, cache_hit = fetch_frozen_jats(
                    article,
                    cache_dir=args.jats_cache_dir,
                    client=client,
                    retries=args.retries,
                    allow_network=not args.require_cached_jats,
                )
                xml_by_document[article.document_id] = xml_bytes
                cache_hits += int(cache_hit)
                downloaded += int(not cache_hit)
        result["jats"] = {
            "article_count": len(xml_by_document),
            "cache_hit_count": cache_hits,
            "downloaded_count": downloaded,
            "total_size_bytes": sum(len(item) for item in xml_by_document.values()),
            "all_frozen_sha256_matched": True,
            "cache_path_recorded": False,
        }
        if args.require_cached_jats and (downloaded != 0 or cache_hits != len(articles)):
            raise RuntimeError("GPU inference requires every JATS input to be pre-staged")

        backend = VLLMStructuredBackend(
            model=str(args.model_snapshot_dir),
            revision=model_manifest["revision"],
            tokenizer_revision=model_manifest["tokenizer_revision"],
            max_tokens=args.max_tokens,
            seed=args.seed,
            dtype="bfloat16",
            max_model_len=args.max_model_len,
            tensor_parallel_size=1,
            gpu_memory_utilization=args.gpu_memory_utilization,
        )
        result["model"] = _sanitized_model_provenance(model_manifest, backend)
        model_label = f"{model_manifest['repo_id']}@{model_manifest['revision']}"
        extractor = SchemaConstrainedEventExtractor(backend, model_label)

        def checkpoint(payload: dict[str, Any]) -> None:
            atomic_write_json(args.checkpoint_output, payload)

        batch_result = run_model_batch(
            backend=backend,
            extractor=extractor,
            articles=articles,
            xml_by_document=xml_by_document,
            response_schema=response_schema,
            batch_size=args.batch_size,
            determinism_check=not args.no_determinism_check,
            checkpoint=checkpoint,
        )
        result["batch"] = batch_result
        schema_rejections = batch_result["classification_counts"].get("schema_rejected", 0)
        generation_rejections = batch_result["classification_counts"].get(
            "generation_rejected", 0
        )
        if batch_result["task_count_classified"] != batch_result["task_count"]:
            raise RuntimeError("not every model task received an explicit classification")
        if batch_result["task_count"] < 1:
            raise RuntimeError("selected corpus produced no protocol paragraph tasks")
        articles_without_tasks = [
            document_id
            for document_id, row in batch_result["per_article"].items()
            if row["paragraph_count"] < 1
        ]
        if articles_without_tasks:
            raise RuntimeError(
                "selected articles produced no protocol tasks: "
                + ", ".join(articles_without_tasks)
            )
        evidence_valid_responses = sum(
            batch_result["classification_counts"].get(name, 0)
            for name in ("accepted", "accepted_with_evidence_rejections")
        )
        if evidence_valid_responses < 1:
            raise RuntimeError("model produced no evidence-valid paragraph response")
        if batch_result["event_count"] < args.minimum_event_count:
            raise RuntimeError(
                f"model produced {batch_result['event_count']} accepted events; "
                f"minimum is {args.minimum_event_count}"
            )
        if schema_rejections:
            raise RuntimeError(f"{schema_rejections} structured responses failed their schema")
        maximum_generation_rejections = int(
            batch_result["task_count"] * args.maximum_generation_rejection_fraction
        )
        if generation_rejections > maximum_generation_rejections:
            raise RuntimeError(
                f"{generation_rejections} generations were rejected; maximum allowed is "
                f"{maximum_generation_rejections} of {batch_result['task_count']} tasks"
            )
        check = batch_result["determinism_check"]
        if check["performed"] and check["identical"] is not True:
            raise RuntimeError("temperature-zero repeated inference was not identical")
        result["status"] = "pass"
    except Exception as error:
        exit_code = 1
        result["status"] = "fail"
        result["error"] = {
            "type": type(error).__name__,
            "message": str(error),
        }
    finally:
        result["completed_at"] = _utc_now()
        result["result_sha256"] = canonical_sha256(result)
        atomic_write_json(args.output, result)
        atomic_write_json(args.summary_output, compact_summary(result))
    print(
        json.dumps(
            {
                "status": result["status"],
                "result_sha256": result["result_sha256"],
                "article_count": result.get("corpus", {}).get("selected_article_count"),
                "task_count": result.get("batch", {}).get("task_count"),
                "classification_counts": result.get("batch", {}).get(
                    "classification_counts"
                ),
                "event_count": result.get("batch", {}).get("event_count"),
                "usage": result.get("batch", {}).get("usage"),
            },
            indent=2,
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
