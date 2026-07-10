from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict


class CandidateArticle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    title: str
    doi: str | None = None
    year: int | None = None
    software_family: str = "unknown"
    licence: str | None = None
    full_text_available: bool = True
    source_uri: str
    source_sha256: str | None = None


class BenchmarkPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    study_id: str
    seed: int
    target_size: int
    development: list[CandidateArticle]
    validation: list[CandidateArticle]
    locked_test: list[CandidateArticle]
    exclusions: list[dict[str, str]]
    plan_sha256: str


def _stable_digest(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def create_benchmark_plan(
    candidates: list[CandidateArticle],
    *,
    seed: int = 3997,
    target_size: int = 60,
    development_size: int = 30,
    validation_size: int = 10,
    locked_test_size: int = 20,
    excluded_document_ids: set[str] | None = None,
) -> BenchmarkPlan:
    if development_size + validation_size + locked_test_size != target_size:
        raise ValueError("split sizes must sum to target_size")
    excluded_document_ids = excluded_document_ids or set()
    exclusions: list[dict[str, str]] = []
    eligible: list[CandidateArticle] = []
    seen: set[str] = set()
    for candidate in candidates:
        reason = None
        if candidate.document_id in seen:
            reason = "duplicate_document_id"
        elif candidate.document_id in excluded_document_ids:
            reason = "previously_used_development_article"
        elif not candidate.full_text_available:
            reason = "full_text_unavailable"
        if reason:
            exclusions.append({"document_id": candidate.document_id, "reason": reason})
        else:
            eligible.append(candidate)
            seen.add(candidate.document_id)
    if len(eligible) < target_size:
        raise ValueError(f"need at least {target_size} eligible articles; found {len(eligible)}")

    rng = random.Random(seed)
    strata: dict[str, list[CandidateArticle]] = defaultdict(list)
    for candidate in eligible:
        strata[candidate.software_family.lower()].append(candidate)
    for group in strata.values():
        group.sort(key=lambda item: _stable_digest({"seed": seed, "id": item.document_id}))
        rng.shuffle(group)

    selected: list[CandidateArticle] = []
    keys = sorted(strata)
    while len(selected) < target_size and keys:
        next_keys = []
        for key in keys:
            if strata[key] and len(selected) < target_size:
                selected.append(strata[key].pop())
            if strata[key]:
                next_keys.append(key)
        keys = next_keys

    rng.shuffle(selected)
    development = selected[:development_size]
    validation = selected[development_size : development_size + validation_size]
    locked_test = selected[development_size + validation_size :]
    plan_payload = {
        "study_id": "mdlit-confirmatory-60-v1",
        "seed": seed,
        "development": [item.document_id for item in development],
        "validation": [item.document_id for item in validation],
        "locked_test": [item.document_id for item in locked_test],
        "exclusions": exclusions,
    }
    return BenchmarkPlan(
        study_id="mdlit-confirmatory-60-v1",
        seed=seed,
        target_size=target_size,
        development=development,
        validation=validation,
        locked_test=locked_test,
        exclusions=exclusions,
        plan_sha256=_stable_digest(plan_payload),
    )


def load_candidates(path: str | Path) -> list[CandidateArticle]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload["articles"] if isinstance(payload, dict) else payload
    return [CandidateArticle.model_validate(row) for row in rows]
