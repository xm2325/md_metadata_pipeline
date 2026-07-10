from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .benchmark import CandidateArticle, canonical_sha256

EligibilityDecision = Literal["eligible", "ineligible", "uncertain"]


class EligibilityReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1)
    reviewer_id: str = Field(min_length=1)
    decision: EligibilityDecision
    reason: str = Field(min_length=1)
    full_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    note: str | None = None


class AdjudicatedEligibility(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1)
    decision: Literal["eligible", "ineligible"]
    reason: str = Field(min_length=1)
    full_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    adjudicator_id: str = Field(min_length=1)
    note: str | None = None


def _load_rows(path: str | Path, key: str) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    rows = payload.get(key)
    if not isinstance(rows, list):
        raise ValueError(f"expected a list or a '{key}' list")
    return rows


def load_eligibility_reviews(path: str | Path) -> list[EligibilityReview]:
    return [EligibilityReview.model_validate(row) for row in _load_rows(path, "reviews")]


def load_adjudicated_eligibility(path: str | Path) -> list[AdjudicatedEligibility]:
    return [
        AdjudicatedEligibility.model_validate(row)
        for row in _load_rows(path, "decisions")
    ]


def compare_eligibility_reviews(
    reviews_a: list[EligibilityReview], reviews_b: list[EligibilityReview]
) -> dict[str, Any]:
    by_a = {review.document_id: review for review in reviews_a}
    by_b = {review.document_id: review for review in reviews_b}
    all_ids = sorted(set(by_a) | set(by_b))
    agreements: list[dict[str, Any]] = []
    disagreements: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    confusion: Counter[tuple[str, str]] = Counter()
    hash_conflicts: list[dict[str, str]] = []

    for document_id in all_ids:
        left = by_a.get(document_id)
        right = by_b.get(document_id)
        if left is None or right is None:
            missing.append(
                {
                    "document_id": document_id,
                    "missing_from": "annotator_a" if left is None else "annotator_b",
                }
            )
            continue
        if left.full_text_sha256 != right.full_text_sha256:
            hash_conflicts.append(
                {
                    "document_id": document_id,
                    "annotator_a_sha256": left.full_text_sha256,
                    "annotator_b_sha256": right.full_text_sha256,
                }
            )
        confusion[(left.decision, right.decision)] += 1
        row = {
            "document_id": document_id,
            "annotator_a": left.model_dump(mode="json"),
            "annotator_b": right.model_dump(mode="json"),
        }
        (agreements if left.decision == right.decision else disagreements).append(row)

    comparable = len(agreements) + len(disagreements)
    return {
        "comparison_scope": "independent_human_eligibility_reviews",
        "annotator_a_count": len(reviews_a),
        "annotator_b_count": len(reviews_b),
        "duplicate_document_ids_a": len(reviews_a) - len(by_a),
        "duplicate_document_ids_b": len(reviews_b) - len(by_b),
        "comparable_count": comparable,
        "agreement_count": len(agreements),
        "disagreement_count": len(disagreements),
        "decision_agreement": len(agreements) / comparable if comparable else 0.0,
        "missing_reviews": missing,
        "full_text_hash_conflicts": hash_conflicts,
        "decision_confusion": {
            decision_a: {
                decision_b: count
                for (left, decision_b), count in sorted(confusion.items())
                if left == decision_a
            }
            for decision_a in sorted({left for left, _ in confusion})
        },
        "agreements": agreements,
        "disagreements": disagreements,
    }


def create_blind_review_template(
    pool: dict[str, Any], screen: dict[str, Any], *, review_seed: int = 7041
) -> dict[str, Any]:
    if screen.get("pool_sha256") != pool.get("pool_sha256"):
        raise ValueError("screen result does not match screening pool")
    screen_records = {row["document_id"]: row for row in screen.get("records", [])}
    blinded: list[dict[str, Any]] = []
    for article in pool["screening_pool"]:
        record = screen_records.get(article["document_id"])
        if record is None:
            raise ValueError(f"missing screen record for {article['document_id']}")
        blinded.append(
            {
                "document_id": article["document_id"],
                "title": record.get("title") or article["title"],
                "year": article.get("year"),
                "source_uri": article["source_uri"],
                "article_type": record.get("article_type"),
                "full_text_sha256": record["full_text_sha256"],
                "method_section_titles": record.get("method_section_titles", []),
                "decision": "pending",
                "reason": None,
                "reviewer_id": None,
                "note": None,
            }
        )
    blinded.sort(
        key=lambda row: canonical_sha256(
            {"review_seed": review_seed, "document_id": row["document_id"]}
        )
    )
    for index, row in enumerate(blinded, start=1):
        row["review_index"] = index
    core = {
        "study_id": pool["study_id"],
        "study_status": pool["study_status"],
        "pool_sha256": pool["pool_sha256"],
        "screen_sha256": canonical_sha256(screen),
        "review_seed": review_seed,
        "blinding": (
            "split labels, pool positions, machine-screen status, engine mentions, "
            "and protocol-term counts omitted"
        ),
        "articles": blinded,
    }
    return {**core, "template_sha256": canonical_sha256(core)}


def create_adjudication_template(comparison: dict[str, Any]) -> dict[str, Any]:
    items = []
    for row in comparison["disagreements"]:
        items.append(
            {
                "document_id": row["document_id"],
                "annotator_a": row["annotator_a"],
                "annotator_b": row["annotator_b"],
                "decision": "pending",
                "reason": None,
                "full_text_sha256": row["annotator_a"]["full_text_sha256"],
                "adjudicator_id": None,
                "note": None,
            }
        )
    for row in comparison["full_text_hash_conflicts"]:
        items.append(
            {
                "document_id": row["document_id"],
                "annotator_a_sha256": row["annotator_a_sha256"],
                "annotator_b_sha256": row["annotator_b_sha256"],
                "decision": "blocked_hash_conflict",
                "reason": None,
                "full_text_sha256": None,
                "adjudicator_id": None,
                "note": None,
            }
        )
    return {
        "status": "not_adjudicated",
        "allowed_decisions": ["eligible", "ineligible"],
        "items": items,
    }


def lock_after_eligibility(
    pool: dict[str, Any],
    adjudicated: list[AdjudicatedEligibility],
    *,
    development_size: int = 30,
    validation_size: int = 10,
    locked_test_size: int = 20,
    split_seed: int = 9041,
) -> dict[str, Any]:
    target = development_size + validation_size + locked_test_size
    decisions = {row.document_id: row for row in adjudicated}
    if len(decisions) != len(adjudicated):
        raise ValueError("adjudication contains duplicate document IDs")

    selected: list[CandidateArticle] = []
    reviewed_prefix: list[str] = []
    for article_row in pool["screening_pool"]:
        document_id = article_row["document_id"]
        decision = decisions.get(document_id)
        if decision is None:
            if len(selected) < target:
                raise ValueError(
                    f"missing adjudicated eligibility before target reached: {document_id}"
                )
            break
        reviewed_prefix.append(document_id)
        if decision.decision == "eligible":
            selected.append(CandidateArticle.model_validate(article_row))
            if len(selected) == target:
                break
    if len(selected) < target:
        raise ValueError(f"need {target} adjudicated eligible articles; found {len(selected)}")

    split_order = sorted(
        selected,
        key=lambda article: canonical_sha256(
            {"split_seed": split_seed, "document_id": article.document_id}
        ),
    )
    assignment_cycle = ["development"] * 3 + ["locked_test"] * 2 + ["validation"]
    splits: dict[str, list[CandidateArticle]] = {
        "development": [],
        "validation": [],
        "locked_test": [],
    }
    for index, article in enumerate(split_order):
        splits[assignment_cycle[index % len(assignment_cycle)]].append(article)
    if (
        len(splits["development"]) != development_size
        or len(splits["validation"]) != validation_size
        or len(splits["locked_test"]) != locked_test_size
    ):
        raise AssertionError("split assignment did not reach requested capacities")

    adjudication_payload = [
        decisions[document_id].model_dump(mode="json") for document_id in reviewed_prefix
    ]
    core = {
        "study_id": f"{pool['study_id']}-human-eligible-v1",
        "study_status": "human_eligibility_adjudicated_split_locked",
        "source_pool_sha256": pool["pool_sha256"],
        "adjudication_sha256": canonical_sha256(adjudication_payload),
        "split_seed": split_seed,
        "selection_method": "first_60_eligible_in_pool_order_then_hash_split_3_2_1",
        "reviewed_prefix_count": len(reviewed_prefix),
        "development": [row.document_id for row in splits["development"]],
        "validation": [row.document_id for row in splits["validation"]],
        "locked_test": [row.document_id for row in splits["locked_test"]],
    }
    return {
        **core,
        "development": [row.model_dump(mode="json") for row in splits["development"]],
        "validation": [row.model_dump(mode="json") for row in splits["validation"]],
        "locked_test": [row.model_dump(mode="json") for row in splits["locked_test"]],
        "plan_sha256": canonical_sha256(core),
    }
