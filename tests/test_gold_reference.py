from copy import deepcopy

import pytest

from mdmeta.benchmark import canonical_sha256
from mdmeta.gold_reference import (
    freeze_gold_reference,
    prepare_gold_adjudication,
    seal_annotation_submission,
)
from scripts.audit_independent_plan import audit_independent_plan
from scripts.finalize_screened_plan import finalize_screened_plan


def _article(index: int) -> dict:
    return {
        "document_id": f"PMC{index:06d}",
        "title": f"Article {index}",
        "source_uri": f"https://example.test/PMC{index:06d}",
        "software_family": ("gromacs", "amber", "namd", "unknown")[index % 4],
        "licence": "CC BY",
    }


def _source_contract() -> tuple[dict, dict, dict]:
    pool = {
        "plan_sha256": "a" * 64,
        "development": [_article(index) for index in range(110)],
        "validation": [],
        "locked_test": [],
    }
    screen = {
        "plan_sha256": "a" * 64,
        "screening_scope": "machine_triage_not_human_eligibility",
        "records": [
            {
                "document_id": f"PMC{index:06d}",
                "full_text_sha256": f"{index + 1:064x}",
                "machine_eligible_for_annotation": True,
                "machine_screen_status": "strong_biomolecular_protocol_signal",
                "article_type": "research-article",
            }
            for index in range(110)
        ],
    }
    plan = finalize_screened_plan(
        pool,
        screen,
        development_size=80,
        validation_size=0,
        locked_test_size=20,
        study_id="mdmeta-independent-100-v1",
        study_status="independent_100_machine_screened_unreviewed",
        split_strategy="locked_test_stratified",
        split_seed=3997,
    )
    audit = audit_independent_plan(
        plan,
        {"document_ids": ["PMC999999"], "registry_sha256": "b" * 64},
    )
    return plan, screen, audit


def _fact(document_id: str, annotator_id: str) -> dict:
    return {
        "annotation_id": f"{annotator_id}-{document_id}-temperature",
        "document_id": document_id,
        "annotator_id": annotator_id,
        "field_name": "temperature_k",
        "normalized_value": 300,
        "unit": "K",
        "event_type": "production",
        "paragraph_id": "methods-p1",
        "paragraph_sha256": "c" * 64,
        "start_char": 12,
        "end_char": 17,
        "quote": "300 K",
        "note": None,
    }


def _unsealed_submission(
    plan: dict, screen: dict, annotator_id: str, *, add_disagreement: bool = False
) -> dict:
    sources = {row["document_id"]: row["full_text_sha256"] for row in screen["records"]}
    articles = []
    for index, row in enumerate(plan["locked_test"]):
        document_id = row["document_id"]
        facts = [_fact(document_id, annotator_id)] if index == 0 else []
        eligibility = "eligible"
        reason = "eligible_biomolecular_md_protocol"
        if add_disagreement and index == 0:
            eligibility = "ineligible"
            reason = "protocol_text_insufficient"
            facts = []
        articles.append(
            {
                "document_id": document_id,
                "source_sha256": sources[document_id],
                "eligibility": eligibility,
                "eligibility_reason": reason,
                "annotation_status": (
                    "complete_with_facts" if facts else "complete_no_facts"
                ),
                "facts": facts,
            }
        )
    return {
        "schema_version": "mdmeta.gold-annotation-submission.v1",
        "study_id": plan["study_id"],
        "plan_sha256": plan["plan_sha256"],
        "annotator_id": annotator_id,
        "independent_first_pass": True,
        "machine_predictions_seen": False,
        "peer_submission_seen": False,
        "articles": articles,
    }


def _sealed_pair() -> tuple[dict, dict, dict, dict, dict]:
    plan, screen, audit = _source_contract()
    submission_a = seal_annotation_submission(
        _unsealed_submission(plan, screen, "ann-a"), plan, screen, audit
    )
    submission_b = seal_annotation_submission(
        _unsealed_submission(plan, screen, "ann-b", add_disagreement=True),
        plan,
        screen,
        audit,
    )
    return plan, screen, audit, submission_a, submission_b


def test_sealed_submission_requires_explicit_coverage_of_all_gold20() -> None:
    plan, screen, audit = _source_contract()
    payload = _unsealed_submission(plan, screen, "ann-a")
    payload["articles"].pop()
    with pytest.raises(ValueError, match="coverage differs from gold20"):
        seal_annotation_submission(payload, plan, screen, audit)


def test_gold_fact_requires_paragraph_hash() -> None:
    plan, screen, audit = _source_contract()
    payload = _unsealed_submission(plan, screen, "ann-a")
    payload["articles"][0]["facts"][0]["paragraph_sha256"] = None
    with pytest.raises(ValueError, match="lacks paragraph_sha256"):
        seal_annotation_submission(payload, plan, screen, audit)


def test_prepare_rejects_same_annotator_identity() -> None:
    plan, screen, audit = _source_contract()
    submission = seal_annotation_submission(
        _unsealed_submission(plan, screen, "ann-a"), plan, screen, audit
    )
    with pytest.raises(ValueError, match="two distinct annotator"):
        prepare_gold_adjudication(
            plan, screen, audit, submission, deepcopy(submission)
        )


def test_complete_adjudication_freezes_private_reference_and_label_free_receipt() -> None:
    plan, screen, audit, submission_a, submission_b = _sealed_pair()
    template, comparison = prepare_gold_adjudication(
        plan, screen, audit, submission_a, submission_b
    )
    assert comparison["article_count"] == 20
    assert comparison["disagreement_count"] == 2

    disagreements = {
        row["disagreement_id"]: row for row in comparison["disagreements"]
    }
    template["status"] = "complete"
    template["adjudicator_ids"] = ["ann-a", "ann-b"]
    for decision in template["decisions"]:
        disagreement = disagreements[decision["disagreement_id"]]
        decision["decision"] = (
            "accept_a" if disagreement["kind"] == "eligibility" else "accept_candidate"
        )
        decision["note"] = "Consensus checked against the frozen paragraph."
    core = {
        key: value for key, value in template.items() if key != "adjudication_sha256"
    }
    template["adjudication_sha256"] = canonical_sha256(core)

    private_reference, receipt = freeze_gold_reference(
        plan,
        screen,
        audit,
        submission_a,
        submission_b,
        template,
        frozen_at_utc="2026-07-16T00:00:00Z",
        operator_run_id="private-roihu-gold-freeze-1",
    )
    assert private_reference["article_count"] == 20
    assert private_reference["human_reference"] is True
    assert private_reference["contains_model_predictions"] is False
    assert sum(len(row["facts"]) for row in private_reference["articles"]) == 1
    assert receipt["coverage_complete"] is True
    assert receipt["all_disagreements_resolved"] is True
    assert receipt["labels_disclosed"] is False
    assert receipt["label_statistics_disclosed"] is False
    assert receipt["reference_sha256"] == private_reference["reference_sha256"]
    assert "articles" not in receipt
    assert "fact_count" not in receipt


def test_freeze_rejects_pending_decisions() -> None:
    plan, screen, audit, submission_a, submission_b = _sealed_pair()
    template, _ = prepare_gold_adjudication(
        plan, screen, audit, submission_a, submission_b
    )
    with pytest.raises(ValueError, match="adjudication is not complete"):
        freeze_gold_reference(
            plan,
            screen,
            audit,
            submission_a,
            submission_b,
            template,
            frozen_at_utc="2026-07-16T00:00:00Z",
            operator_run_id="private-roihu-gold-freeze-1",
        )
