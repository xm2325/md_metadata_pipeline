from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import RequestAttempt, ValidationState
from .validation import IdentifierValidator

PDBE_KB_FUNPDBE = "https://www.ebi.ac.uk/pdbe/graph-api/pdb/funpdbe/{pdb_id}"


class PDBeKBAnnotation(BaseModel):
    """Conservative projection of one PDBe-KB/FunPDBe annotation record.

    The source API integrates annotations from multiple providers. Only values that are explicitly
    present in the response are projected. Unknown provider-specific fields remain represented by
    ``source_record_sha256`` rather than being guessed.
    """

    model_config = ConfigDict(extra="forbid")

    annotation_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    pdb_id: str = Field(pattern=r"^[0-9][A-Z0-9]{3}$")
    provider: str = Field(min_length=1)
    annotation_type: str = Field(min_length=1)
    label: str | None = None
    chain_id: str | None = None
    residue_start: int | None = Field(default=None, ge=1)
    residue_end: int | None = Field(default=None, ge=1)
    source_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PDBeKBEnrichment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["pdbe-kb-enrichment-v1"] = "pdbe-kb-enrichment-v1"
    pdb_id: str = Field(pattern=r"^[0-9][A-Z0-9]{3}$")
    state: ValidationState
    endpoint: str
    reason: str
    http_status: int | None = None
    response_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    attempts: int = Field(default=0, ge=0)
    cache_hit: bool = False
    request_log: list[RequestAttempt] = Field(default_factory=list)
    provider_counts: dict[str, int] = Field(default_factory=dict)
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


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 1 else None
    if isinstance(value, str) and value.isdigit():
        parsed = int(value)
        return parsed if parsed >= 1 else None
    if isinstance(value, dict):
        for key in ("residue_number", "author_residue_number", "index", "value"):
            parsed = _integer(value.get(key))
            if parsed is not None:
                return parsed
    return None


def _range_from_record(record: dict[str, Any]) -> tuple[int | None, int | None]:
    start = None
    end = None
    for key in ("residue_start", "startIndex", "start_index", "start", "begin"):
        start = _integer(record.get(key))
        if start is not None:
            break
    for key in ("residue_end", "endIndex", "end_index", "end", "stop"):
        end = _integer(record.get(key))
        if end is not None:
            break
    return start, end


def _range_records(record: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("residues", "ranges", "sites", "segments"):
        value = record.get(key)
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            return value
    start, end = _range_from_record(record)
    return [record] if start is not None or end is not None else []


def _project_record(pdb_id: str, record: dict[str, Any]) -> list[PDBeKBAnnotation]:
    provider = _first_text(record, ("origin", "provider", "source", "resource", "database"))
    annotation_type = _first_text(
        record,
        ("annotation_type", "annotationType", "data_type", "dataType", "type", "category"),
    )
    label = _first_text(record, ("label", "description", "name", "annotation", "term"))
    chain_id = _first_text(record, ("chain_id", "chainId", "chain", "auth_asym_id"))

    # Provider and type are the minimum semantic contract. A response can still be service-valid
    # while containing a provider-specific shape that this version deliberately does not project.
    if provider is None or annotation_type is None:
        return []

    source_sha = _canonical_sha256(record)
    ranges = _range_records(record)
    if not ranges:
        ranges = [{}]

    output: list[PDBeKBAnnotation] = []
    for index, item in enumerate(ranges):
        start, end = _range_from_record(item)
        item_chain = _first_text(item, ("chain_id", "chainId", "chain", "auth_asym_id"))
        annotation_key = {
            "pdb_id": pdb_id,
            "provider": provider,
            "annotation_type": annotation_type,
            "label": label,
            "chain_id": item_chain or chain_id,
            "residue_start": start,
            "residue_end": end,
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
                chain_id=item_chain or chain_id,
                residue_start=start,
                residue_end=end,
                source_record_sha256=source_sha,
            )
        )
    return output


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
        "raw_payload": retrieved.payload if retain_payload else None,
    }

    if not retrieved.response_received:
        return PDBeKBEnrichment(
            state=ValidationState.UNRESOLVED,
            reason=retrieved.terminal_error or "request_failed",
            **common,
        )
    if retrieved.http_status == 404:
        return PDBeKBEnrichment(
            state=ValidationState.CONFLICT,
            reason="successful_service_response_identifier_not_found",
            **common,
        )
    if retrieved.http_status != 200:
        return PDBeKBEnrichment(
            state=ValidationState.UNRESOLVED,
            reason="non_success_service_response",
            **common,
        )
    if not retrieved.payload_valid:
        return PDBeKBEnrichment(
            state=ValidationState.UNRESOLVED,
            reason=retrieved.terminal_error or "invalid_service_payload",
            **common,
        )

    payload = retrieved.payload or {}
    rows = payload.get(normalized, payload.get(rendered))
    if rows is None:
        return PDBeKBEnrichment(
            state=ValidationState.CONFLICT,
            reason="response_does_not_contain_requested_entry",
            **common,
        )
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        return PDBeKBEnrichment(
            state=ValidationState.UNRESOLVED,
            reason="malformed_pdbe_kb_payload",
            **common,
        )

    annotations = [item for row in rows for item in _project_record(rendered, row)]
    unique = {annotation.annotation_id: annotation for annotation in annotations}
    ordered = [unique[key] for key in sorted(unique)]
    provider_counts = dict(sorted(Counter(item.provider for item in ordered).items()))
    reason = (
        "pdbe_kb_annotations_projected"
        if ordered
        else "pdbe_kb_payload_available_no_supported_projection"
    )
    return PDBeKBEnrichment(
        state=ValidationState.VALIDATED,
        reason=reason,
        annotations=ordered,
        provider_counts=provider_counts,
        **common,
    )
