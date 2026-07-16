from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from . import user_agent
from .models import (
    MappingSegment,
    RequestAttempt,
    ValidationRecord,
    ValidationState,
)

PDBE_SUMMARY = "https://www.ebi.ac.uk/pdbe/api/pdb/entry/summary/{pdb_id}"
PDBE_UNIPROT = "https://www.ebi.ac.uk/pdbe/api/mappings/uniprot/{pdb_id}"
UNIPROT = "https://rest.uniprot.org/uniprotkb/{accession}.json"
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _hash_payload(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class ResponseCache:
    """File cache for public validation responses.

    Cache files contain endpoint, status, canonical payload hash, and JSON payload.
    Writes are atomic so interrupted runs do not leave partially written entries.
    """

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, endpoint: str) -> Path:
        key = hashlib.sha256(endpoint.encode("utf-8")).hexdigest()
        return self.directory / f"{key}.json"

    def load(self, endpoint: str) -> tuple[int, dict[str, Any], str] | None:
        path = self._path(endpoint)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("endpoint") != endpoint:
            return None
        response_payload = payload.get("payload")
        if not isinstance(response_payload, dict):
            return None
        digest = _hash_payload(response_payload)
        if digest != payload.get("response_sha256"):
            return None
        try:
            http_status = int(payload["http_status"])
        except (KeyError, TypeError, ValueError):
            return None
        if not 100 <= http_status <= 599:
            return None
        return http_status, response_payload, digest

    def store(self, endpoint: str, http_status: int, payload: dict[str, Any]) -> str:
        digest = _hash_payload(payload)
        record = {
            "endpoint": endpoint,
            "http_status": http_status,
            "response_sha256": digest,
            "payload": payload,
        }
        path = self._path(endpoint)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(record, sort_keys=True, indent=2),
                encoding="utf-8",
            )
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        return digest


@dataclass(frozen=True)
class _Retrieved:
    response_received: bool
    http_status: int | None
    payload: dict[str, Any] | None
    response_sha256: str | None
    attempts: int
    cache_hit: bool
    request_log: list[RequestAttempt]
    payload_valid: bool = True
    terminal_error: str | None = None


class IdentifierValidator:
    def __init__(
        self,
        client: httpx.Client | None = None,
        timeout: float = 15.0,
        *,
        retries: int = 2,
        backoff_seconds: float = 0.25,
        max_retry_after_seconds: float = 5.0,
        cache_dir: str | Path | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client or httpx.Client(
            timeout=timeout,
            headers={"User-Agent": user_agent("identifier-validation")},
        )
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self.max_retry_after_seconds = max_retry_after_seconds
        self.cache = ResponseCache(cache_dir) if cache_dir is not None else None
        self.sleep = sleep

    def _retrieve(self, endpoint: str) -> _Retrieved:
        if self.cache is not None:
            cached = self.cache.load(endpoint)
            if cached is not None:
                status, payload, digest = cached
                return _Retrieved(
                    response_received=True,
                    http_status=status,
                    payload=payload,
                    response_sha256=digest,
                    attempts=0,
                    cache_hit=True,
                    request_log=[RequestAttempt(attempt=0, outcome="cache", http_status=status)],
                )

        request_log: list[RequestAttempt] = []
        for attempt in range(1, self.retries + 2):
            try:
                response = self.client.get(endpoint)
            except httpx.HTTPError as exc:
                request_log.append(
                    RequestAttempt(
                        attempt=attempt,
                        outcome="network_error",
                        error_type=type(exc).__name__,
                    )
                )
                if attempt <= self.retries:
                    self.sleep(self.backoff_seconds * (2 ** (attempt - 1)))
                    continue
                return _Retrieved(
                    response_received=False,
                    http_status=None,
                    payload=None,
                    response_sha256=None,
                    attempts=attempt,
                    cache_hit=False,
                    request_log=request_log,
                    terminal_error=f"network_error:{type(exc).__name__}",
                )

            retry_after: float | None = None
            if response.status_code in _RETRYABLE_STATUS and attempt <= self.retries:
                header = response.headers.get("Retry-After")
                try:
                    retry_after = float(header) if header is not None else None
                except ValueError:
                    retry_after = None
                delay = (
                    retry_after
                    if retry_after is not None
                    else self.backoff_seconds * (2 ** (attempt - 1))
                )
                delay = min(delay, self.max_retry_after_seconds)
                request_log.append(
                    RequestAttempt(
                        attempt=attempt,
                        outcome="response",
                        http_status=response.status_code,
                        retry_after_seconds=delay,
                    )
                )
                self.sleep(delay)
                continue

            request_log.append(
                RequestAttempt(
                    attempt=attempt,
                    outcome="response",
                    http_status=response.status_code,
                )
            )
            try:
                payload = response.json()
            except ValueError:
                return _Retrieved(
                    response_received=True,
                    http_status=response.status_code,
                    payload=None,
                    response_sha256=hashlib.sha256(response.content).hexdigest(),
                    attempts=attempt,
                    cache_hit=False,
                    request_log=request_log,
                    payload_valid=False,
                    terminal_error="invalid_json_response",
                )
            if not isinstance(payload, dict):
                return _Retrieved(
                    response_received=True,
                    http_status=response.status_code,
                    payload=None,
                    response_sha256=hashlib.sha256(response.content).hexdigest(),
                    attempts=attempt,
                    cache_hit=False,
                    request_log=request_log,
                    payload_valid=False,
                    terminal_error=f"unexpected_json_type:{type(payload).__name__}",
                )
            digest = _hash_payload(payload)
            if self.cache is not None and response.status_code == 200:
                digest = self.cache.store(endpoint, response.status_code, payload)
            return _Retrieved(
                response_received=True,
                http_status=response.status_code,
                payload=payload,
                response_sha256=digest,
                attempts=attempt,
                cache_hit=False,
                request_log=request_log,
            )
        raise AssertionError("unreachable retrieval state")

    @staticmethod
    def _record(
        *,
        identifier_type: str,
        query: dict[str, str],
        state: ValidationState,
        endpoint: str,
        reason: str,
        retrieved: _Retrieved,
        mapping_segments: list[MappingSegment] | None = None,
    ) -> ValidationRecord:
        return ValidationRecord(
            identifier_type=identifier_type,
            query=query,
            state=state,
            endpoint=endpoint,
            http_status=retrieved.http_status,
            response_sha256=retrieved.response_sha256,
            reason=reason,
            payload=retrieved.payload,
            attempts=retrieved.attempts,
            cache_hit=retrieved.cache_hit,
            request_log=retrieved.request_log,
            mapping_segments=mapping_segments or [],
        )

    def validate_pdb(self, pdb_id: str) -> ValidationRecord:
        pdb_id = pdb_id.lower()
        endpoint = PDBE_SUMMARY.format(pdb_id=pdb_id)
        query = {"pdb_id": pdb_id.upper()}
        retrieved = self._retrieve(endpoint)
        if not retrieved.response_received:
            return self._record(
                identifier_type="pdb",
                query=query,
                state=ValidationState.UNRESOLVED,
                endpoint=endpoint,
                reason=retrieved.terminal_error or "request_failed",
                retrieved=retrieved,
            )
        if retrieved.http_status == 404:
            return self._record(
                identifier_type="pdb",
                query=query,
                state=ValidationState.CONFLICT,
                endpoint=endpoint,
                reason="successful_service_response_identifier_not_found",
                retrieved=retrieved,
            )
        if retrieved.http_status != 200:
            return self._record(
                identifier_type="pdb",
                query=query,
                state=ValidationState.UNRESOLVED,
                endpoint=endpoint,
                reason="non_success_service_response",
                retrieved=retrieved,
            )
        if not retrieved.payload_valid:
            return self._record(
                identifier_type="pdb",
                query=query,
                state=ValidationState.UNRESOLVED,
                endpoint=endpoint,
                reason=retrieved.terminal_error or "invalid_service_payload",
                retrieved=retrieved,
            )
        payload = retrieved.payload or {}
        if pdb_id not in payload:
            state = ValidationState.CONFLICT
            reason = "response_does_not_contain_requested_entry"
        elif not isinstance(payload[pdb_id], list) or not payload[pdb_id] or not all(
            isinstance(item, dict) for item in payload[pdb_id]
        ):
            state = ValidationState.UNRESOLVED
            reason = "malformed_pdb_summary_payload"
        else:
            state = ValidationState.VALIDATED
            reason = "entry_exists"
        return self._record(
            identifier_type="pdb",
            query=query,
            state=state,
            endpoint=endpoint,
            reason=reason,
            retrieved=retrieved,
        )

    def validate_uniprot(self, accession: str) -> ValidationRecord:
        endpoint = UNIPROT.format(accession=accession)
        query = {"accession": accession}
        retrieved = self._retrieve(endpoint)
        if not retrieved.response_received:
            return self._record(
                identifier_type="uniprot",
                query=query,
                state=ValidationState.UNRESOLVED,
                endpoint=endpoint,
                reason=retrieved.terminal_error or "request_failed",
                retrieved=retrieved,
            )
        if retrieved.http_status == 404:
            return self._record(
                identifier_type="uniprot",
                query=query,
                state=ValidationState.CONFLICT,
                endpoint=endpoint,
                reason="successful_service_response_identifier_not_found",
                retrieved=retrieved,
            )
        if retrieved.http_status != 200:
            return self._record(
                identifier_type="uniprot",
                query=query,
                state=ValidationState.UNRESOLVED,
                endpoint=endpoint,
                reason="non_success_service_response",
                retrieved=retrieved,
            )
        if not retrieved.payload_valid:
            return self._record(
                identifier_type="uniprot",
                query=query,
                state=ValidationState.UNRESOLVED,
                endpoint=endpoint,
                reason=retrieved.terminal_error or "invalid_service_payload",
                retrieved=retrieved,
            )
        returned = (retrieved.payload or {}).get("primaryAccession")
        if not isinstance(returned, str):
            return self._record(
                identifier_type="uniprot",
                query=query,
                state=ValidationState.UNRESOLVED,
                endpoint=endpoint,
                reason="malformed_uniprot_payload",
                retrieved=retrieved,
            )
        state = ValidationState.VALIDATED if returned == accession else ValidationState.CONFLICT
        return self._record(
            identifier_type="uniprot",
            query=query,
            state=state,
            endpoint=endpoint,
            reason=(
                "accession_matches"
                if state is ValidationState.VALIDATED
                else "accession_mismatch"
            ),
            retrieved=retrieved,
        )

    @staticmethod
    def _mapping_segments(
        pdb_id: str, accession: str, mappings: list[dict[str, Any]]
    ) -> list[MappingSegment]:
        segments = []
        for item in mappings:
            start = item.get("start") or {}
            end = item.get("end") or {}
            segments.append(
                MappingSegment(
                    pdb_id=pdb_id.upper(),
                    uniprot_accession=accession,
                    chain_id=str(item.get("chain_id") or item.get("struct_asym_id") or ""),
                    pdb_start=start.get("residue_number"),
                    pdb_end=end.get("residue_number"),
                    uniprot_start=item.get("unp_start"),
                    uniprot_end=item.get("unp_end"),
                )
            )
        return segments

    def validate_mapping(
        self,
        pdb_id: str,
        accession: str,
        chain_id: str | None = None,
    ) -> ValidationRecord:
        pdb_id = pdb_id.lower()
        endpoint = PDBE_UNIPROT.format(pdb_id=pdb_id)
        query = {
            "pdb_id": pdb_id.upper(),
            "accession": accession,
            "chain_id": chain_id or "",
        }
        retrieved = self._retrieve(endpoint)
        if (
            not retrieved.response_received
            or not retrieved.payload_valid
            or retrieved.http_status != 200
        ):
            return self._record(
                identifier_type="pdb_uniprot_mapping",
                query=query,
                state=ValidationState.UNRESOLVED,
                endpoint=endpoint,
                reason=retrieved.terminal_error or "mapping_response_unavailable",
                retrieved=retrieved,
            )
        payload = retrieved.payload or {}
        pdb_payload = payload.get(pdb_id)
        if pdb_payload is not None and not isinstance(pdb_payload, dict):
            return self._record(
                identifier_type="pdb_uniprot_mapping",
                query=query,
                state=ValidationState.UNRESOLVED,
                endpoint=endpoint,
                reason="malformed_mapping_payload",
                retrieved=retrieved,
            )
        uniprot = (pdb_payload or {}).get("UniProt", {})
        if not isinstance(uniprot, dict):
            return self._record(
                identifier_type="pdb_uniprot_mapping",
                query=query,
                state=ValidationState.UNRESOLVED,
                endpoint=endpoint,
                reason="malformed_mapping_payload",
                retrieved=retrieved,
            )
        accession_payload = uniprot.get(accession)
        if accession_payload is not None and not isinstance(accession_payload, dict):
            return self._record(
                identifier_type="pdb_uniprot_mapping",
                query=query,
                state=ValidationState.UNRESOLVED,
                endpoint=endpoint,
                reason="malformed_mapping_payload",
                retrieved=retrieved,
            )
        mappings = (accession_payload or {}).get("mappings", [])
        if not isinstance(mappings, list) or not all(
            isinstance(item, dict) for item in mappings
        ):
            return self._record(
                identifier_type="pdb_uniprot_mapping",
                query=query,
                state=ValidationState.UNRESOLVED,
                endpoint=endpoint,
                reason="malformed_mapping_payload",
                retrieved=retrieved,
            )
        segments = self._mapping_segments(pdb_id, accession, mappings)
        if not segments:
            state = ValidationState.CONFLICT
            reason = "successful_mapping_response_relation_absent"
        elif chain_id and not any(segment.chain_id == chain_id for segment in segments):
            state = ValidationState.CONFLICT
            reason = "accession_present_but_chain_absent"
        else:
            state = ValidationState.VALIDATED
            reason = "mapping_supported"
        return self._record(
            identifier_type="pdb_uniprot_mapping",
            query=query,
            state=state,
            endpoint=endpoint,
            reason=reason,
            retrieved=retrieved,
            mapping_segments=segments,
        )


def summarize_validation(records: list[ValidationRecord]) -> dict[str, Any]:
    states = Counter(record.state.value for record in records)
    types = Counter(record.identifier_type for record in records)
    reasons = Counter(record.reason for record in records)
    return {
        "record_count": len(records),
        "state_counts": dict(sorted(states.items())),
        "identifier_type_counts": dict(sorted(types.items())),
        "reason_counts": dict(sorted(reasons.items())),
        "cache_hit_count": sum(record.cache_hit for record in records),
        "total_network_attempts": sum(record.attempts for record in records),
        "mapping_segment_count": sum(len(record.mapping_segments) for record in records),
        "unresolved_or_conflict_count": sum(
            record.state in {ValidationState.UNRESOLVED, ValidationState.CONFLICT}
            for record in records
        ),
    }
