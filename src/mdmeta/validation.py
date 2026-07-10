from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx

from .models import ValidationRecord, ValidationState

PDBE_SUMMARY = "https://www.ebi.ac.uk/pdbe/api/pdb/entry/summary/{pdb_id}"
PDBE_UNIPROT = "https://www.ebi.ac.uk/pdbe/api/mappings/uniprot/{pdb_id}"
UNIPROT = "https://rest.uniprot.org/uniprotkb/{accession}.json"


def _hash_payload(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class IdentifierValidator:
    def __init__(self, client: httpx.Client | None = None, timeout: float = 15.0) -> None:
        self.client = client or httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "md-metadata-pipeline/0.3"},
        )

    def validate_pdb(self, pdb_id: str) -> ValidationRecord:
        pdb_id = pdb_id.lower()
        endpoint = PDBE_SUMMARY.format(pdb_id=pdb_id)
        try:
            response = self.client.get(endpoint)
        except httpx.HTTPError as exc:
            return ValidationRecord(
                identifier_type="pdb",
                query={"pdb_id": pdb_id.upper()},
                state=ValidationState.UNRESOLVED,
                endpoint=endpoint,
                reason=f"network_error:{type(exc).__name__}",
            )
        if response.status_code == 404:
            return ValidationRecord(
                identifier_type="pdb",
                query={"pdb_id": pdb_id.upper()},
                state=ValidationState.CONFLICT,
                endpoint=endpoint,
                http_status=404,
                reason="successful_service_response_identifier_not_found",
            )
        if response.status_code != 200:
            return ValidationRecord(
                identifier_type="pdb",
                query={"pdb_id": pdb_id.upper()},
                state=ValidationState.UNRESOLVED,
                endpoint=endpoint,
                http_status=response.status_code,
                reason="non_success_service_response",
            )
        payload = response.json()
        response_hash = _hash_payload(payload)
        if pdb_id not in payload:
            return ValidationRecord(
                identifier_type="pdb",
                query={"pdb_id": pdb_id.upper()},
                state=ValidationState.CONFLICT,
                endpoint=endpoint,
                http_status=200,
                response_sha256=response_hash,
                reason="response_does_not_contain_requested_entry",
                payload=payload,
            )
        return ValidationRecord(
            identifier_type="pdb",
            query={"pdb_id": pdb_id.upper()},
            state=ValidationState.VALIDATED,
            endpoint=endpoint,
            http_status=200,
            response_sha256=response_hash,
            reason="entry_exists",
            payload=payload,
        )

    def validate_uniprot(self, accession: str) -> ValidationRecord:
        endpoint = UNIPROT.format(accession=accession)
        try:
            response = self.client.get(endpoint)
        except httpx.HTTPError as exc:
            return ValidationRecord(
                identifier_type="uniprot",
                query={"accession": accession},
                state=ValidationState.UNRESOLVED,
                endpoint=endpoint,
                reason=f"network_error:{type(exc).__name__}",
            )
        if response.status_code == 404:
            return ValidationRecord(
                identifier_type="uniprot",
                query={"accession": accession},
                state=ValidationState.CONFLICT,
                endpoint=endpoint,
                http_status=404,
                reason="successful_service_response_identifier_not_found",
            )
        if response.status_code != 200:
            return ValidationRecord(
                identifier_type="uniprot",
                query={"accession": accession},
                state=ValidationState.UNRESOLVED,
                endpoint=endpoint,
                http_status=response.status_code,
                reason="non_success_service_response",
            )
        payload = response.json()
        returned = payload.get("primaryAccession")
        state = ValidationState.VALIDATED if returned == accession else ValidationState.CONFLICT
        return ValidationRecord(
            identifier_type="uniprot",
            query={"accession": accession},
            state=state,
            endpoint=endpoint,
            http_status=200,
            response_sha256=_hash_payload(payload),
            reason="accession_matches" if state is ValidationState.VALIDATED else "accession_mismatch",
            payload=payload,
        )

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
        try:
            response = self.client.get(endpoint)
        except httpx.HTTPError as exc:
            return ValidationRecord(
                identifier_type="pdb_uniprot_mapping",
                query=query,
                state=ValidationState.UNRESOLVED,
                endpoint=endpoint,
                reason=f"network_error:{type(exc).__name__}",
            )
        if response.status_code != 200:
            return ValidationRecord(
                identifier_type="pdb_uniprot_mapping",
                query=query,
                state=ValidationState.UNRESOLVED,
                endpoint=endpoint,
                http_status=response.status_code,
                reason="mapping_response_unavailable",
            )
        payload = response.json()
        uniprot = payload.get(pdb_id, {}).get("UniProt", {})
        mappings = uniprot.get(accession, {}).get("mappings", [])
        if not mappings:
            state = ValidationState.CONFLICT
            reason = "successful_mapping_response_relation_absent"
        elif chain_id and not any(item.get("chain_id") == chain_id for item in mappings):
            state = ValidationState.CONFLICT
            reason = "accession_present_but_chain_absent"
        else:
            state = ValidationState.VALIDATED
            reason = "mapping_supported"
        return ValidationRecord(
            identifier_type="pdb_uniprot_mapping",
            query=query,
            state=state,
            endpoint=endpoint,
            http_status=200,
            response_sha256=_hash_payload(payload),
            reason=reason,
            payload=payload,
        )
