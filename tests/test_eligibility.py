import pytest

from mdmeta.benchmark import CandidateArticle
from mdmeta.eligibility import (
    AdjudicatedEligibility,
    EligibilityReview,
    compare_eligibility_reviews,
    create_blind_review_template,
    lock_after_eligibility,
)
from mdmeta.screening_pool import create_screening_pool


def _candidates(n=150):
    families = ["gromacs", "amber", "namd", "openmm", "unknown"]
    return [
        CandidateArticle(
            document_id=f"PMC{i:06d}",
            title=f"Article {i}",
            source_uri=f"https://example.org/{i}",
            year=2018,
            software_family=families[i % len(families)],
        )
        for i in range(n)
    ]


def _screen(pool):
    records = []
    for position, article in enumerate(pool.screening_pool, start=1):
        records.append(
            {
                "document_id": article.document_id,
                "split": "unassigned",
                "pool_position": position,
                "title": article.title,
                "article_type": "research-article",
                "full_text_sha256": f"{position:064x}"[-64:],
                "method_section_titles": ["Methods"],
                "machine_screen_status": "strong_biomolecular_protocol_signal",
                "machine_eligible_for_annotation": True,
                "engine_mentions": ["gromacs"],
                "protocol_term_hits": {"duration": 1},
            }
        )
    return {
        "study_id": pool.study_id,
        "study_status": pool.study_status,
        "pool_sha256": pool.pool_sha256,
        "records": records,
    }


def test_screening_pool_is_deterministic_and_has_reserves():
    first = create_screening_pool(_candidates(), pool_size=120)
    second = create_screening_pool(_candidates(), pool_size=120)
    assert first == second
    assert len(first.screening_pool) == 120
    assert len({row.document_id for row in first.screening_pool}) == 120
    assert first.eligibility_rules["human_eligibility_required_before_split"] is True


def test_blind_template_omits_split_machine_status_and_pool_position():
    pool = create_screening_pool(_candidates(), pool_size=120)
    template = create_blind_review_template(
        pool.model_dump(mode="json"), _screen(pool), review_seed=7
    )
    row = template["articles"][0]
    assert len(template["articles"]) == 120
    assert "split" not in row
    assert "pool_position" not in row
    assert "machine_screen_status" not in row
    assert "engine_mentions" not in row
    assert row["decision"] == "pending"


def test_review_comparison_reports_hash_conflict_and_decision_disagreement():
    left = EligibilityReview(
        document_id="PMC1",
        reviewer_id="a",
        decision="eligible",
        reason="reports biomolecular MD",
        full_text_sha256="a" * 64,
    )
    right = EligibilityReview(
        document_id="PMC1",
        reviewer_id="b",
        decision="ineligible",
        reason="review article",
        full_text_sha256="b" * 64,
    )
    result = compare_eligibility_reviews([left], [right])
    assert result["decision_agreement"] == 0
    assert result["disagreement_count"] == 1
    assert len(result["full_text_hash_conflicts"]) == 1


def test_lock_requires_complete_review_prefix_before_sixtieth_eligible():
    pool = create_screening_pool(_candidates(), pool_size=120)
    decisions = [
        AdjudicatedEligibility(
            document_id=article.document_id,
            decision="eligible",
            reason="reports biomolecular MD",
            full_text_sha256=f"{index:064x}"[-64:],
            adjudicator_id="adj",
        )
        for index, article in enumerate(pool.screening_pool[:59], start=1)
    ]
    with pytest.raises(ValueError, match="missing adjudicated eligibility"):
        lock_after_eligibility(pool.model_dump(mode="json"), decisions)


def test_lock_selects_first_sixty_eligible_then_assigns_exact_splits():
    pool = create_screening_pool(_candidates(), pool_size=120)
    decisions = []
    eligible_count = 0
    reviewed = 0
    for index, article in enumerate(pool.screening_pool, start=1):
        decision = "ineligible" if index % 5 == 0 else "eligible"
        if decision == "eligible":
            eligible_count += 1
        reviewed += 1
        decisions.append(
            AdjudicatedEligibility(
                document_id=article.document_id,
                decision=decision,
                reason="reports biomolecular MD" if decision == "eligible" else "not target MD",
                full_text_sha256=f"{index:064x}"[-64:],
                adjudicator_id="adj",
            )
        )
        if eligible_count == 60:
            break
    plan = lock_after_eligibility(pool.model_dump(mode="json"), decisions, split_seed=11)
    assert plan["reviewed_prefix_count"] == reviewed
    assert len(plan["development"]) == 30
    assert len(plan["validation"]) == 10
    assert len(plan["locked_test"]) == 20
    ids = {
        row["document_id"]
        for split in ("development", "validation", "locked_test")
        for row in plan[split]
    }
    assert len(ids) == 60
    assert plan["study_status"] == "human_eligibility_adjudicated_split_locked"
