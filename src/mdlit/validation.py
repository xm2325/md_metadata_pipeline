from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .clients import PDBeClient, UniProtClient
from .models import MDRecord, StructureSequenceMapping, ValidationEvent

KNOWN_PROGRAMS = {"GROMACS", "AMBER", "NAMD", "OpenMM", "CHARMM", "DESMOND"}
KNOWN_ENSEMBLES = {"NPT", "NVT", "NVE"}


def _event(
    validator: str,
    status: str,
    message: str,
    source_uri: str | None = None,
    response_sha256: str | None = None,
) -> ValidationEvent:
    return ValidationEvent(
        validator=validator,
        status=status,
        message=message,
        checked_at=datetime.now(timezone.utc),
        source_uri=source_uri,
        response_sha256=response_sha256,
    )


def validate_semantics(record: MDRecord) -> MDRecord:
    for fact in record.facts:
        if fact.field_name == "program":
            status = "validated" if str(fact.normalized_value) in KNOWN_PROGRAMS else "unresolved"
            fact.validation.append(
                _event(
                    "controlled_program_list_v1", status, f"Program value: {fact.normalized_value}"
                )
            )
        elif fact.field_name == "ensemble":
            status = "validated" if str(fact.normalized_value) in KNOWN_ENSEMBLES else "invalid"
            fact.validation.append(
                _event("ensemble_vocabulary_v1", status, f"Ensemble value: {fact.normalized_value}")
            )
        elif fact.field_name == "temperature":
            value = float(fact.normalized_value)
            status = "validated" if 0 < value <= 1000 else "invalid"
            fact.validation.append(_event("temperature_range_v1", status, f"Temperature={value} K"))
        elif fact.field_name == "time_step":
            value = float(fact.normalized_value)
            status = "validated" if 0 < value <= 0.1 else "unresolved"
            fact.validation.append(_event("time_step_sanity_v1", status, f"Time step={value} ps"))
        elif fact.field_name == "simulation_duration":
            value = float(fact.normalized_value)
            status = "validated" if value > 0 else "invalid"
            fact.validation.append(_event("duration_positive_v1", status, f"Duration={value} ns"))
        elif fact.field_name == "replicates":
            value = int(fact.normalized_value)
            status = "validated" if value >= 1 else "invalid"
            fact.validation.append(_event("replicate_count_v1", status, f"Replicates={value}"))
    for event in record.protocol_events:
        if event.duration_value is not None and float(event.duration_value) <= 0:
            event.validation.append(
                _event("protocol_duration_positive_v1", "invalid", "Duration must be positive")
            )
        if event.phase == "production" and event.duration_value is None:
            event.validation.append(
                _event(
                    "production_duration_presence_v1",
                    "unresolved",
                    "Production event has no extracted duration",
                )
            )
        if event.phase in {"equilibration", "production"} and event.ensemble is None:
            event.validation.append(
                _event(
                    "protocol_ensemble_presence_v1",
                    "unresolved",
                    f"{event.phase} event has no extracted ensemble",
                )
            )
    return record


def _extract_mappings(pdb_id: str, data: dict[str, Any]) -> list[StructureSequenceMapping]:
    root = data.get(pdb_id.lower()) or data.get(pdb_id.upper()) or {}
    uniprot = root.get("UniProt", {}) if isinstance(root, dict) else {}
    mappings: list[StructureSequenceMapping] = []
    for accession, entry in uniprot.items():
        for mapping in entry.get("mappings", []):
            start = mapping.get("start", {}) or {}
            end = mapping.get("end", {}) or {}
            mappings.append(
                StructureSequenceMapping(
                    pdb_id=pdb_id.upper(),
                    uniprot_accession=accession.upper(),
                    chain_id=str(mapping.get("chain_id") or mapping.get("struct_asym_id") or ""),
                    pdb_start=start.get("residue_number"),
                    pdb_end=end.get("residue_number"),
                    uniprot_start=mapping.get("unp_start"),
                    uniprot_end=mapping.get("unp_end"),
                )
            )
    return mappings


def validate_live(
    record: MDRecord, pdbe: PDBeClient | None = None, uniprot: UniProtClient | None = None
) -> MDRecord:
    pdbe = pdbe or PDBeClient()
    uniprot = uniprot or UniProtClient()
    mapping_checked_pdbs: set[str] = set()

    for fact in record.facts:
        if fact.field_name == "pdb_id":
            pdb_id = str(fact.normalized_value).lower()
            try:
                data, digest, url = pdbe.entry_summary(pdb_id)
                key_present = pdb_id in data or pdb_id.upper() in data
                status = "validated" if key_present else "invalid"
                fact.validation.append(
                    _event(
                        "PDBe_entry_summary",
                        status,
                        f"PDBe entry lookup for {pdb_id.upper()}",
                        url,
                        digest,
                    )
                )
            except RuntimeError as exc:
                fact.validation.append(_event("PDBe_entry_summary", "unresolved", str(exc)))

            try:
                mapping_data, mapping_digest, mapping_url = pdbe.uniprot_mapping(pdb_id)
                mapping_checked_pdbs.add(pdb_id.upper())
                mappings = _extract_mappings(pdb_id, mapping_data)
                record.mappings.extend(mappings)
                record.record_validation.append(
                    _event(
                        "PDBe_SIFTS_mapping",
                        "validated" if mappings else "unresolved",
                        f"Mappings found: {len(mappings)}",
                        mapping_url,
                        mapping_digest,
                    )
                )
            except RuntimeError as exc:
                record.record_validation.append(
                    _event("PDBe_SIFTS_mapping", "unresolved", str(exc))
                )

        elif fact.field_name == "uniprot_accession":
            accession = str(fact.normalized_value).upper()
            try:
                data, digest, url = uniprot.entry(accession)
                returned = str(data.get("primaryAccession", "")).upper()
                status = "validated" if returned == accession else "conflict"
                fact.validation.append(
                    _event(
                        "UniProt_entry",
                        status,
                        f"UniProt returned {returned or 'no accession'}",
                        url,
                        digest,
                    )
                )
            except RuntimeError as exc:
                fact.validation.append(_event("UniProt_entry", "unresolved", str(exc)))

    extracted_pairs = {
        (str(p.normalized_value).upper(), str(u.normalized_value).upper())
        for p in record.facts_for("pdb_id")
        for u in record.facts_for("uniprot_accession")
    }
    mapped_pairs = {(m.pdb_id.upper(), m.uniprot_accession.upper()) for m in record.mappings}
    if extracted_pairs:
        pair_states: list[str] = []
        for pdb_id, accession in extracted_pairs:
            if pdb_id not in mapping_checked_pdbs:
                pair_states.append("unresolved")
            elif (pdb_id, accession) in mapped_pairs:
                pair_states.append("validated")
            else:
                pair_states.append("conflict")

        if all(state == "validated" for state in pair_states):
            status = "validated"
        elif "conflict" in pair_states:
            status = "conflict"
        else:
            status = "unresolved"
        record.record_validation.append(
            _event(
                "PDB_UniProt_cross_check",
                status,
                f"Extracted pairs={sorted(extracted_pairs)}; mapped pairs={sorted(mapped_pairs)}; "
                f"mapping-checked PDB IDs={sorted(mapping_checked_pdbs)}",
            )
        )
    return record
