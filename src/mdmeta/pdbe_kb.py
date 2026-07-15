from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any, Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field

from .models import RequestAttempt, ValidationState
from .validation import IdentifierValidator

PDBE_KB_FUNPDBE = "https://www.ebi.ac.uk/pdbe/graph-api/pdb/funpdbe/{pdb_id}"
PDBE_KB_ANNOTATIONS = (
    "https://www.ebi.ac.uk/pdbe/graph-api/pdb/funpdbe_annotation/{origin}/{pdb_id}"
)


class PDBeKBProviderCatalogue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1)
    labels: list[str] = Field(default_factory=list)
    evidence_codes: list[str] = Field(default_factory=list)
    release_date: str | None = None
    url: str | None = None


class PDBeKBProviderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1)
    endpoint: str
    state: ValidationState
    reason: str
    http_status: int | None = None
    response_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    attempts: int = Field(default=0, ge=0)
    cache_hit: bool = False
    request_log: list[RequestAttempt] = Field(default_factory=list)
    annotation_count: int = Field(default=0, ge=0)


class PDBeKBAnnotation(BaseModel):
    """Conservative projection of one PDBe-KB/FunPDBe annotation or site residue."""

    model_config = ConfigDict(extra="forbid")

    annotation_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    pdb_id: str = Field(pattern=r"^[0-9][A-Z0-9]{3}$")
    provider: str = Field(min_length=1)
    annotation_type: str = Field(min_length=1)
    label: str | None = None
    chain_id: str | None = None
    residue_start: int | None = Field(default=None, ge=1)
    residue_end: int | None = Field(default=None, ge=1)
    author_residue_number: int | None = None
    author_insertion_code: str | None = None
    entity_id: int | None = Field(default=None, ge=1)
    raw_score: float | str | None = None
    confidence_score: float | str | None = None
    confidence_classification: str | None = None
    source_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PDBeKBEnrichment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["pdbe-kb-enrichment-v2"] = "pdbe-kb-enrichment-v2"
    pdb_id: str = Field(pattern=r"^[0-9][A-Z0-9]{3}$")
    state: ValidationState
    endpoint: str
    reason: str
    http_status: int | None = None
    response_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    attempts: int = Field(default=0, ge=0)
    cache_hit: bool = False
    request_log: list[RequestAttempt] = Field(default_factory=list)
    provider_catalogue: list[PDBeKBProviderCatalogue] = Field(default_factory=list)
    provider_requests: list[PDBeKBProviderRequest] = Field(default_factory=list)
    provider_counts: dict[str, int] = Field(default_factory=dict)
    provider_state_counts: dict[str, int] = Field(default_factory=dict)
    annotations: list[PDBeKBAnnotation] = Field(default_factory=list)
    raw_payload: dict[str, Any] | None = None


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _first_text(record: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _integer(value: Any, *, positive: bool = True) -> int | None:
    if isinstance(value, bool):
        return None
    parsed: int | None = None
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        stripped = value.strip()
        if stripped.lstrip("-").isdigit():
            parsed = int(stripped)
    elif isinstance(value, dict):
        for key in (
            "residue_number",
            "author_residue_number",
            "entity_id",
            "index",
            "value",
        ):
            parsed = _integer(value.get(key), positive=positive)
            if parsed is not None:
                return parsed
    if parsed is None:
        return None
    return parsed if not positive or parsed >= 1 else None


def _number_or_text(value: Any) -> float | str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _range_from_record(record: dict[str, Any]) -> tuple[int | None, int | None]:
    start = None
    end = None
    for key in (
        "residue_start",
        "startIndex",
        "start_index",
        "start",
        "begin",
        "residue_number",
    ):
        start = _integer(record.get(key))
        if start is not None:
            break
    for key in (
        "residue_end",
        "endIndex",
        "end_index",
        "end",
        "stop",
        "residue_number",
    ):
        end = _integer(record.get(key))
        if end is not None:
            break
    return start, end


def _site_records(annotation: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("site_residues", "residues", "ranges", "sites", "segments"):
        value = annotation.get(key)
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            return value
    start, end = _range_from_record(annotation)
    return [annotation] if start is not None or end is not None else []


def _project_annotation(
    pdb_id: str,
    provider: str,
    annotation: dict[str, Any],
) -> list[PDBeKBAnnotation]:
    label = _first_text(annotation, ("label", "description", "name", "annotation", "term"))
    annotation_type = _first_text(
        annotation,
        ("annotation_type", "annotationType", "data_type", "dataType", "type", "category"),
    ) or "funpdbe_annotation"
    annotation_chain = _first_text(
        annotation, ("chain_id", "chainId", "chain", "auth_asym_id")
    )
    source_sha = _canonical_sha256(annotation)
    sites = _site_records(annotation) or [{}]

    output: list[PDBeKBAnnotation] = []
    for index, site in enumerate(sites):
        start, end = _range_from_record(site)
        chain_id = _first_text(site, ("chain_id", "chainId", "chain", "auth_asym_id"))
        author_residue_number = _integer(
            site.get("author_residue_number") or site.get("author_residue_id"),
            positive=False,
        )
        entity_id = _integer(site.get("entity_id") or site.get("entityId"))
        insertion_code = _first_text(
            site,
            ("author_insertion_code", "insertion_code", "pdb_ins_code"),
        )
        raw_score = _number_or_text(site.get("raw_score"))
        confidence_score = _number_or_text(site.get("confidence_score"))
        confidence_classification = _first_text(
            site,
            ("confidence_classification", "confidence_label", "classification"),
        )
        annotation_key = {
            "pdb_id": pdb_id,
            "provider": provider,
            "annotation_type": annotation_type,
            "label": label,
            "chain_id": chain_id or annotation_chain,
            "residue_start": start,
            "residue_end": end,
            "author_residue_number": author_residue_number,
            "author_insertion_code": insertion_code,
            "entity_id": entity_id,
            "raw_score": raw_score,
            "confidence_score": confidence_score,
            "confidence_classification": confidence_classification,
            "source_sha256": source_sha,
            "index": index,
        }
        output.append(
            PDBeKBAnnotation(
                annotation_id=_canonical_sha256(annotation_key)[:16],
                pdb_id=pdb_id,
                provider=provider,
                annotation_type=annotation_type,
                label=label,
                chain_id=chain_id or annotation_chain,
                residue_start=start,
                residue_end=end,
                author_residue_number=author_residue_number,
                author_insertion_code=insertion_code,
                entity_id=entity_id,
                raw_score=raw_score,
                confidence_score=confidence_score,
                confidence_classification=confidence_classification,
                source_record_sha256=source_sha,
            )
        )
    return output


def _catalogue_row(row: dict[str, Any]) -> PDBeKBProviderCatalogue | None:
    provider = _first_text(row, ("origin", "provider", "source", "resource", "database"))
    if provider is None:
        return None
    return PDBeKBProviderCatalogue(
        provider=provider,
        labels=_text_list(row.get("labels")),
        evidence_codes=_text_list(row.get("evidence_codes")),
        release_date=_first_text(row, ("release_date", "releaseDate")),
        url=_first_text(row, ("url", "source_url")),
    )


def _provider_request(
    provider: str,
    endpoint: str,
    retrieved: Any,
    *,
    state: ValidationState,
    reason: str,
    annotation_count: int = 0,
) -> PDBeKBProviderRequest:
    return PDBeKBProviderRequest(
        provider=provider,
        endpoint=endpoint,
        state=state,
        reason=reason,
        http_status=retrieved.http_status,
        response_sha256=retrieved.response_sha256,
        attempts=retrieved.attempts,
        cache_hit=retrieved.cache_hit,
        request_log=retrieved.request_log,
        annotation_count=annotation_count,
    )


def fetch_pdbe_kb_annotations(
    validator: IdentifierValidator,
    pdb_id: str,
    *,
    retain_payload: bool = False,
) -> PDBeKBEnrichment:
    normalized = pdb_id.lower()
    rendered = normalized.upper()
    if len(normalized) != 4 or not normalized[0].isdigit() or not normalized.isalnum():
        raise ValueError(f"invalid PDB identifier: {pdb_id}")

    endpoint = PDBE_KB_FUNPDBE.format(pdb_id=normalized)
    retrieved = validator._retrieve(endpoint)  # reuse audited cache/retry semantics
    common = {
        "pdb_id": rendered,
        "endpoint": endpoint,
        "http_status": retrieved.http_status,
        "response_sha256": retrieved.response_sha256,
        "attempts": retrieved.attempts,
        "cache_hit": retrieved.cache_hit,
        "request_log": retrieved.request_log,
    }

    if not retrieved.response_received:
        return PDBeKBEnrichment(
            state=ValidationState.UNRESOLVED,
            reason=retrieved.terminal_error or "request_failed",
            raw_payload=retrieved.payload if retain_payload else None,
            **common,
        )
    if retrieved.http_status == 404:
        return PDBeKBEnrichment(
            state=ValidationState.CONFLICT,
            reason="successful_service_response_identifier_not_found",
            raw_payload=retrieved.payload if retain_payload else None,
            **common,
        )
    if retrieved.http_status != 200:
        return PDBeKBEnrichment(
            state=ValidationState.UNRESOLVED,
            reason="non_success_service_response",
            raw_payload=retrieved.payload if retain_payload else None,
            **common,
        )
    if not retrieved.payload_valid:
        return PDBeKBEnrichment(
            state=ValidationState.UNRESOLVED,
            reason=retrieved.terminal_error or "invalid_service_payload",
            raw_payload=retrieved.payload if retain_payload else None,
            **common,
        )

    catalogue_payload = retrieved.payload or {}
    rows = catalogue_payload.get(normalized, catalogue_payload.get(rendered))
    if rows is None:
        return PDBeKBEnrichment(
            state=ValidationState.CONFLICT,
            reason="response_does_not_contain_requested_entry",
            raw_payload=catalogue_payload if retain_payload else None,
            **common,
        )
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        return PDBeKBEnrichment(
            state=ValidationState.UNRESOLVED,
            reason="malformed_pdbe_kb_catalogue_payload",
            raw_payload=catalogue_payload if retain_payload else None,
            **common,
        )

    catalogue = [item for row in rows if (item := _catalogue_row(row)) is not None]
    raw_provider_payloads: dict[str, Any] = {}
    provider_requests: list[PDBeKBProviderRequest] = []
    annotations: list[PDBeKBAnnotation] = []

    for provider_row in catalogue:
        provider = provider_row.provider
        provider_endpoint = PDBE_KB_ANNOTATIONS.format(
            origin=quote(provider, safe=""),
            pdb_id=normalized,
        )
        provider_retrieved = validator._retrieve(provider_endpoint)
        if retain_payload:
            raw_provider_payloads[provider] = provider_retrieved.payload

        if not provider_retrieved.response_received:
            provider_requests.append(
                _provider_request(
                    provider,
                    provider_endpoint,
                    provider_retrieved,
                    state=ValidationState.UNRESOLVED,
                    reason=provider_retrieved.terminal_error or "request_failed",
                )
            )
            continue
        if provider_retrieved.http_status == 404:
            provider_requests.append(
                _provider_request(
                    provider,
                    provider_endpoint,
                    provider_retrieved,
                    state=ValidationState.CONFLICT,
                    reason="provider_catalogue_relation_not_found",
                )
            )
            continue
        if provider_retrieved.http_status != 200 or not provider_retrieved.payload_valid:
            provider_requests.append(
                _provider_request(
                    provider,
                    provider_endpoint,
                    provider_retrieved,
                    state=ValidationState.UNRESOLVED,
                    reason=(
                        provider_retrieved.terminal_error
                        or "provider_annotation_response_unavailable"
                    ),
                )
            )
            continue

        provider_payload = provider_retrieved.payload or {}
        provider_rows = provider_payload.get(normalized, provider_payload.get(rendered))
        if not isinstance(provider_rows, list) or not all(
            isinstance(row, dict) for row in provider_rows
        ):
            provider_requests.append(
                _provider_request(
                    provider,
                    provider_endpoint,
                    provider_retrieved,
                    state=ValidationState.UNRESOLVED,
                    reason="malformed_provider_annotation_payload",
                )
            )
            continue

        projected: list[PDBeKBAnnotation] = []
        for provider_record in provider_rows:
            annotation_rows = provider_record.get("annotations", [])
            if annotation_rows is None:
                annotation_rows = []
            if not isinstance(annotation_rows, list) or not all(
                isinstance(row, dict) for row in annotation_rows
            ):
                projected = []
                provider_requests.append(
                    _provider_request(
                        provider,
                        provider_endpoint,
                        provider_retrieved,
                        state=ValidationState.UNRESOLVED,
                        reason="malformed_provider_annotation_payload",
                    )
                )
                break
            for annotation in annotation_rows:
                projected.extend(_project_annotation(rendered, provider, annotation))
        else:
            annotations.extend(projected)
            provider_requests.append(
                _provider_request(
                    provider,
                    provider_endpoint,
                    provider_retrieved,
                    state=ValidationState.VALIDATED,
                    reason=(
                        "provider_annotations_projected"
                        if projected
                        else "provider_response_contains_no_annotations"
                    ),
                    annotation_count=len(projected),
                )
            )

    unique = {annotation.annotation_id: annotation for annotation in annotations}
    ordered = [unique[key] for key in sorted(unique)]
    provider_counts = dict(sorted(Counter(item.provider for item in ordered).items()))
    provider_state_counts = dict(
        sorted(Counter(item.state.value for item in provider_requests).items())
    )
    incomplete = any(item.state is not ValidationState.VALIDATED for item in provider_requests)
    if incomplete:
        state = ValidationState.UNRESOLVED
        reason = "pdbe_kb_provider_retrieval_incomplete"
    elif ordered:
        state = ValidationState.VALIDATED
        reason = "pdbe_kb_annotations_projected"
    elif catalogue:
        state = ValidationState.VALIDATED
        reason = "pdbe_kb_providers_returned_no_annotations"
    else:
        state = ValidationState.VALIDATED
        reason = "pdbe_kb_catalogue_contains_no_supported_providers"

    raw_payload = None
    if retain_payload:
        raw_payload = {
            "catalogue": catalogue_payload,
            "provider_annotations": raw_provider_payloads,
        }
    return PDBeKBEnrichment(
        state=state,
        reason=reason,
        provider_catalogue=catalogue,
        provider_requests=provider_requests,
        annotations=ordered,
        provider_counts=provider_counts,
        provider_state_counts=provider_state_counts,
        raw_payload=raw_payload,
        **common,
    )
