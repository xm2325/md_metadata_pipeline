from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .annotation import AnnotationFact, compare_annotators
from .benchmark import canonical_sha256

_REQUIRED_AUDIT_CHECKS = {
    "scale_count_is_frozen",
    "validation_is_empty",
    "gold_count_is_frozen",
    "selected_identifiers_are_unique",
    "splits_are_disjoint",
    "prior_article_overlap_is_zero",
    "selection_is_model_output_free",
    "gold_predictions_are_absent",
    "gold_role_is_sealed_dual_human",
}
_LOWER_HEX = r"^[0-9a-f]{64}$"


def _is_lower_hex(value: object, length: int = 64) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


class GoldArticleAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1)
    source_sha256: str = Field(pattern=_LOWER_HEX)
    eligibility: Literal["eligible", "ineligible"]
    eligibility_reason: str = Field(min_length=1)
    annotation_status: Literal["complete_with_facts", "complete_no_facts"]
    facts: list[AnnotationFact]

    @model_validator(mode="after")
    def check_completion(self) -> "GoldArticleAnnotation":
        if self.annotation_status == "complete_with_facts" and not self.facts:
            raise ValueError("complete_with_facts requires at least one fact")
        if self.annotation_status == "complete_no_facts" and self.facts:
            raise ValueError("complete_no_facts requires an empty facts list")
        if self.eligibility == "ineligible" and self.facts:
            raise ValueError("ineligible articles cannot contain reference facts")
        return self


class GoldAnnotationSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["mdmeta.gold-annotation-submission.v1"]
    study_id: str = Field(min_length=1)
    plan_sha256: str = Field(pattern=_LOWER_HEX)
    annotator_id: str = Field(min_length=1)
    independent_first_pass: Literal[True]
    machine_predictions_seen: Literal[False]
    peer_submission_seen: Literal[False]
    articles: list[GoldArticleAnnotation]
    submission_sha256: str = Field(pattern=_LOWER_HEX)


class AdjudicationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disagreement_id: str = Field(pattern=_LOWER_HEX)
    decision: Literal[
        "pending",
        "accept_candidate",
        "reject_candidate",
        "replace_candidate",
        "accept_a",
        "accept_b",
        "replace_eligibility",
    ]
    replacement_fact: AnnotationFact | None = None
    replacement_eligibility: Literal["eligible", "ineligible"] | None = None
    replacement_eligibility_reason: str | None = None
    note: str | None = None


class GoldAdjudication(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["mdmeta.gold-adjudication.v1"]
    study_id: str = Field(min_length=1)
    plan_sha256: str = Field(pattern=_LOWER_HEX)
    submission_a_sha256: str = Field(pattern=_LOWER_HEX)
    submission_b_sha256: str = Field(pattern=_LOWER_HEX)
    status: Literal["not_adjudicated", "complete"]
    adjudication_mode: Literal["annotator_consensus", "independent_third_reviewer"]
    adjudicator_ids: list[str]
    machine_predictions_seen: Literal[False]
    decisions: list[AdjudicationDecision]
    adjudication_sha256: str = Field(pattern=_LOWER_HEX)


def _without_commitment(payload: dict[str, Any], field: str) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != field}


def _check_commitment(payload: dict[str, Any], field: str) -> None:
    expected = canonical_sha256(_without_commitment(payload, field))
    if payload.get(field) != expected:
        raise ValueError(f"{field} commitment is invalid")


def _validate_final_plan_commitment(plan: dict[str, Any]) -> None:
    core = {
        key: value
        for key, value in plan.items()
        if key not in {"plan_sha256", "interpretation"}
    }
    for split in ("development", "validation", "locked_test"):
        core[split] = [row["document_id"] for row in plan[split]]
    if plan.get("plan_sha256") != canonical_sha256(core):
        raise ValueError("frozen plan commitment is invalid")


def validate_gold_source_contract(
    plan: dict[str, Any], screen: dict[str, Any], plan_audit: dict[str, Any]
) -> dict[str, str]:
    _validate_final_plan_commitment(plan)
    if canonical_sha256(screen) != plan.get("screen_sha256"):
        raise ValueError("full-text screen does not match the frozen plan")
    audit_core = _without_commitment(plan_audit, "audit_sha256")
    if plan_audit.get("audit_sha256") != canonical_sha256(audit_core):
        raise ValueError("plan audit commitment is invalid")
    if plan_audit.get("plan_sha256") != plan.get("plan_sha256"):
        raise ValueError("plan audit does not bind the frozen plan")
    checks = plan_audit.get("checks", {})
    if (
        plan_audit.get("passed") is not True
        or plan_audit.get("failures") != []
        or not _REQUIRED_AUDIT_CHECKS.issubset(checks)
        or not all(checks[name] is True for name in _REQUIRED_AUDIT_CHECKS)
    ):
        raise ValueError("independent plan audit did not pass all required checks")
    if plan.get("gold_predictions_generated") is not False:
        raise ValueError("gold predictions already exist")
    if plan.get("split_roles", {}).get("locked_test") != "sealed_dual_human_gold":
        raise ValueError("locked test is not declared as sealed dual-human gold")
    if len(plan.get("development", [])) != 80 or plan.get("validation"):
        raise ValueError("gold gate requires the accepted independent scale80/validation0 plan")
    if len(plan.get("locked_test", [])) != 20:
        raise ValueError("gold gate requires exactly 20 locked-test articles")

    screen_records = {row["document_id"]: row for row in screen["records"]}
    expected: dict[str, str] = {}
    for row in plan["locked_test"]:
        document_id = row["document_id"]
        record = screen_records.get(document_id)
        if record is None:
            raise ValueError(f"missing screen record for {document_id}")
        source_sha256 = record.get("full_text_sha256")
        if not _is_lower_hex(source_sha256):
            raise ValueError(f"invalid source hash for {document_id}")
        expected[document_id] = source_sha256
    return expected


def _validate_submission_articles(
    submission: GoldAnnotationSubmission, expected_sources: dict[str, str]
) -> None:
    rows = {row.document_id: row for row in submission.articles}
    if len(rows) != len(submission.articles):
        raise ValueError("annotation submission contains duplicate article identifiers")
    if set(rows) != set(expected_sources):
        missing = sorted(set(expected_sources) - set(rows))
        unexpected = sorted(set(rows) - set(expected_sources))
        raise ValueError(
            f"annotation coverage differs from gold20; missing={missing}, "
            f"unexpected={unexpected}"
        )
    annotation_ids: set[str] = set()
    for document_id, row in rows.items():
        if row.source_sha256 != expected_sources[document_id]:
            raise ValueError(f"source hash mismatch for {document_id}")
        exact_keys: set[tuple[Any, ...]] = set()
        for fact in row.facts:
            if fact.document_id != document_id:
                raise ValueError(f"fact document differs from article envelope: {document_id}")
            if fact.annotator_id != submission.annotator_id:
                raise ValueError(f"fact annotator differs from submission owner: {document_id}")
            if fact.paragraph_sha256 is None:
                raise ValueError(f"gold fact lacks paragraph_sha256: {fact.annotation_id}")
            if fact.annotation_id in annotation_ids:
                raise ValueError(f"duplicate annotation_id: {fact.annotation_id}")
            annotation_ids.add(fact.annotation_id)
            key = _gold_exact_key(fact)
            if key in exact_keys:
                raise ValueError(f"duplicate exact fact in {document_id}")
            exact_keys.add(key)


def seal_annotation_submission(
    payload: dict[str, Any],
    plan: dict[str, Any],
    screen: dict[str, Any],
    plan_audit: dict[str, Any],
) -> dict[str, Any]:
    expected_sources = validate_gold_source_contract(plan, screen, plan_audit)
    core = _without_commitment(payload, "submission_sha256")
    sealed = {**core, "submission_sha256": canonical_sha256(core)}
    if payload.get("submission_sha256") not in {None, sealed["submission_sha256"]}:
        raise ValueError("existing submission_sha256 is invalid")
    submission = GoldAnnotationSubmission.model_validate(sealed)
    if submission.study_id != plan.get("study_id"):
        raise ValueError("submission study differs from frozen plan")
    if submission.plan_sha256 != plan.get("plan_sha256"):
        raise ValueError("submission does not bind the frozen plan")
    _validate_submission_articles(submission, expected_sources)
    return submission.model_dump(mode="json")


def validate_annotation_submission(
    payload: dict[str, Any], expected_sources: dict[str, str], plan: dict[str, Any]
) -> GoldAnnotationSubmission:
    submission = GoldAnnotationSubmission.model_validate(payload)
    _check_commitment(payload, "submission_sha256")
    if submission.study_id != plan.get("study_id"):
        raise ValueError("submission study differs from frozen plan")
    if submission.plan_sha256 != plan.get("plan_sha256"):
        raise ValueError("submission does not bind the frozen plan")
    _validate_submission_articles(submission, expected_sources)
    return submission


def _gold_exact_key(fact: AnnotationFact) -> tuple[Any, ...]:
    return (
        *fact.exact_key(),
        fact.quote,
        fact.paragraph_sha256,
    )


def _disagreement_id(payload: dict[str, Any]) -> str:
    return canonical_sha256({"schema_version": "mdmeta.gold-disagreement.v1", **payload})


def _submission_by_document(
    submission: GoldAnnotationSubmission,
) -> dict[str, GoldArticleAnnotation]:
    return {row.document_id: row for row in submission.articles}


def _build_disagreements(
    submission_a: GoldAnnotationSubmission, submission_b: GoldAnnotationSubmission
) -> list[dict[str, Any]]:
    by_a = _submission_by_document(submission_a)
    by_b = _submission_by_document(submission_b)
    disagreements: list[dict[str, Any]] = []
    for document_id in sorted(by_a):
        article_a = by_a[document_id]
        article_b = by_b[document_id]
        eligibility_a = (article_a.eligibility, article_a.eligibility_reason)
        eligibility_b = (article_b.eligibility, article_b.eligibility_reason)
        if eligibility_a != eligibility_b:
            core = {
                "kind": "eligibility",
                "document_id": document_id,
                "candidate_a": {
                    "eligibility": article_a.eligibility,
                    "eligibility_reason": article_a.eligibility_reason,
                },
                "candidate_b": {
                    "eligibility": article_b.eligibility,
                    "eligibility_reason": article_b.eligibility_reason,
                },
            }
            disagreements.append({**core, "disagreement_id": _disagreement_id(core)})

        facts_a = {_gold_exact_key(fact): fact for fact in article_a.facts}
        facts_b = {_gold_exact_key(fact): fact for fact in article_b.facts}
        for source, candidates in (
            ("a", set(facts_a) - set(facts_b)),
            ("b", set(facts_b) - set(facts_a)),
        ):
            fact_map = facts_a if source == "a" else facts_b
            for key in sorted(candidates, key=repr):
                fact = fact_map[key]
                candidate = fact.model_dump(mode="json")
                core = {
                    "kind": "fact",
                    "document_id": document_id,
                    "source": source,
                    "candidate_sha256": canonical_sha256(candidate),
                }
                disagreements.append(
                    {
                        **core,
                        "candidate": candidate,
                        "disagreement_id": _disagreement_id(core),
                    }
                )
    return sorted(disagreements, key=lambda item: item["disagreement_id"])


def prepare_gold_adjudication(
    plan: dict[str, Any],
    screen: dict[str, Any],
    plan_audit: dict[str, Any],
    payload_a: dict[str, Any],
    payload_b: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    expected_sources = validate_gold_source_contract(plan, screen, plan_audit)
    submission_a = validate_annotation_submission(payload_a, expected_sources, plan)
    submission_b = validate_annotation_submission(payload_b, expected_sources, plan)
    if submission_a.annotator_id == submission_b.annotator_id:
        raise ValueError("gold reference requires two distinct annotator identifiers")
    disagreements = _build_disagreements(submission_a, submission_b)
    template_core = {
        "schema_version": "mdmeta.gold-adjudication.v1",
        "study_id": plan["study_id"],
        "plan_sha256": plan["plan_sha256"],
        "submission_a_sha256": submission_a.submission_sha256,
        "submission_b_sha256": submission_b.submission_sha256,
        "status": "not_adjudicated",
        "adjudication_mode": "annotator_consensus",
        "adjudicator_ids": [],
        "machine_predictions_seen": False,
        "decisions": [
            {
                "disagreement_id": item["disagreement_id"],
                "decision": "pending",
                "replacement_fact": None,
                "replacement_eligibility": None,
                "replacement_eligibility_reason": None,
                "note": None,
            }
            for item in disagreements
        ],
    }
    template = {
        **template_core,
        "adjudication_sha256": canonical_sha256(template_core),
    }
    comparison = compare_annotators(
        [fact for row in submission_a.articles for fact in row.facts],
        [fact for row in submission_b.articles for fact in row.facts],
    )
    private_report = {
        "schema_version": "mdmeta.gold-agreement-private.v1",
        "study_id": plan["study_id"],
        "article_count": len(expected_sources),
        "submission_a_sha256": submission_a.submission_sha256,
        "submission_b_sha256": submission_b.submission_sha256,
        "disagreement_count": len(disagreements),
        "disagreements": disagreements,
        "fact_agreement": comparison,
        "contains_model_predictions": False,
    }
    return template, private_report


def _validate_adjudicators(
    adjudication: GoldAdjudication,
    submission_a: GoldAnnotationSubmission,
    submission_b: GoldAnnotationSubmission,
) -> None:
    ids = adjudication.adjudicator_ids
    if not ids or len(set(ids)) != len(ids) or any(not item.strip() for item in ids):
        raise ValueError("adjudicator_ids must contain unique non-empty identifiers")
    annotators = {submission_a.annotator_id, submission_b.annotator_id}
    if adjudication.adjudication_mode == "annotator_consensus":
        if set(ids) != annotators:
            raise ValueError("annotator_consensus requires both original annotators")
    elif set(ids) & annotators:
        raise ValueError("independent_third_reviewer must not reuse an original annotator id")


def _reference_fact(fact: AnnotationFact) -> dict[str, Any]:
    core = {
        "document_id": fact.document_id,
        "field_name": fact.field_name,
        "normalized_value": fact.normalized_value,
        "unit": fact.unit,
        "event_type": fact.event_type.value,
        "paragraph_id": fact.paragraph_id,
        "paragraph_sha256": fact.paragraph_sha256,
        "start_char": fact.start_char,
        "end_char": fact.end_char,
        "quote": fact.quote,
    }
    return {"reference_fact_id": canonical_sha256(core), **core}


def _parse_frozen_at(value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("frozen_at_utc must be RFC 3339") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("frozen_at_utc must include a timezone")
    if parsed.utcoffset().total_seconds() != 0:
        raise ValueError("frozen_at_utc must be expressed in UTC")


def freeze_gold_reference(
    plan: dict[str, Any],
    screen: dict[str, Any],
    plan_audit: dict[str, Any],
    payload_a: dict[str, Any],
    payload_b: dict[str, Any],
    adjudication_payload: dict[str, Any],
    *,
    frozen_at_utc: str,
    operator_run_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _parse_frozen_at(frozen_at_utc)
    if not operator_run_id.strip():
        raise ValueError("operator_run_id is required")
    expected_sources = validate_gold_source_contract(plan, screen, plan_audit)
    submission_a = validate_annotation_submission(payload_a, expected_sources, plan)
    submission_b = validate_annotation_submission(payload_b, expected_sources, plan)
    if submission_a.annotator_id == submission_b.annotator_id:
        raise ValueError("gold reference requires two distinct annotator identifiers")
    adjudication = GoldAdjudication.model_validate(adjudication_payload)
    _check_commitment(adjudication_payload, "adjudication_sha256")
    if adjudication.status != "complete":
        raise ValueError("adjudication is not complete")
    if adjudication.study_id != plan.get("study_id") or adjudication.plan_sha256 != plan.get(
        "plan_sha256"
    ):
        raise ValueError("adjudication does not bind the frozen study")
    if (
        adjudication.submission_a_sha256 != submission_a.submission_sha256
        or adjudication.submission_b_sha256 != submission_b.submission_sha256
    ):
        raise ValueError("adjudication does not bind both annotation submissions")
    _validate_adjudicators(adjudication, submission_a, submission_b)

    disagreements = _build_disagreements(submission_a, submission_b)
    expected_decisions = {item["disagreement_id"]: item for item in disagreements}
    decisions = {item.disagreement_id: item for item in adjudication.decisions}
    if len(decisions) != len(adjudication.decisions):
        raise ValueError("adjudication contains duplicate disagreement decisions")
    if set(decisions) != set(expected_decisions):
        raise ValueError("adjudication does not resolve exactly the derived disagreements")

    by_a = _submission_by_document(submission_a)
    by_b = _submission_by_document(submission_b)
    final_eligibility: dict[str, tuple[str, str]] = {}
    final_facts: dict[str, dict[tuple[Any, ...], AnnotationFact]] = {}
    for document_id in sorted(expected_sources):
        row_a = by_a[document_id]
        row_b = by_b[document_id]
        eligibility_a = (row_a.eligibility, row_a.eligibility_reason)
        eligibility_b = (row_b.eligibility, row_b.eligibility_reason)
        if eligibility_a == eligibility_b:
            final_eligibility[document_id] = eligibility_a
        facts_a = {_gold_exact_key(fact): fact for fact in row_a.facts}
        facts_b = {_gold_exact_key(fact): fact for fact in row_b.facts}
        final_facts[document_id] = {
            key: facts_a[key] for key in set(facts_a) & set(facts_b)
        }

    for disagreement_id, expected in expected_decisions.items():
        decision = decisions[disagreement_id]
        if decision.decision == "pending" or not (decision.note or "").strip():
            raise ValueError(f"unresolved or undocumented disagreement: {disagreement_id}")
        document_id = expected["document_id"]
        if expected["kind"] == "eligibility":
            if decision.replacement_fact is not None:
                raise ValueError("eligibility decision cannot contain a replacement fact")
            if decision.decision == "accept_a":
                if decision.replacement_eligibility is not None:
                    raise ValueError("accept_a cannot contain a replacement eligibility")
                selected = expected["candidate_a"]
            elif decision.decision == "accept_b":
                if decision.replacement_eligibility is not None:
                    raise ValueError("accept_b cannot contain a replacement eligibility")
                selected = expected["candidate_b"]
            elif decision.decision == "replace_eligibility":
                if not decision.replacement_eligibility or not (
                    decision.replacement_eligibility_reason or ""
                ).strip():
                    raise ValueError("replacement eligibility and reason are required")
                selected = {
                    "eligibility": decision.replacement_eligibility,
                    "eligibility_reason": decision.replacement_eligibility_reason,
                }
            else:
                raise ValueError("invalid decision for an eligibility disagreement")
            final_eligibility[document_id] = (
                selected["eligibility"],
                selected["eligibility_reason"],
            )
        else:
            if decision.replacement_eligibility is not None:
                raise ValueError("fact decision cannot contain replacement eligibility")
            candidate = AnnotationFact.model_validate(expected["candidate"])
            if decision.decision == "accept_candidate":
                if decision.replacement_fact is not None:
                    raise ValueError("accept_candidate cannot contain a replacement fact")
                chosen = candidate
            elif decision.decision == "reject_candidate":
                if decision.replacement_fact is not None:
                    raise ValueError("reject_candidate cannot contain a replacement fact")
                chosen = None
            elif decision.decision == "replace_candidate":
                chosen = decision.replacement_fact
                if chosen is None:
                    raise ValueError("replace_candidate requires replacement_fact")
                if chosen.document_id != document_id or chosen.paragraph_sha256 is None:
                    raise ValueError("replacement fact lacks the bound document or paragraph hash")
                if chosen.annotator_id not in set(adjudication.adjudicator_ids):
                    raise ValueError("replacement fact must identify an adjudicator")
            else:
                raise ValueError("invalid decision for a fact disagreement")
            if chosen is not None:
                chosen_key = _gold_exact_key(chosen)
                if chosen_key in final_facts[document_id]:
                    raise ValueError("adjudication creates a duplicate reference fact")
                final_facts[document_id][chosen_key] = chosen

    reference_articles: list[dict[str, Any]] = []
    for document_id in sorted(expected_sources):
        eligibility, reason = final_eligibility[document_id]
        facts = sorted(
            (_reference_fact(fact) for fact in final_facts[document_id].values()),
            key=lambda row: row["reference_fact_id"],
        )
        if eligibility == "ineligible" and facts:
            raise ValueError(f"ineligible adjudicated article contains facts: {document_id}")
        reference_articles.append(
            {
                "document_id": document_id,
                "source_sha256": expected_sources[document_id],
                "eligibility": eligibility,
                "eligibility_reason": reason,
                "annotation_status": "complete_with_facts" if facts else "complete_no_facts",
                "facts": facts,
            }
        )

    private_core = {
        "schema_version": "mdmeta.gold-human-reference.v1",
        "study_id": plan["study_id"],
        "study_status": "gold20_dual_human_adjudicated_frozen",
        "plan_sha256": plan["plan_sha256"],
        "plan_audit_sha256": plan_audit["audit_sha256"],
        "screen_sha256": plan["screen_sha256"],
        "submission_a_sha256": submission_a.submission_sha256,
        "submission_b_sha256": submission_b.submission_sha256,
        "adjudication_sha256": adjudication.adjudication_sha256,
        "frozen_at_utc": frozen_at_utc,
        "operator_run_id": operator_run_id,
        "human_reference": True,
        "contains_model_predictions": False,
        "article_count": len(reference_articles),
        "articles": reference_articles,
    }
    private_reference = {
        **private_core,
        "reference_sha256": canonical_sha256(private_core),
    }
    receipt_core = {
        "schema_version": "mdmeta.gold-reference-public-receipt.v1",
        "study_id": plan["study_id"],
        "study_status": "gold20_dual_human_adjudicated_frozen",
        "plan_sha256": plan["plan_sha256"],
        "plan_audit_sha256": plan_audit["audit_sha256"],
        "screen_sha256": plan["screen_sha256"],
        "submission_commitments_sha256": sorted(
            [submission_a.submission_sha256, submission_b.submission_sha256]
        ),
        "adjudication_sha256": adjudication.adjudication_sha256,
        "reference_sha256": private_reference["reference_sha256"],
        "frozen_at_utc": frozen_at_utc,
        "operator_run_id": operator_run_id,
        "article_count": len(reference_articles),
        "annotator_count": 2,
        "coverage_complete": True,
        "all_disagreements_resolved": True,
        "human_reference": True,
        "contains_model_predictions": False,
        "labels_disclosed": False,
        "label_statistics_disclosed": False,
        "passed": True,
    }
    public_receipt = {
        **receipt_core,
        "receipt_sha256": canonical_sha256(receipt_core),
    }
    return private_reference, public_receipt
