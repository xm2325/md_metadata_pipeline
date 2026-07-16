from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import RequestAttempt, ValidationState
from .validation import IdentifierValidator


PDBEKB_ANNOTATIONS = "https://www.ebi.ac.uk/pdbe/graph-api/uniprot/annotations/{accession}"
PDBEKB_PARTNERS = "https://www.ebi.ac.uk/pdbe/graph-api/uniprot/annotation_partners/{accession}"
_UNIPROT_ACCESSION = re.compile(r"^[A-Z0-9]{6,10}$")
_PDB_ID = re.compile(r"^[0-9][A-Z0-9]{3}$")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PDBeKBEndpointResult(_StrictModel):
    state: ValidationState
    endpoint: str
    reason: str
    http_status: int | None = None
    response_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    attempts: int = Field(default=0, ge=0)
    cache_hit: bool = False
    request_log: list[RequestAttempt] = Field(default_factory=list)


class PDBeKBAnnotationGroup(_StrictModel):
    name: str
    accession: str
    data_type: str
    residue_range_count: int = Field(ge=0)
    covered_sequence_position_count: int = Field(ge=0)
    pdb_ids: list[str] = Field(default_factory=list)
    resource_urls: list[str] = Field(default_factory=list)
    confidence_classifications: list[str] = Field(default_factory=list)


class PDBeKBPartner(_StrictModel):
    resource_name: str
    url: str
    annotation_category: str


class PDBeKBEnrichment(_StrictModel):
    accession: str
    state: ValidationState
    sequence_length: int | None = Field(default=None, ge=1)
    annotation_result: PDBeKBEndpointResult
    partner_result: PDBeKBEndpointResult
    annotation_groups: list[PDBeKBAnnotationGroup] = Field(default_factory=list)
    partners: list[PDBeKBPartner] = Field(default_factory=list)


class PDBeKBBatchReport(_StrictModel):
    schema_version: Literal["pdbekb-enrichment-batch-v1"] = (
        "pdbekb-enrichment-batch-v1"
    )
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_database_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_database_schema_version: int = Field(ge=1)
    source_article_count: int = Field(ge=0)
    requested_accessions: list[str]
    enrichments: list[PDBeKBEnrichment]
    state_counts: dict[str, int]
    annotation_group_count: int = Field(ge=0)
    annotation_residue_range_count: int = Field(ge=0)
    partner_count: int = Field(ge=0)
    linked_pdb_id_count: int = Field(ge=0)
    content_commitment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_summary_and_commitment(self) -> "PDBeKBBatchReport":
        accessions = [item.accession for item in self.enrichments]
        if accessions != self.requested_accessions:
            raise ValueError("enrichments must match requested_accessions in order")
        if accessions != sorted(set(accessions)):
            raise ValueError("requested_accessions must be sorted and unique")
        expected_states = dict(
            sorted(Counter(item.state.value for item in self.enrichments).items())
        )
        if self.state_counts != expected_states:
            raise ValueError("state_counts does not match enrichments")
        groups = [group for item in self.enrichments for group in item.annotation_groups]
        if self.annotation_group_count != len(groups):
            raise ValueError("annotation_group_count does not match enrichments")
        if self.annotation_residue_range_count != sum(
            group.residue_range_count for group in groups
        ):
            raise ValueError("annotation_residue_range_count does not match enrichments")
        if self.partner_count != sum(len(item.partners) for item in self.enrichments):
            raise ValueError("partner_count does not match enrichments")
        pdb_ids = {pdb_id for group in groups for pdb_id in group.pdb_ids}
        if self.linked_pdb_id_count != len(pdb_ids):
            raise ValueError("linked_pdb_id_count does not match enrichments")
        body = self.model_dump(mode="json", exclude={"content_commitment_sha256"})
        body["generated_at"] = self.generated_at.isoformat()
        expected = _canonical_hash(body)
        if self.content_commitment_sha256 != expected:
            raise ValueError("content_commitment_sha256 does not match report content")
        return self


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _endpoint_result(retrieved: object, *, endpoint: str) -> PDBeKBEndpointResult:
    return PDBeKBEndpointResult(
        state=ValidationState.UNRESOLVED,
        endpoint=endpoint,
        reason=getattr(retrieved, "terminal_error", None) or "response_unavailable",
        http_status=getattr(retrieved, "http_status", None),
        response_sha256=getattr(retrieved, "response_sha256", None),
        attempts=getattr(retrieved, "attempts", 0),
        cache_hit=getattr(retrieved, "cache_hit", False),
        request_log=getattr(retrieved, "request_log", []),
    )


def _resolved_endpoint_result(
    retrieved: object,
    *,
    endpoint: str,
    state: ValidationState,
    reason: str,
) -> PDBeKBEndpointResult:
    return PDBeKBEndpointResult(
        state=state,
        endpoint=endpoint,
        reason=reason,
        http_status=getattr(retrieved, "http_status", None),
        response_sha256=getattr(retrieved, "response_sha256", None),
        attempts=getattr(retrieved, "attempts", 0),
        cache_hit=getattr(retrieved, "cache_hit", False),
        request_log=getattr(retrieved, "request_log", []),
    )


def _successful_payload(retrieved: object) -> dict[str, object] | None:
    if (
        not getattr(retrieved, "response_received", False)
        or not getattr(retrieved, "payload_valid", False)
        or getattr(retrieved, "http_status", None) != 200
    ):
        return None
    payload = getattr(retrieved, "payload", None)
    return payload if isinstance(payload, dict) else None


def _parse_annotation_groups(
    payload: dict[str, object],
    accession: str,
) -> tuple[int, list[PDBeKBAnnotationGroup]]:
    root = payload.get(accession)
    if not isinstance(root, dict):
        raise KeyError(accession)
    length = root.get("length")
    if not isinstance(length, int) or isinstance(length, bool) or length < 1:
        raise ValueError("invalid sequence length")
    rows = root.get("data")
    if not isinstance(rows, list):
        raise ValueError("annotation data must be a list")

    groups: list[PDBeKBAnnotationGroup] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("annotation group must be an object")
        name = row.get("name")
        group_accession = row.get("accession")
        data_type = row.get("dataType")
        residues = row.get("residues")
        if not all(
            isinstance(value, str) and value
            for value in (name, group_accession, data_type)
        ):
            raise ValueError("annotation group identity is malformed")
        if not isinstance(residues, list):
            raise ValueError("annotation residues must be a list")

        covered_positions: set[int] = set()
        pdb_ids: set[str] = set()
        resource_urls: set[str] = set()
        confidence: set[str] = set()
        for residue in residues:
            if not isinstance(residue, dict):
                raise ValueError("annotation residue must be an object")
            start = residue.get("startIndex")
            end = residue.get("endIndex")
            if (
                not isinstance(start, int)
                or isinstance(start, bool)
                or not isinstance(end, int)
                or isinstance(end, bool)
                or start < 1
                or end < start
                or end > length
            ):
                raise ValueError("annotation residue range is invalid")
            covered_positions.update(range(start, end + 1))
            entries = residue.get("pdbEntries", [])
            if entries is None:
                entries = []
            if not isinstance(entries, list):
                raise ValueError("pdbEntries must be a list")
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ValueError("PDB entry must be an object")
                pdb_id = entry.get("pdbId")
                if not isinstance(pdb_id, str) or not _PDB_ID.fullmatch(pdb_id.upper()):
                    raise ValueError("PDB entry identifier is malformed")
                pdb_ids.add(pdb_id.upper())
            additional = residue.get("additionalData", {})
            if additional is None:
                additional = {}
            if not isinstance(additional, dict):
                raise ValueError("additionalData must be an object")
            resource_url = additional.get("resourceUrl")
            if isinstance(resource_url, str) and resource_url:
                resource_urls.add(resource_url)
            classification = additional.get("confidenceClassification")
            if isinstance(classification, str) and classification:
                confidence.add(classification)

        groups.append(
            PDBeKBAnnotationGroup(
                name=name,
                accession=group_accession,
                data_type=data_type,
                residue_range_count=len(residues),
                covered_sequence_position_count=len(covered_positions),
                pdb_ids=sorted(pdb_ids),
                resource_urls=sorted(resource_urls),
                confidence_classifications=sorted(confidence),
            )
        )
    return length, groups


def _parse_partners(payload: dict[str, object], accession: str) -> list[PDBeKBPartner]:
    root = payload.get(accession)
    if not isinstance(root, dict):
        raise KeyError(accession)
    rows = root.get("externalResources")
    if not isinstance(rows, list):
        raise ValueError("externalResources must be a list")
    partners: list[PDBeKBPartner] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("partner must be an object")
        values = (
            row.get("resourceName"),
            row.get("url"),
            row.get("annotationCategory"),
        )
        if not all(isinstance(value, str) and value for value in values):
            raise ValueError("partner identity is malformed")
        partners.append(
            PDBeKBPartner(
                resource_name=values[0],
                url=values[1],
                annotation_category=values[2],
            )
        )
    return sorted(
        partners,
        key=lambda item: (item.resource_name.casefold(), item.annotation_category, item.url),
    )


def fetch_pdbekb_enrichment(
    validator: IdentifierValidator,
    accession: str,
) -> PDBeKBEnrichment:
    normalized = accession.upper()
    if not _UNIPROT_ACCESSION.fullmatch(normalized):
        raise ValueError(f"invalid UniProt accession: {accession}")
    annotation_endpoint = PDBEKB_ANNOTATIONS.format(accession=normalized)
    partner_endpoint = PDBEKB_PARTNERS.format(accession=normalized)
    annotation_retrieved = validator._retrieve(annotation_endpoint)
    partner_retrieved = validator._retrieve(partner_endpoint)

    annotation_result = _endpoint_result(annotation_retrieved, endpoint=annotation_endpoint)
    sequence_length: int | None = None
    groups: list[PDBeKBAnnotationGroup] = []
    annotation_payload = _successful_payload(annotation_retrieved)
    if annotation_payload is not None:
        try:
            sequence_length, groups = _parse_annotation_groups(annotation_payload, normalized)
        except KeyError:
            annotation_result = _resolved_endpoint_result(
                annotation_retrieved,
                endpoint=annotation_endpoint,
                state=ValidationState.CONFLICT,
                reason="accession_missing_from_successful_response",
            )
        except ValueError:
            annotation_result = _resolved_endpoint_result(
                annotation_retrieved,
                endpoint=annotation_endpoint,
                state=ValidationState.UNRESOLVED,
                reason="malformed_annotation_payload",
            )
        else:
            annotation_result = _resolved_endpoint_result(
                annotation_retrieved,
                endpoint=annotation_endpoint,
                state=ValidationState.VALIDATED,
                reason="pdbekb_annotations_validated",
            )

    partner_result = _endpoint_result(partner_retrieved, endpoint=partner_endpoint)
    partners: list[PDBeKBPartner] = []
    partner_payload = _successful_payload(partner_retrieved)
    if partner_payload is not None:
        try:
            partners = _parse_partners(partner_payload, normalized)
        except (KeyError, ValueError):
            partner_result = _resolved_endpoint_result(
                partner_retrieved,
                endpoint=partner_endpoint,
                state=ValidationState.UNRESOLVED,
                reason="malformed_partner_payload",
            )
        else:
            partner_result = _resolved_endpoint_result(
                partner_retrieved,
                endpoint=partner_endpoint,
                state=ValidationState.VALIDATED,
                reason="pdbekb_partners_validated",
            )

    if annotation_result.state is ValidationState.CONFLICT:
        state = ValidationState.CONFLICT
    elif (
        annotation_result.state is ValidationState.VALIDATED
        and partner_result.state is ValidationState.VALIDATED
    ):
        state = ValidationState.VALIDATED
    else:
        state = ValidationState.UNRESOLVED
    return PDBeKBEnrichment(
        accession=normalized,
        state=state,
        sequence_length=sequence_length,
        annotation_result=annotation_result,
        partner_result=partner_result,
        annotation_groups=groups,
        partners=partners,
    )


def build_pdbekb_batch_report(
    enrichments: list[PDBeKBEnrichment],
    *,
    source_database: str | Path,
    source_database_schema_version: int,
    source_article_count: int,
    generated_at: datetime | None = None,
) -> PDBeKBBatchReport:
    ordered = sorted(enrichments, key=lambda item: item.accession)
    accessions = [item.accession for item in ordered]
    if len(accessions) != len(set(accessions)):
        raise ValueError("PDBe-KB enrichment accessions must be unique")
    groups = [group for item in ordered for group in item.annotation_groups]
    pdb_ids = {pdb_id for group in groups for pdb_id in group.pdb_ids}
    body = {
        "schema_version": "pdbekb-enrichment-batch-v1",
        "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(),
        "source_database_sha256": _sha256_file(Path(source_database)),
        "source_database_schema_version": source_database_schema_version,
        "source_article_count": source_article_count,
        "requested_accessions": accessions,
        "enrichments": [item.model_dump(mode="json") for item in ordered],
        "state_counts": dict(sorted(Counter(item.state.value for item in ordered).items())),
        "annotation_group_count": len(groups),
        "annotation_residue_range_count": sum(group.residue_range_count for group in groups),
        "partner_count": sum(len(item.partners) for item in ordered),
        "linked_pdb_id_count": len(pdb_ids),
    }
    return PDBeKBBatchReport(
        **body,
        content_commitment_sha256=_canonical_hash(body),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
