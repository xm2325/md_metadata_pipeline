from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mdmeta.human_review import (
    HumanReviewPolicy,
    HumanReviewQueue,
    ReviewPurpose,
    ReviewTier,
    build_human_review_queue,
    export_human_review_queue,
    review_record,
    verify_human_review_queue,
)
from mdmeta.integration import (
    ArticleMetadata,
    IntegratedMDRecord,
    LiteratureFact,
    MappingDiscovery,
    ProvenanceRecord,
)
from mdmeta.models import (
    EventType,
    Evidence,
    MappingSegment,
    ProtocolEvent,
    ValidationRecord,
    ValidationState,
)
from mdmeta.storage import SQLiteRecordStore


def _evidence(document_id: str = "DOC1", quote: str = "300 K") -> Evidence:
    return Evidence(
        document_id=document_id,
        section="Methods",
        paragraph_id="p1",
        quote=quote,
        start_char=0,
        end_char=len(quote),
        context_sha256=hashlib.sha256(quote.encode()).hexdigest(),
    )


def _record(
    *,
    document_id: str = "DOC1",
    facts: list[LiteratureFact] | None = None,
    events: list[ProtocolEvent] | None = None,
    validations: list[ValidationRecord] | None = None,
    discoveries: list[MappingDiscovery] | None = None,
    mappings: list[MappingSegment] | None = None,
    completeness: dict[str, str] | None = None,
) -> IntegratedMDRecord:
    return IntegratedMDRecord(
        article=ArticleMetadata(
            document_id=document_id,
            title=f"Article {document_id}",
            source_uri=f"https://example.org/articles/{document_id}",
            full_text_sha256=hashlib.sha256(document_id.encode()).hexdigest(),
        ),
        literature_facts=facts or [],
        protocol_events=events or [],
        pdb_validations=validations or [],
        mapping_discoveries=discoveries or [],
        uniprot_validations=[],
        mapping_validations=[],
        residue_mappings=mappings or [],
        provenance=ProvenanceRecord(),
        completeness=completeness or {"pipeline": "complete"},
    )


def _policy(**values: object) -> HumanReviewPolicy:
    return HumanReviewPolicy(
        audit_sample_rate=0,
        require_pdbekb=False,
        **values,
    )


def test_high_certainty_record_is_auto_accepted() -> None:
    event = ProtocolEvent(
        event_id="event-1",
        event_type=EventType.PRODUCTION,
        duration_ps=100_000,
        evidence=[_evidence()],
        relation_method="fixture",
        confidence=0.95,
    )

    item = review_record(_record(events=[event]), policy=_policy())

    assert item.review_tier is ReviewTier.AUTO_ACCEPT
    assert item.priority_score == 0
    assert item.review_reasons == []
    assert item.review_prompts == []


def test_routine_uncertainty_routes_to_one_reviewer_with_prompt() -> None:
    event = ProtocolEvent(
        event_id="event-1",
        event_type=EventType.PRODUCTION,
        duration_ps=100_000,
        evidence=[_evidence()],
        relation_method="fixture",
        confidence=0.6,
    )

    item = review_record(_record(events=[event]), policy=_policy())

    assert item.review_tier is ReviewTier.SINGLE_REVIEW
    assert [reason.code for reason in item.review_reasons] == [
        "low_confidence_protocol_event"
    ]
    assert "event phase" in item.review_prompts[0]
    binding = item.review_reasons[0].evidence_bindings[0]
    assert binding.event_id == "event-1"
    assert binding.paragraph_id == "p1"
    assert not hasattr(binding, "quote")


def test_multiple_engines_are_not_a_conflict_unless_policy_declares_single_value() -> None:
    facts = [
        LiteratureFact(
            field="simulation_engine",
            value=value,
            evidence=_evidence(quote=value),
            extraction_method="fixture",
            confidence=1,
        )
        for value in ("GROMACS", "NAMD")
    ]
    event = ProtocolEvent(
        event_id="event-1",
        event_type=EventType.PRODUCTION,
        evidence=[_evidence()],
        relation_method="fixture",
        confidence=1,
    )

    item = review_record(_record(facts=facts, events=[event]), policy=_policy())

    assert item.review_tier is ReviewTier.AUTO_ACCEPT
    assert item.review_reasons == []


def test_critical_ambiguity_requires_blinded_independent_double_review() -> None:
    facts = [
        LiteratureFact(
            field="simulation_engine",
            value=value,
            evidence=_evidence(quote=value),
            extraction_method="fixture",
            confidence=0.5,
        )
        for value in ("GROMACS", "NAMD")
    ]
    validation = ValidationRecord(
        identifier_type="pdb",
        query={"pdb_id": "1ABC"},
        state=ValidationState.UNRESOLVED,
        endpoint="https://example.org/pdb/1abc",
        reason="network_failure",
    )
    discovery = MappingDiscovery(
        pdb_id="1ABC",
        state=ValidationState.CONFLICT,
        endpoint="https://example.org/sifts/1abc",
        reason="ambiguous",
    )
    mappings = [
        MappingSegment(
            pdb_id="1ABC",
            chain_id="A",
            uniprot_accession=accession,
            pdb_start=1,
            pdb_end=20,
            uniprot_start=offset,
            uniprot_end=offset + 19,
        )
        for accession, offset in (("P12345", 1), ("Q99999", 50))
    ]

    item = review_record(
        _record(
            facts=facts,
            validations=[validation],
            discoveries=[discovery],
            mappings=mappings,
            completeness={"sifts_mapping": "partial"},
        ),
        policy=_policy(
            single_value_fields=["force_field", "simulation_engine", "water_model"]
        ),
    )

    assert item.review_tier is ReviewTier.DUAL_INDEPENDENT
    codes = {reason.code for reason in item.review_reasons}
    assert {
        "conflicting_literature_facts",
        "external_identifier_unresolved",
        "incomplete_pipeline_stage",
        "mapping_discovery_conflict",
        "overlapping_residue_mapping",
        "protocol_signal_without_event",
    } <= codes
    assert item.priority_score == 100
    assert item.second_review_triggers


def test_benchmark_reference_forces_double_review_without_selecting_by_uncertainty() -> None:
    item = review_record(
        _record(),
        policy=_policy(purpose=ReviewPurpose.BENCHMARK_REFERENCE),
    )

    assert item.review_tier is ReviewTier.DUAL_INDEPENDENT
    assert [reason.code for reason in item.review_reasons] == [
        "benchmark_independent_double_review"
    ]


def test_deterministic_audit_sample_checks_auto_accept_drift() -> None:
    item = review_record(
        _record(),
        policy=HumanReviewPolicy(audit_sample_rate=1, require_pdbekb=False),
    )

    assert item.review_tier is ReviewTier.SINGLE_REVIEW
    assert item.audit_sample is True
    assert [reason.code for reason in item.review_reasons] == [
        "quality_control_sample"
    ]


def test_review_queue_is_deterministic_content_bound_and_database_bound(
    tmp_path: Path,
) -> None:
    database = tmp_path / "records.sqlite"
    store = SQLiteRecordStore(database)
    store.write(_record(document_id="DOC2"))
    store.write(_record(document_id="DOC1"))
    store.checkpoint()
    policy = _policy()

    first = export_human_review_queue(
        database,
        tmp_path / "first.json",
        implementation_git_commit="a" * 40,
        policy=policy,
    )
    second = build_human_review_queue(
        database, implementation_git_commit="a" * 40, policy=policy
    )

    assert first == second
    assert [item.document_id for item in first.items] == ["DOC1", "DOC2"]
    assert first.review_tier_counts == {"auto_accept": 2}
    assert first.review_reason_counts == {}
    assert first.software_version == "0.13.0"
    assert first.implementation_git_commit == "a" * 40
    assert verify_human_review_queue(
        tmp_path / "first.json", database=database
    ) == first

    payload = first.model_dump(mode="json")
    payload["review_tier_counts"] = {"auto_accept": 1}
    with pytest.raises(ValueError, match="review_tier_counts"):
        HumanReviewQueue.model_validate(payload)


def test_review_queue_rejects_uncheckpointed_database(tmp_path: Path) -> None:
    database = tmp_path / "records.sqlite"
    store = SQLiteRecordStore(database)
    store.write(_record())
    store.checkpoint()
    database.with_name(database.name + "-wal").write_bytes(b"sidecar")

    with pytest.raises(RuntimeError, match="checkpointed database"):
        build_human_review_queue(
            database, implementation_git_commit="a" * 40, policy=_policy()
        )


def test_model_batch_rejections_are_bound_and_routed(tmp_path: Path) -> None:
    database = tmp_path / "records.sqlite"
    store = SQLiteRecordStore(database)
    store.write(_record())
    store.checkpoint()
    summary = tmp_path / "model-summary.json"
    summary.write_text(
        json.dumps(
            {
                "batch": {
                    "per_article": {
                        "DOC1": {
                            "paragraph_count": 3,
                            "accepted_paragraph_count": 2,
                            "accepted_with_evidence_rejections_count": 1,
                            "rejected_paragraph_count": 1,
                            "generation_rejected_count": 1,
                            "event_count": 0,
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    queue = build_human_review_queue(
        database,
        implementation_git_commit="b" * 40,
        policy=_policy(),
        model_summary=summary,
    )

    assert queue.model_summary_sha256 == hashlib.sha256(summary.read_bytes()).hexdigest()
    assert queue.items[0].review_tier is ReviewTier.SINGLE_REVIEW
    assert {reason.code for reason in queue.items[0].review_reasons} == {
        "model_evidence_rejection",
        "model_generation_rejection",
    }
