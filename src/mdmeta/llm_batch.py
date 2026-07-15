from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .benchmark import canonical_sha256
from .integration import parse_jats_paragraphs, protocol_paragraphs
from .llm_adapter import (
    EvidenceValidationAudit,
    LLMEventResponse,
    SchemaConstrainedEventExtractor,
)
from .models import ProtocolEvent
from .protocol_events import Paragraph


SCHEMA_VERSION = "mdmeta.llm-protocol-batch.v3"
RESPONSE_SCHEMA_VERSION = "mdmeta.llm-event-response.v2"
RESPONSE_SCHEMA_FILENAME = "llm-event-response-v2.schema.json"
FULLTEXT_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/{document_id}/fullTextXML"
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_DOCUMENT_ID = re.compile(r"PMC\d+", re.IGNORECASE)
_SHA256 = re.compile(r"[0-9a-f]{64}")


def load_committed_response_schema(path: Path) -> dict[str, Any]:
    """Load the one source-controlled schema used by GPU generation and CPU replay."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("type") != "object":
        raise ValueError("committed LLM response schema is not an object schema")
    if payload.get("additionalProperties") is not False:
        raise ValueError("committed LLM response schema permits unknown top-level fields")
    candidate = payload.get("$defs", {}).get("LLMEventCandidate", {})
    if (
        not isinstance(candidate, dict)
        or candidate.get("additionalProperties") is not False
        or "event_type_raw_text" not in candidate.get("required", [])
    ):
        raise ValueError("committed LLM response schema lacks the v2 evidence contract")
    return payload


class FrozenArticle(BaseModel):
    """One immutable source commitment used by a model batch."""

    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(pattern=r"^PMC\d+$")
    split: str = Field(min_length=1)
    source_uri: str = Field(min_length=1)
    full_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class InferenceTask:
    task_id: str
    split: str
    paragraph: Paragraph
    prompt: str
    prompt_sha256: str
    context_sha256: str


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write a JSON result atomically without allowing NaN values."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                payload,
                handle,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        os.chmod(path, 0o600)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        temporary_path.unlink(missing_ok=True)


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Write a private source snapshot atomically."""

    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        os.chmod(path, 0o600)
    finally:
        temporary_path.unlink(missing_ok=True)


def validate_source_manifest(payload: dict[str, Any]) -> list[FrozenArticle]:
    """Validate a self-committed frozen JATS source manifest."""

    stored_digest = payload.get("manifest_sha256")
    core = {key: value for key, value in payload.items() if key != "manifest_sha256"}
    if not isinstance(stored_digest, str) or stored_digest != canonical_sha256(core):
        raise ValueError("source manifest commitment is invalid")
    rows = payload.get("articles")
    if not isinstance(rows, list) or not rows:
        raise ValueError("source manifest must contain at least one article")
    articles = [FrozenArticle.model_validate(row) for row in rows]
    identifiers = [article.document_id for article in articles]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("source manifest contains duplicate document identifiers")
    return articles


def select_articles(
    articles: list[FrozenArticle],
    *,
    limit: int | None = None,
    document_ids: Iterable[str] = (),
) -> list[FrozenArticle]:
    """Select a deterministic ordered subset without consulting model output."""

    requested = [item.upper() for item in document_ids]
    if requested and limit is not None:
        raise ValueError("article limit and explicit document identifiers are mutually exclusive")
    if requested:
        if len(requested) != len(set(requested)):
            raise ValueError("requested document identifiers contain duplicates")
        by_id = {article.document_id: article for article in articles}
        missing = [item for item in requested if item not in by_id]
        if missing:
            raise ValueError(f"requested document identifiers are absent: {missing}")
        selected = [by_id[item] for item in requested]
    else:
        selected = list(articles)
    if limit is not None:
        if limit < 1:
            raise ValueError("article limit must be positive")
        if limit > len(selected):
            raise ValueError(
                f"article limit requests {limit} rows but only {len(selected)} are available"
            )
        selected = selected[:limit]
    if not selected:
        raise ValueError("article selection is empty")
    return selected


def _retry_after(response: httpx.Response | None, fallback: float) -> float:
    if response is None:
        return fallback
    raw = response.headers.get("Retry-After")
    if raw is None:
        return fallback
    try:
        return min(max(float(raw), 0.0), 30.0)
    except ValueError:
        return fallback


def fetch_frozen_jats(
    article: FrozenArticle,
    *,
    cache_dir: Path,
    client: httpx.Client,
    retries: int = 5,
    allow_network: bool = True,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[bytes, bool]:
    """Read or fetch one JATS snapshot and require its frozen SHA-256."""

    if _DOCUMENT_ID.fullmatch(article.document_id) is None:
        raise ValueError("unsafe document identifier")
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(cache_dir, 0o700)
    path = cache_dir / f"{article.document_id}.xml"
    if path.is_file():
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != article.full_text_sha256:
            raise ValueError(f"cached JATS SHA-256 mismatch for {article.document_id}")
        return payload, True
    if not allow_network:
        raise FileNotFoundError(f"required frozen JATS cache entry is missing: {path.name}")

    last_error: Exception | None = None
    endpoint = FULLTEXT_URL.format(document_id=article.document_id)
    for attempt in range(retries + 1):
        response: httpx.Response | None = None
        try:
            response = client.get(endpoint)
            if response.status_code not in RETRYABLE_STATUS_CODES:
                response.raise_for_status()
                payload = response.content
                if hashlib.sha256(payload).hexdigest() != article.full_text_sha256:
                    raise ValueError(
                        f"downloaded JATS SHA-256 mismatch for {article.document_id}"
                    )
                atomic_write_bytes(path, payload)
                return payload, False
            last_error = httpx.HTTPStatusError(
                f"retryable Europe PMC status {response.status_code}",
                request=response.request,
                response=response,
            )
        except httpx.TransportError as error:
            last_error = error
        except httpx.HTTPStatusError:
            raise
        if attempt == retries:
            break
        sleep(_retry_after(response, min(2.0**attempt, 20.0)))
    raise RuntimeError(
        f"Europe PMC JATS request failed after {retries + 1} attempts for "
        f"{article.document_id}"
    ) from last_error


def build_tasks(
    article: FrozenArticle,
    xml_bytes: bytes,
    extractor: SchemaConstrainedEventExtractor,
) -> list[InferenceTask]:
    """Create one independently verifiable model task per protocol paragraph."""

    paragraphs = protocol_paragraphs(parse_jats_paragraphs(article.document_id, xml_bytes))
    tasks: list[InferenceTask] = []
    seen: set[str] = set()
    for paragraph in paragraphs:
        context_sha256 = hashlib.sha256(paragraph.text.encode("utf-8")).hexdigest()
        stable_payload = "|".join(
            (
                article.document_id,
                article.split,
                paragraph.section,
                paragraph.paragraph_id,
                context_sha256,
            )
        )
        task_id = hashlib.sha256(stable_payload.encode("utf-8")).hexdigest()
        if task_id in seen:
            continue
        seen.add(task_id)
        prompt = extractor.build_prompt([paragraph])
        tasks.append(
            InferenceTask(
                task_id=task_id,
                split=article.split,
                paragraph=paragraph,
                prompt=prompt,
                prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                context_sha256=context_sha256,
            )
        )
    return tasks


def _event_counts(events: Iterable[ProtocolEvent]) -> tuple[Counter[str], Counter[str]]:
    phases: Counter[str] = Counter()
    attributes: Counter[str] = Counter()
    for event in events:
        phases[event.event_type.value] += 1
        for name in (
            "duration_ps",
            "temperature_k",
            "pressure_bar",
            "timestep_fs",
            "ensemble",
            "restraints",
            "replicates",
        ):
            if getattr(event, name) is not None:
                attributes[name] += 1
    return phases, attributes


def _metadata_at(backend: Any, index: int) -> dict[str, Any]:
    rows = getattr(backend, "last_batch_metadata", [])
    if not isinstance(rows, list) or index >= len(rows) or not isinstance(rows[index], dict):
        return {}
    return rows[index]


def serialize_evidence_audit(
    audit: EvidenceValidationAudit,
    response: dict[str, Any],
) -> dict[str, Any]:
    """Bind source-free rejection/repair rows to immutable raw model candidates."""

    candidates = response.get("events")
    if not isinstance(candidates, list) or len(candidates) != audit.candidate_count:
        raise ValueError("evidence audit candidate count differs from the structured response")

    def bind(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        bound: list[dict[str, Any]] = []
        for row in rows:
            candidate_index = row.get("candidate_index")
            if not isinstance(candidate_index, int) or not 0 <= candidate_index < len(candidates):
                raise ValueError("evidence audit contains an invalid candidate index")
            bound.append(
                {
                    **row,
                    "candidate_sha256": canonical_sha256(candidates[candidate_index]),
                }
            )
        return bound

    candidate_rejections = bind(audit.candidate_rejections)
    attribute_rejections = bind(audit.attribute_rejections)
    repairs = bind(audit.repairs)
    return {
        "candidate_count": audit.candidate_count,
        "candidate_rejection_count": len(candidate_rejections),
        "candidate_rejections": candidate_rejections,
        "attribute_rejection_count": len(attribute_rejections),
        "attribute_rejections": attribute_rejections,
        "repair_count": len(repairs),
        "repairs": repairs,
    }


def classify_evidence_audit(audit: EvidenceValidationAudit) -> str:
    """Return a task classification without hiding accepted-but-filtered candidates."""

    if audit.events:
        if audit.candidate_rejections or audit.attribute_rejections:
            return "accepted_with_evidence_rejections"
        return "accepted"
    if audit.candidate_count:
        return "evidence_rejected"
    return "accepted"


def run_model_batch(
    *,
    backend: Any,
    extractor: SchemaConstrainedEventExtractor,
    articles: list[FrozenArticle],
    xml_by_document: dict[str, bytes],
    response_schema: dict[str, Any],
    batch_size: int,
    determinism_check: bool,
    checkpoint: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Generate and classify every paragraph response without silent dropping."""

    if batch_size < 1:
        raise ValueError("batch size must be positive")
    tasks = [
        task
        for article in articles
        for task in build_tasks(article, xml_by_document[article.document_id], extractor)
    ]
    response_schema_sha256 = canonical_sha256(response_schema)
    deterministic: dict[str, Any] = {
        "requested": determinism_check,
        "performed": False,
        "identical": None,
    }
    if determinism_check and tasks:
        duplicate = backend.complete_many(
            [tasks[0].prompt, tasks[0].prompt],
            response_schema,
        )
        if len(duplicate) != 2:
            raise RuntimeError("determinism check returned an unexpected response count")
        deterministic.update(
            {
                "performed": True,
                "task_id": tasks[0].task_id,
                "identical": canonical_sha256(duplicate[0]) == canonical_sha256(duplicate[1]),
                "response_sha256": [canonical_sha256(item) for item in duplicate],
            }
        )

    task_results: list[dict[str, Any]] = []
    started = time.perf_counter()
    for offset in range(0, len(tasks), batch_size):
        batch = tasks[offset : offset + batch_size]
        responses = backend.complete_many(
            [task.prompt for task in batch],
            response_schema,
        )
        if len(responses) != len(batch):
            raise RuntimeError("model backend returned an unexpected response count")
        for index, (task, response) in enumerate(zip(batch, responses, strict=True)):
            record: dict[str, Any] = {
                "task_id": task.task_id,
                "document_id": task.paragraph.document_id,
                "split": task.split,
                "section": task.paragraph.section,
                "paragraph_id": task.paragraph.paragraph_id,
                "context_sha256": task.context_sha256,
                "prompt_sha256": task.prompt_sha256,
                "response_sha256": canonical_sha256(response),
                "response": response,
                "usage": _metadata_at(backend, index),
            }
            try:
                LLMEventResponse.model_validate(response)
            except ValidationError as error:
                record.update(
                    {
                        "classification": "schema_rejected",
                        "event_count": 0,
                        "events": [],
                        "rejection": {
                            "type": type(error).__name__,
                            "message": str(error),
                        },
                    }
                )
            else:
                audit = extractor.validate_response_with_audit([task.paragraph], response)
                record.update(serialize_evidence_audit(audit, response))
                record.update(
                    {
                        "classification": classify_evidence_audit(audit),
                        "event_count": len(audit.events),
                        "events": [
                            event.model_dump(mode="json") for event in audit.events
                        ],
                    }
                )
            task_results.append(record)
        if checkpoint is not None:
            checkpoint(
                {
                    "schema_version": SCHEMA_VERSION,
                    "response_schema_version": RESPONSE_SCHEMA_VERSION,
                    "response_schema_sha256": response_schema_sha256,
                    "status": "running",
                    "task_count_total": len(tasks),
                    "task_count_classified": len(task_results),
                    "tasks": task_results,
                }
            )
    elapsed = time.perf_counter() - started

    classifications = Counter(item["classification"] for item in task_results)
    candidate_rejection_reasons = Counter(
        row["reason_code"]
        for item in task_results
        for row in item.get("candidate_rejections", [])
    )
    attribute_rejection_reasons = Counter(
        row["reason_code"]
        for item in task_results
        for row in item.get("attribute_rejections", [])
    )
    repair_reasons = Counter(
        row["reason_code"]
        for item in task_results
        for row in item.get("repairs", [])
    )
    events = [
        ProtocolEvent.model_validate(event)
        for item in task_results
        for event in item["events"]
    ]
    phase_counts, attribute_counts = _event_counts(events)
    per_article: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in task_results:
        grouped[item["document_id"]].append(item)
    for article in articles:
        rows = grouped.get(article.document_id, [])
        accepted_classifications = {"accepted", "accepted_with_evidence_rejections"}
        per_article[article.document_id] = {
            "split": article.split,
            "paragraph_count": len(rows),
            "accepted_paragraph_count": sum(
                item["classification"] in accepted_classifications for item in rows
            ),
            "rejected_paragraph_count": sum(
                item["classification"] not in accepted_classifications for item in rows
            ),
            "accepted_with_evidence_rejections_count": sum(
                item["classification"] == "accepted_with_evidence_rejections"
                for item in rows
            ),
            "event_count": sum(item["event_count"] for item in rows),
            "event_bearing_paragraph_count": sum(item["event_count"] > 0 for item in rows),
        }
    prompt_tokens = sum(
        int(item["usage"].get("prompt_tokens", 0) or 0) for item in task_results
    )
    completion_tokens = sum(
        int(item["usage"].get("completion_tokens", 0) or 0) for item in task_results
    )
    return {
        "response_schema_version": RESPONSE_SCHEMA_VERSION,
        "response_schema_sha256": response_schema_sha256,
        "task_count": len(tasks),
        "task_count_classified": len(task_results),
        "classification_counts": dict(sorted(classifications.items())),
        "candidate_rejection_reason_counts": dict(
            sorted(candidate_rejection_reasons.items())
        ),
        "attribute_rejection_reason_counts": dict(
            sorted(attribute_rejection_reasons.items())
        ),
        "repair_reason_counts": dict(sorted(repair_reasons.items())),
        "event_count": len(events),
        "phase_counts": dict(sorted(phase_counts.items())),
        "attribute_counts": dict(sorted(attribute_counts.items())),
        "per_article": per_article,
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "generation_seconds": elapsed,
            "tokens_per_second": (
                (prompt_tokens + completion_tokens) / elapsed if elapsed > 0 else None
            ),
        },
        "determinism_check": deterministic,
        "tasks": task_results,
    }


def compact_summary(result: dict[str, Any]) -> dict[str, Any]:
    """Remove source excerpts and raw predictions from a shareable run summary."""

    batch = result.get("batch", {})
    return {
        "schema_version": result.get("schema_version"),
        "status": result.get("status"),
        "started_at": result.get("started_at"),
        "completed_at": result.get("completed_at"),
        "source": result.get("source"),
        "slurm": result.get("slurm"),
        "runtime": result.get("runtime"),
        "model": result.get("model"),
        "corpus": result.get("corpus"),
        "configuration": result.get("configuration"),
        "accuracy_evaluated": False,
        "human_reference_used": False,
        "interpretation": (
            "model integration, schema/evidence validation and throughput evidence only"
        ),
        "jats": result.get("jats"),
        "batch": {
            key: batch.get(key)
            for key in (
                "task_count",
                "task_count_classified",
                "classification_counts",
                "candidate_rejection_reason_counts",
                "attribute_rejection_reason_counts",
                "repair_reason_counts",
                "event_count",
                "phase_counts",
                "attribute_counts",
                "per_article",
                "usage",
                "determinism_check",
                "response_schema_version",
                "response_schema_sha256",
            )
        },
        "result_sha256": result.get("result_sha256"),
    }


def validate_sha256(value: str, *, field: str) -> None:
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field} must be a lowercase SHA-256")
