from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any

from pydantic import BaseModel, ConfigDict

from .benchmark import CandidateArticle, canonical_sha256


class ScreeningPool(BaseModel):
    model_config = ConfigDict(extra="forbid")

    study_id: str
    study_status: str
    seed: int
    pool_size: int
    selection_method: str
    eligibility_rules: dict[str, Any]
    screening_pool: list[CandidateArticle]
    exclusions: list[dict[str, str]]
    candidate_manifest_sha256: str
    pool_sha256: str


def _rank(seed: int, document_id: str) -> str:
    return hashlib.sha256(f"{seed}|{document_id}".encode("utf-8")).hexdigest()


def create_screening_pool(
    candidates: list[CandidateArticle],
    *,
    excluded_document_ids: set[str] | None = None,
    seed: int = 3997,
    pool_size: int = 120,
    publication_year_min: int | None = None,
    publication_year_max: int | None = None,
    require_known_year: bool = False,
    study_status: str = "provisional_temporal_isolation",
) -> ScreeningPool:
    if pool_size < 60:
        raise ValueError("screening pool must contain at least 60 articles")
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
            reason = "previous_study_article"
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

    if len(eligible) < pool_size:
        raise ValueError(f"need at least {pool_size} eligible pool candidates; found {len(eligible)}")

    strata: dict[str, list[CandidateArticle]] = defaultdict(list)
    for candidate in eligible:
        strata[candidate.software_family.strip().lower() or "unknown"].append(candidate)
    for articles in strata.values():
        articles.sort(key=lambda article: _rank(seed, article.document_id))

    ordered: list[CandidateArticle] = []
    active = sorted(strata)
    while active and len(ordered) < pool_size:
        remaining: list[str] = []
        for stratum in active:
            if strata[stratum] and len(ordered) < pool_size:
                ordered.append(strata[stratum].pop(0))
            if strata[stratum]:
                remaining.append(stratum)
        active = remaining

    candidate_manifest = [article.model_dump(mode="json") for article in candidates]
    manifest_sha = canonical_sha256(candidate_manifest)
    eligibility_rules = {
        "publication_year_min": publication_year_min,
        "publication_year_max": publication_year_max,
        "require_known_year": require_known_year,
        "excluded_document_id_count": len(excluded_document_ids),
        "human_eligibility_required_before_split": True,
    }
    core = {
        "study_id": "mdmeta-provisional-temporal-eligibility-pool-v1",
        "study_status": study_status,
        "seed": seed,
        "pool_size": pool_size,
        "selection_method": "round_robin_software_strata_then_sha256_rank",
        "eligibility_rules": eligibility_rules,
        "screening_pool": [article.document_id for article in ordered],
        "exclusions": exclusions,
        "candidate_manifest_sha256": manifest_sha,
    }
    return ScreeningPool(
        study_id=core["study_id"],
        study_status=study_status,
        seed=seed,
        pool_size=pool_size,
        selection_method=core["selection_method"],
        eligibility_rules=eligibility_rules,
        screening_pool=ordered,
        exclusions=exclusions,
        candidate_manifest_sha256=manifest_sha,
        pool_sha256=canonical_sha256(core),
    )
