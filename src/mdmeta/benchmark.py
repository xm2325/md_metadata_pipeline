from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CandidateArticle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source_uri: str = Field(min_length=1)
    doi: str | None = None
    year: int | None = None
    software_family: str = "unknown"
    licence: str | None = None
    full_text_available: bool = True
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class BenchmarkPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    study_id: str
    study_status: str
    seed: int
    selection_method: str
    eligibility_rules: dict[str, Any]
    development: list[CandidateArticle]
    validation: list[CandidateArticle]
    locked_test: list[CandidateArticle]
    exclusions: list[dict[str, str]]
    candidate_manifest_sha256: str
    plan_sha256: str


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _rank(seed: int, document_id: str) -> str:
    return hashlib.sha256(f"{seed}|{document_id}".encode("utf-8")).hexdigest()


def create_benchmark_plan(
    candidates: list[CandidateArticle],
    *,
    excluded_document_ids: set[str] | None = None,
    seed: int = 3997,
    development_size: int = 30,
    validation_size: int = 10,
    locked_test_size: int = 20,
    publication_year_min: int | None = None,
    publication_year_max: int | None = None,
    require_known_year: bool = False,
    study_status: str = "locked_confirmatory",
) -> BenchmarkPlan:
    target_size = development_size + validation_size + locked_test_size
    excluded_document_ids = {item.upper() for item in (excluded_document_ids or set())}
    exclusions: list[dict[str, str]] = []
    eligible: list[CandidateArticle] = []
    seen: set[str] = set()

    for candidate in candidates:
        identifier = candidate.document_id.upper()
        reason: str | None = None
        if identifier in seen:
            reason = "duplicate_document_id"
        elif identifier in excluded_document_ids:
            reason = "previous_development_article"
        elif not candidate.full_text_available:
            reason = "full_text_unavailable"
        elif not identifier.startswith("PMC"):
            reason = "missing_pmc_identifier"
        elif require_known_year and candidate.year is None:
            reason = "missing_publication_year"
        elif (
            publication_year_min is not None
            and candidate.year is not None
            and candidate.year < publication_year_min
        ):
            reason = "publication_year_below_window"
        elif (
            publication_year_max is not None
            and candidate.year is not None
            and candidate.year > publication_year_max
        ):
            reason = "publication_year_above_window"
        if reason is not None:
            exclusions.append({"document_id": candidate.document_id, "reason": reason})
            continue
        seen.add(identifier)
        eligible.append(candidate.model_copy(update={"document_id": identifier}))

    if len(eligible) < target_size:
        raise ValueError(f"need at least {target_size} eligible articles; found {len(eligible)}")

    strata: dict[str, list[CandidateArticle]] = defaultdict(list)
    for candidate in eligible:
        stratum = candidate.software_family.strip().lower() or "unknown"
        strata[stratum].append(candidate)
    for articles in strata.values():
        articles.sort(key=lambda article: _rank(seed, article.document_id))

    selected: list[CandidateArticle] = []
    active = sorted(strata)
    while active and len(selected) < target_size:
        remaining: list[str] = []
        for stratum in active:
            if strata[stratum] and len(selected) < target_size:
                selected.append(strata[stratum].pop(0))
            if strata[stratum]:
                remaining.append(stratum)
        active = remaining

    selected.sort(key=lambda article: _rank(seed + 1, article.document_id))
    development = selected[:development_size]
    validation = selected[development_size : development_size + validation_size]
    locked_test = selected[development_size + validation_size : target_size]

    candidate_manifest = [article.model_dump(mode="json") for article in candidates]
    manifest_sha = canonical_sha256(candidate_manifest)
    eligibility_rules = {
        "publication_year_min": publication_year_min,
        "publication_year_max": publication_year_max,
        "require_known_year": require_known_year,
        "excluded_document_id_count": len(excluded_document_ids),
    }
    study_id = (
        "mdmeta-confirmatory-60-v1"
        if study_status == "locked_confirmatory"
        else "mdmeta-provisional-temporal-60-v1"
    )
    plan_core = {
        "study_id": study_id,
        "study_status": study_status,
        "seed": seed,
        "eligibility_rules": eligibility_rules,
        "development": [article.document_id for article in development],
        "validation": [article.document_id for article in validation],
        "locked_test": [article.document_id for article in locked_test],
        "exclusions": exclusions,
        "candidate_manifest_sha256": manifest_sha,
    }
    return BenchmarkPlan(
        study_id=study_id,
        study_status=study_status,
        seed=seed,
        selection_method="round_robin_software_strata_then_sha256_rank",
        eligibility_rules=eligibility_rules,
        development=development,
        validation=validation,
        locked_test=locked_test,
        exclusions=exclusions,
        candidate_manifest_sha256=manifest_sha,
        plan_sha256=canonical_sha256(plan_core),
    )


def load_candidate_manifest(path: str | Path) -> list[CandidateArticle]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload["articles"] if isinstance(payload, dict) else payload
    return [CandidateArticle.model_validate(row) for row in rows]
