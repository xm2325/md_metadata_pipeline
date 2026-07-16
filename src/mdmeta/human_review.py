from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter, defaultdict
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .integration import IntegratedMDRecord
from .models import EventType, MappingSegment, ValidationState
from .storage import SCHEMA_VERSION, SQLiteRecordStore


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewPurpose(StrEnum):
    PRODUCTION_TRIAGE = "production_triage"
    BENCHMARK_REFERENCE = "benchmark_reference"


class ReviewTier(StrEnum):
    AUTO_ACCEPT = "auto_accept"
    SINGLE_REVIEW = "single_review"
    DUAL_INDEPENDENT = "dual_independent"


class ReviewSeverity(StrEnum):
    ROUTINE = "routine"
    ELEVATED = "elevated"
    CRITICAL = "critical"


class HumanReviewPolicy(_StrictModel):
    """Versioned policy separating production triage from reference annotation."""

    policy_version: Literal["mdmeta-risk-review-policy-v1"] = (
        "mdmeta-risk-review-policy-v1"
    )
    purpose: ReviewPurpose = ReviewPurpose.PRODUCTION_TRIAGE
    confidence_threshold: float = Field(default=0.8, ge=0, le=1)
    audit_sample_rate: float = Field(default=0.05, ge=0, le=1)
    audit_salt: str = Field(default="mdmeta-production-audit-v1", min_length=1)
    require_pdbekb: bool = True
    single_value_fields: list[str] = Field(
        default_factory=lambda: ["force_field", "simulation_engine", "water_model"]
    )

    @model_validator(mode="after")
    def validate_fields(self) -> "HumanReviewPolicy":
        if self.single_value_fields != sorted(set(self.single_value_fields)):
            raise ValueError("single_value_fields must be sorted and unique")
        return self


class ReviewEvidenceBinding(_StrictModel):
    """Minimal locator for review; deliberately excludes evidence quotes and payloads."""

    source: Literal[
        "literature_fact",
        "protocol_event",
        "identifier_validation",
        "mapping_discovery",
        "residue_mapping",
        "pdbekb",
        "completeness",
        "policy",
    ]
    field: str | None = None
    value: str | bool | float | int | None = None
    event_id: str | None = None
    identifier: str | None = None
    state: str | None = None
    endpoint: str | None = None
    paragraph_id: str | None = None
    start_char: int | None = Field(default=None, ge=0)
    end_char: int | None = Field(default=None, gt=0)
    context_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    report_commitment_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )


class ReviewReason(_StrictModel):
    code: str = Field(min_length=1)
    category: Literal[
        "extraction",
        "evidence",
        "external_validation",
        "residue_mapping",
        "coverage",
        "pdbekb",
        "quality_control",
        "benchmark",
    ]
    severity: ReviewSeverity
    summary: str = Field(min_length=1)
    review_prompt: str = Field(min_length=1)
    evidence_bindings: list[ReviewEvidenceBinding] = Field(default_factory=list)


SECOND_REVIEW_TRIGGERS = [
    "first reviewer cannot resolve the item from the bound evidence and named source",
    "first reviewer changes a scientific value, event type, residue mapping, or evidence span",
    "first reviewer finds two plausible interpretations or a source disagreement",
    "quality-control review disagrees with an automatic acceptance",
    "the record will support a regulated or otherwise high-impact downstream decision",
]


class HumanReviewItem(_StrictModel):
    document_id: str = Field(min_length=1)
    title: str
    source_uri: str
    review_tier: ReviewTier
    priority_score: int = Field(ge=0, le=100)
    audit_sample: bool = False
    review_reasons: list[ReviewReason]
    review_prompts: list[str]
    second_review_triggers: list[str]

    @model_validator(mode="after")
    def validate_item(self) -> "HumanReviewItem":
        codes = [reason.code for reason in self.review_reasons]
        if codes != sorted(set(codes)):
            raise ValueError("review reason codes must be sorted and unique")
        expected_prompts = sorted({reason.review_prompt for reason in self.review_reasons})
        if self.review_prompts != expected_prompts:
            raise ValueError("review_prompts must match review reasons")
        if self.second_review_triggers != SECOND_REVIEW_TRIGGERS:
            raise ValueError("second_review_triggers do not match policy")
        if self.review_tier is ReviewTier.AUTO_ACCEPT:
            if self.review_reasons or self.priority_score != 0 or self.audit_sample:
                raise ValueError("auto-accepted items cannot contain review triggers")
        elif not self.review_reasons:
            raise ValueError("reviewed items require at least one review reason")
        if self.audit_sample and not any(
            reason.code == "quality_control_sample" for reason in self.review_reasons
        ):
            raise ValueError("audit samples require a quality_control_sample reason")
        return self


class HumanReviewQueue(_StrictModel):
    schema_version: Literal["mdmeta-human-review-queue-v1"] = (
        "mdmeta-human-review-queue-v1"
    )
    source_database_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_database_schema_version: Literal[2] = SCHEMA_VERSION
    source_article_count: int = Field(ge=0)
    policy: HumanReviewPolicy
    items: list[HumanReviewItem]
    review_tier_counts: dict[str, int]
    review_reason_counts: dict[str, int]
    content_commitment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_summary_and_commitment(self) -> "HumanReviewQueue":
        document_ids = [item.document_id for item in self.items]
        if document_ids != sorted(set(document_ids)):
            raise ValueError("review items must be sorted by unique document_id")
        if len(self.items) != self.source_article_count:
            raise ValueError("review item count does not match source_article_count")
        expected_tiers = dict(
            sorted(Counter(item.review_tier.value for item in self.items).items())
        )
        if self.review_tier_counts != expected_tiers:
            raise ValueError("review_tier_counts does not match items")
        expected_reasons = dict(
            sorted(
                Counter(
                    reason.code
                    for item in self.items
                    for reason in item.review_reasons
                ).items()
            )
        )
        if self.review_reason_counts != expected_reasons:
            raise ValueError("review_reason_counts does not match items")
        body = self.model_dump(mode="json", exclude={"content_commitment_sha256"})
        if self.content_commitment_sha256 != _canonical_sha256(body):
            raise ValueError("content_commitment_sha256 does not match queue content")
        return self


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError(f"refusing to replace symlink: {path}")
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _sampled(document_id: str, policy: HumanReviewPolicy) -> bool:
    if policy.audit_sample_rate <= 0:
        return False
    digest = hashlib.sha256(
        f"{policy.audit_salt}\0{document_id}".encode("utf-8")
    ).digest()
    value = int.from_bytes(digest[:8], "big") / 2**64
    return value < policy.audit_sample_rate


def _evidence_binding(source: str, evidence: Any, **values: object) -> ReviewEvidenceBinding:
    return ReviewEvidenceBinding(
        source=source,
        paragraph_id=evidence.paragraph_id,
        start_char=evidence.start_char,
        end_char=evidence.end_char,
        context_sha256=evidence.context_sha256,
        **values,
    )


def _validation_identifier(query: dict[str, str]) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(query.items()))


def _overlap(left: MappingSegment, right: MappingSegment) -> bool:
    if left.pdb_start is None or left.pdb_end is None:
        return False
    if right.pdb_start is None or right.pdb_end is None:
        return False
    return max(left.pdb_start, right.pdb_start) <= min(left.pdb_end, right.pdb_end)


def _priority_score(reasons: list[ReviewReason]) -> int:
    weights = {
        ReviewSeverity.ROUTINE: 10,
        ReviewSeverity.ELEVATED: 30,
        ReviewSeverity.CRITICAL: 100,
    }
    return min(100, sum(weights[reason.severity] for reason in reasons))


def _reason(
    code: str,
    category: str,
    severity: ReviewSeverity,
    summary: str,
    prompt: str,
    bindings: list[ReviewEvidenceBinding] | None = None,
) -> ReviewReason:
    return ReviewReason(
        code=code,
        category=category,
        severity=severity,
        summary=summary,
        review_prompt=prompt,
        evidence_bindings=bindings or [],
    )


def review_record(
    record: IntegratedMDRecord,
    *,
    policy: HumanReviewPolicy,
    pdbekb_by_accession: dict[str, list[dict[str, object]]] | None = None,
) -> HumanReviewItem:
    """Apply deterministic risk rules and expose exactly what a reviewer must inspect."""

    pdbekb_by_accession = pdbekb_by_accession or {}
    reasons: dict[str, ReviewReason] = {}

    def add(reason: ReviewReason) -> None:
        existing = reasons.get(reason.code)
        if existing is None:
            reasons[reason.code] = reason
            return
        bindings = [
            *existing.evidence_bindings,
            *reason.evidence_bindings,
        ]
        reasons[reason.code] = existing.model_copy(
            update={"evidence_bindings": bindings}
        )

    for fact in record.literature_facts:
        binding = _evidence_binding(
            "literature_fact", fact.evidence, field=fact.field, value=fact.value
        )
        if fact.confidence < policy.confidence_threshold:
            add(
                _reason(
                    "low_confidence_literature_fact",
                    "extraction",
                    ReviewSeverity.ELEVATED,
                    f"A literature fact is below confidence threshold {policy.confidence_threshold:g}.",
                    "Does the bound text explicitly support the extracted field and normalized value?",
                    [binding],
                )
            )

    facts_by_field: dict[str, set[str]] = defaultdict(set)
    fact_bindings: dict[str, list[ReviewEvidenceBinding]] = defaultdict(list)
    for fact in record.literature_facts:
        if fact.field in policy.single_value_fields:
            facts_by_field[fact.field].add(json.dumps(fact.value, sort_keys=True))
            fact_bindings[fact.field].append(
                _evidence_binding(
                    "literature_fact", fact.evidence, field=fact.field, value=fact.value
                )
            )
    conflicting_fields = sorted(
        field for field, values in facts_by_field.items() if len(values) > 1
    )
    if conflicting_fields:
        add(
            _reason(
                "conflicting_literature_facts",
                "extraction",
                ReviewSeverity.CRITICAL,
                "A field expected to be single-valued has incompatible extracted values: "
                + ", ".join(conflicting_fields),
                "Which value is supported for each conflicting field, or is the field genuinely multi-valued?",
                [binding for field in conflicting_fields for binding in fact_bindings[field]],
            )
        )

    for event in record.protocol_events:
        bindings = [
            _evidence_binding(
                "protocol_event", evidence, event_id=event.event_id, field="event_type",
                value=event.event_type.value,
            )
            for evidence in event.evidence
        ]
        if not event.evidence:
            add(
                _reason(
                    "missing_protocol_event_evidence",
                    "evidence",
                    ReviewSeverity.CRITICAL,
                    f"Protocol event {event.event_id} has no evidence binding.",
                    "Can this event be bound to an exact source span, or must it be removed?",
                    [
                        ReviewEvidenceBinding(
                            source="protocol_event", event_id=event.event_id
                        )
                    ],
                )
            )
        if event.confidence < policy.confidence_threshold:
            add(
                _reason(
                    "low_confidence_protocol_event",
                    "extraction",
                    ReviewSeverity.ELEVATED,
                    f"A protocol event is below confidence threshold {policy.confidence_threshold:g}.",
                    "Does the evidence support the event phase and every populated numerical attribute?",
                    bindings,
                )
            )
        if event.event_type is EventType.UNKNOWN:
            add(
                _reason(
                    "unknown_protocol_event_type",
                    "extraction",
                    ReviewSeverity.ELEVATED,
                    "A protocol event could not be assigned to a supported phase.",
                    "Which supported phase applies, or should this remain explicitly unknown?",
                    bindings,
                )
            )

    method_fields = {"force_field", "simulation_engine", "water_model"}
    if not record.protocol_events and any(
        fact.field in method_fields for fact in record.literature_facts
    ):
        add(
            _reason(
                "protocol_signal_without_event",
                "coverage",
                ReviewSeverity.ELEVATED,
                "The article has MD-method facts but no protocol event.",
                "Does the source contain a duration, ensemble, temperature, pressure, timestep, or protocol phase that was missed?",
                [
                    _evidence_binding(
                        "literature_fact", fact.evidence, field=fact.field, value=fact.value
                    )
                    for fact in record.literature_facts
                    if fact.field in method_fields
                ],
            )
        )

    validation_groups = (
        record.pdb_validations,
        record.uniprot_validations,
        record.mapping_validations,
    )
    for validation in (item for group in validation_groups for item in group):
        if validation.state not in {ValidationState.UNRESOLVED, ValidationState.CONFLICT}:
            continue
        identifier = _validation_identifier(validation.query)
        binding = ReviewEvidenceBinding(
            source="identifier_validation",
            identifier=identifier,
            state=validation.state.value,
            endpoint=validation.endpoint,
        )
        if validation.state is ValidationState.CONFLICT:
            add(
                _reason(
                    "external_identifier_conflict",
                    "external_validation",
                    ReviewSeverity.CRITICAL,
                    "An extracted identifier or mapping conflicts with an external source.",
                    "Does the cited source, identifier version, and current external record resolve this conflict?",
                    [binding],
                )
            )
        else:
            add(
                _reason(
                    "external_identifier_unresolved",
                    "external_validation",
                    ReviewSeverity.ELEVATED,
                    "An external identifier or mapping check did not reach a scientific result.",
                    "Is this a transient service failure, an obsolete identifier, or an unsupported mapping?",
                    [binding],
                )
            )

    for discovery in record.mapping_discoveries:
        if discovery.state not in {ValidationState.UNRESOLVED, ValidationState.CONFLICT}:
            continue
        binding = ReviewEvidenceBinding(
            source="mapping_discovery",
            identifier=discovery.pdb_id,
            state=discovery.state.value,
            endpoint=discovery.endpoint,
        )
        code = (
            "mapping_discovery_conflict"
            if discovery.state is ValidationState.CONFLICT
            else "mapping_discovery_unresolved"
        )
        severity = (
            ReviewSeverity.CRITICAL
            if discovery.state is ValidationState.CONFLICT
            else ReviewSeverity.ELEVATED
        )
        add(
            _reason(
                code,
                "external_validation",
                severity,
                f"PDB-to-UniProt discovery is {discovery.state.value} for {discovery.pdb_id}.",
                "Which UniProt accession and chain/range mapping is supported by the current SIFTS source?",
                [binding],
            )
        )

    grouped_segments: dict[tuple[str, str], list[MappingSegment]] = defaultdict(list)
    for segment in record.residue_mappings:
        grouped_segments[(segment.pdb_id.upper(), segment.chain_id)].append(segment)
    ambiguous_bindings: list[ReviewEvidenceBinding] = []
    for (pdb_id, chain_id), segments in sorted(grouped_segments.items()):
        for index, left in enumerate(segments):
            for right in segments[index + 1 :]:
                if left.uniprot_accession == right.uniprot_accession or not _overlap(
                    left, right
                ):
                    continue
                for segment in (left, right):
                    ambiguous_bindings.append(
                        ReviewEvidenceBinding(
                            source="residue_mapping",
                            identifier=(
                                f"{pdb_id}:{chain_id}:{segment.pdb_start}-{segment.pdb_end}"
                                f"->{segment.uniprot_accession}:"
                                f"{segment.uniprot_start}-{segment.uniprot_end}"
                            ),
                        )
                    )
    if ambiguous_bindings:
        add(
            _reason(
                "overlapping_residue_mapping",
                "residue_mapping",
                ReviewSeverity.CRITICAL,
                "Overlapping residues on one PDB chain map to different UniProt accessions.",
                "Is this a real chimera/isoform boundary, or which accession and residue ranges are correct?",
                ambiguous_bindings,
            )
        )

    incomplete_values = {
        "conflict",
        "failed",
        "incomplete",
        "partial",
        "unresolved",
    }
    incomplete_bindings = [
        ReviewEvidenceBinding(
            source="completeness", field=field, value=value
        )
        for field, value in sorted(record.completeness.items())
        if any(marker in value.casefold() for marker in incomplete_values)
    ]
    if incomplete_bindings:
        add(
            _reason(
                "incomplete_pipeline_stage",
                "coverage",
                ReviewSeverity.ELEVATED,
                "One or more pipeline completeness fields are partial, unresolved, or failed.",
                "Is the incomplete stage expected for this article, or does it require reprocessing/correction?",
                incomplete_bindings,
            )
        )

    mapped_accessions = sorted(
        {segment.uniprot_accession.upper() for segment in record.residue_mappings}
    )
    for accession in mapped_accessions:
        stored_rows = pdbekb_by_accession.get(accession, [])
        if not stored_rows:
            if policy.require_pdbekb:
                add(
                    _reason(
                        "missing_pdbekb_enrichment",
                        "pdbekb",
                        ReviewSeverity.ELEVATED,
                        f"No PDBe-KB enrichment is stored for mapped accession {accession}.",
                        "Should this accession be re-enriched, or is PDBe-KB out of scope for this record?",
                        [ReviewEvidenceBinding(source="pdbekb", identifier=accession)],
                    )
                )
            continue
        states = sorted(
            {
                str(row["enrichment"]["state"])
                for row in stored_rows
                if isinstance(row.get("enrichment"), dict)
            }
        )
        bindings = [
            ReviewEvidenceBinding(
                source="pdbekb",
                identifier=accession,
                state=str(row["enrichment"]["state"]),
                report_commitment_sha256=str(row["report_commitment_sha256"]),
            )
            for row in stored_rows
            if isinstance(row.get("enrichment"), dict)
        ]
        if len(states) > 1:
            add(
                _reason(
                    "pdbekb_state_disagreement",
                    "pdbekb",
                    ReviewSeverity.ELEVATED,
                    f"Stored PDBe-KB reports disagree on state for {accession}: {', '.join(states)}.",
                    "Which report represents the intended release snapshot, and did upstream data legitimately change?",
                    bindings,
                )
            )
        if ValidationState.CONFLICT.value in states:
            add(
                _reason(
                    "pdbekb_conflict",
                    "pdbekb",
                    ReviewSeverity.CRITICAL,
                    f"PDBe-KB enrichment conflicts for {accession}.",
                    "Does the current PDBe-KB annotation support the accession, ranges, partners, and linked structures?",
                    bindings,
                )
            )
        elif states and set(states) == {ValidationState.UNRESOLVED.value}:
            add(
                _reason(
                    "pdbekb_unresolved",
                    "pdbekb",
                    ReviewSeverity.ELEVATED,
                    f"PDBe-KB enrichment did not resolve for {accession}.",
                    "Is the PDBe-KB result a transient retrieval failure or a persistent unsupported accession?",
                    bindings,
                )
            )

    if policy.purpose is ReviewPurpose.BENCHMARK_REFERENCE:
        add(
            _reason(
                "benchmark_independent_double_review",
                "benchmark",
                ReviewSeverity.CRITICAL,
                "Every reference item requires two blinded, independent annotations.",
                "Do both reviewers independently agree on eligibility, evidence spans, values, events, and mappings before adjudication?",
                [ReviewEvidenceBinding(source="policy")],
            )
        )

    audit_sample = False
    if not reasons and _sampled(record.article.document_id, policy):
        audit_sample = True
        add(
            _reason(
                "quality_control_sample",
                "quality_control",
                ReviewSeverity.ROUTINE,
                "This high-certainty record was deterministically sampled to measure auto-accept drift.",
                "Does a source-to-record check confirm that automatic acceptance missed no material error?",
                [ReviewEvidenceBinding(source="policy")],
            )
        )

    ordered_reasons = [reasons[code] for code in sorted(reasons)]
    if policy.purpose is ReviewPurpose.BENCHMARK_REFERENCE or any(
        reason.severity is ReviewSeverity.CRITICAL for reason in ordered_reasons
    ):
        tier = ReviewTier.DUAL_INDEPENDENT
    elif ordered_reasons:
        tier = ReviewTier.SINGLE_REVIEW
    else:
        tier = ReviewTier.AUTO_ACCEPT
    return HumanReviewItem(
        document_id=record.article.document_id,
        title=record.article.title,
        source_uri=record.article.source_uri,
        review_tier=tier,
        priority_score=_priority_score(ordered_reasons),
        audit_sample=audit_sample,
        review_reasons=ordered_reasons,
        review_prompts=sorted({reason.review_prompt for reason in ordered_reasons}),
        second_review_triggers=SECOND_REVIEW_TRIGGERS,
    )


def build_human_review_queue(
    database: str | Path,
    *,
    policy: HumanReviewPolicy | None = None,
) -> HumanReviewQueue:
    database_path = Path(database)
    for suffix in ("-wal", "-shm"):
        if database_path.with_name(database_path.name + suffix).exists():
            raise RuntimeError(
                "human-review export requires a checkpointed database without sidecars"
            )
    store = SQLiteRecordStore(database_path, read_only=True)
    if store.schema_version() != SCHEMA_VERSION:
        raise RuntimeError(f"human-review export requires schema {SCHEMA_VERSION}")
    selected_policy = policy or HumanReviewPolicy()
    pdbekb_by_accession: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in store.list_pdbekb_enrichments():
        enrichment = row.get("enrichment")
        if not isinstance(enrichment, dict):
            raise ValueError("stored PDBe-KB enrichment is not an object")
        accession = str(enrichment.get("accession", "")).upper()
        if not accession:
            raise ValueError("stored PDBe-KB enrichment has no accession")
        pdbekb_by_accession[accession].append(row)
    items = [
        review_record(
            IntegratedMDRecord.model_validate(json.loads(str(row["record_json"]))),
            policy=selected_policy,
            pdbekb_by_accession=pdbekb_by_accession,
        )
        for row in store.verification_rows()
    ]
    items.sort(key=lambda item: item.document_id)
    body: dict[str, object] = {
        "schema_version": "mdmeta-human-review-queue-v1",
        "source_database_sha256": _file_sha256(database_path),
        "source_database_schema_version": SCHEMA_VERSION,
        "source_article_count": len(items),
        "policy": selected_policy.model_dump(mode="json"),
        "items": [item.model_dump(mode="json") for item in items],
        "review_tier_counts": dict(
            sorted(Counter(item.review_tier.value for item in items).items())
        ),
        "review_reason_counts": dict(
            sorted(
                Counter(
                    reason.code for item in items for reason in item.review_reasons
                ).items()
            )
        ),
    }
    body["content_commitment_sha256"] = _canonical_sha256(body)
    return HumanReviewQueue.model_validate(body)


def export_human_review_queue(
    database: str | Path,
    output: str | Path,
    *,
    policy: HumanReviewPolicy | None = None,
) -> HumanReviewQueue:
    queue = build_human_review_queue(database, policy=policy)
    destination = Path(output)
    rendered = (
        json.dumps(
            queue.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
        + b"\n"
    )
    _atomic_write(destination, rendered)
    return queue


def verify_human_review_queue(
    queue_path: str | Path,
    *,
    database: str | Path | None = None,
) -> HumanReviewQueue:
    path = Path(queue_path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("review queue must be a regular file")
    if path.stat().st_size > 128 * 1024 * 1024:
        raise ValueError("review queue exceeds the 128 MiB verification limit")
    queue = HumanReviewQueue.model_validate_json(path.read_text(encoding="utf-8"))
    if database is not None:
        database_path = Path(database)
        if _file_sha256(database_path) != queue.source_database_sha256:
            raise ValueError("source database SHA-256 does not match review queue")
        store = SQLiteRecordStore(database_path, read_only=True)
        if store.count_articles() != queue.source_article_count:
            raise ValueError("source database article count does not match review queue")
    return queue


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build or verify a deterministic risk-based human review queue."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--database", type=Path, required=True)
    build_parser.add_argument("--output", type=Path, required=True)
    build_parser.add_argument(
        "--purpose", choices=[item.value for item in ReviewPurpose],
        default=ReviewPurpose.PRODUCTION_TRIAGE.value,
    )
    build_parser.add_argument("--confidence-threshold", type=float, default=0.8)
    build_parser.add_argument("--audit-sample-rate", type=float, default=0.05)
    build_parser.add_argument("--audit-salt", default="mdmeta-production-audit-v1")
    build_parser.add_argument("--allow-missing-pdbekb", action="store_true")
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--queue", type=Path, required=True)
    verify_parser.add_argument("--database", type=Path)
    args = parser.parse_args()
    if args.command == "build":
        selected_policy = HumanReviewPolicy(
            purpose=args.purpose,
            confidence_threshold=args.confidence_threshold,
            audit_sample_rate=args.audit_sample_rate,
            audit_salt=args.audit_salt,
            require_pdbekb=not args.allow_missing_pdbekb,
        )
        result = export_human_review_queue(
            args.database, args.output, policy=selected_policy
        )
    else:
        result = verify_human_review_queue(args.queue, database=args.database)
    print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
