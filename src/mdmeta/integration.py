from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from collections import Counter
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Literal

from defusedxml.ElementTree import fromstring as safe_xml_fromstring
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import Evidence, MappingSegment, ProtocolEvent, ValidationRecord, ValidationState
from .protocol_events import Paragraph, extract_protocol_events
from .validation import IdentifierValidator, PDBE_UNIPROT


class FactOrigin(StrEnum):
    LITERATURE = "literature"
    PDBE = "pdbe"
    UNIPROT = "uniprot"
    SIFTS = "sifts"
    ASSET_MANIFEST = "asset_manifest"
    PIPELINE = "pipeline"


class AssetAvailability(StrEnum):
    VERIFIED_LOCAL = "verified_local"
    EXTERNALLY_REFERENCED = "externally_referenced"
    DECLARED_UNAVAILABLE = "declared_unavailable"
    NOT_PROVIDED = "not_provided"


class MDToPDBMappingStatus(StrEnum):
    VERIFIED = "verified"
    DECLARED_ONLY = "declared_only"
    NOT_COMPUTABLE = "not_computable"


class ArticleMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    title: str
    doi: str | None = None
    source_uri: str
    full_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class LiteratureFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    value: str | bool
    origin: FactOrigin = FactOrigin.LITERATURE
    evidence: Evidence
    extraction_method: str
    confidence: float = Field(ge=0, le=1)


class MappingDiscovery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pdb_id: str
    state: ValidationState
    endpoint: str
    reason: str
    http_status: int | None = None
    response_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    attempts: int = Field(default=0, ge=0)
    cache_hit: bool = False
    accessions: list[str] = Field(default_factory=list)
    mapping_segments: list[MappingSegment] = Field(default_factory=list)


class MDAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str
    identifier: str | None = None
    availability: AssetAvailability
    source_uri: str | None = None
    local_path: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    media_type: str | None = None
    origin: FactOrigin = FactOrigin.ASSET_MANIFEST
    reason: str | None = None

    @model_validator(mode="after")
    def check_verified_asset(self) -> "MDAsset":
        if self.availability is AssetAvailability.VERIFIED_LOCAL:
            if self.local_path is None or self.sha256 is None:
                raise ValueError("verified_local assets require local_path and sha256")
        return self


class WorkflowStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    software: str | None = None
    version: str | None = None
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    origin: FactOrigin = FactOrigin.LITERATURE
    evidence_quote: str | None = None


class ProvenanceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assets: list[MDAsset] = Field(default_factory=list)
    workflow_steps: list[WorkflowStep] = Field(default_factory=list)
    md_to_pdb_mapping_status: MDToPDBMappingStatus = MDToPDBMappingStatus.NOT_COMPUTABLE
    md_to_pdb_mapping_reason: str = "no prepared structure or residue correspondence supplied"


class IntegratedMDRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["integrated-md-record-v1"] = "integrated-md-record-v1"
    article: ArticleMetadata
    literature_facts: list[LiteratureFact]
    protocol_events: list[ProtocolEvent]
    pdb_validations: list[ValidationRecord]
    mapping_discoveries: list[MappingDiscovery]
    uniprot_validations: list[ValidationRecord]
    mapping_validations: list[ValidationRecord]
    residue_mappings: list[MappingSegment]
    provenance: ProvenanceRecord
    completeness: dict[str, str]


_PDB_BLOCK = re.compile(
    r"\bPDB(?:\s+(?:ID(?:s)?|entry|entries|code(?:s)?|structure(?:s)?))?"
    r"\s*(?:\))?\s*(?:[:=#]\s*)?"
    r"(?P<ids>[0-9][A-Za-z0-9]{3}(?:\s*(?:,|/|and|or)\s*[0-9][A-Za-z0-9]{3})*)",
    re.IGNORECASE,
)
_PDB_ID = re.compile(r"\b[0-9][A-Za-z0-9]{3}\b")
_FACT_PATTERNS: dict[str, list[tuple[str, re.Pattern[str]]]] = {
    "system_contains_membrane": [
        ("true", re.compile(r"\b(?:viral\s+)?membrane\b|\blipid\s+bilayer\b", re.I))
    ],
    "system_contains_glycans": [
        ("true", re.compile(r"\bglycans?\b|\bglycosylat(?:ed|ion)\b", re.I))
    ],
    "simulation_engine": [
        ("GROMACS", re.compile(r"\bGROMACS\b", re.I)),
        ("AMBER", re.compile(r"\bAMBER(?:TOOLS)?\b", re.I)),
        ("NAMD", re.compile(r"\bNAMD\b", re.I)),
        ("OpenMM", re.compile(r"\bOpenMM\b", re.I)),
        ("CHARMM", re.compile(r"\bCHARMM\b", re.I)),
        ("Desmond", re.compile(r"\bDesmond\b", re.I)),
    ],
    "force_field": [
        (
            "matched_text",
            re.compile(
                r"\b(?:CHARMM(?:19|22|27|36m?|\d{2}[a-z]?)|"
                r"ff(?:99|03|12|14|19)SB|OPLS(?:-AA)?|GROMOS(?:\s*\d+[A-Za-z0-9]*)?)\b",
                re.I,
            ),
        )
    ],
    "water_model": [
        ("matched_text", re.compile(r"\b(?:TIP[345]P(?:-Ew)?|SPC(?:/E)?|OPC)\b", re.I))
    ],
}
_METHOD_TITLE_TERMS = (
    "method",
    "simulation",
    "computational",
    "molecular dynamics",
    "system preparation",
)
_PROTOCOL_SIGNAL = re.compile(
    r"molecular dynamics|\bMD\b|equilibrat|production simulation|force field|\bNPT\b|\bNVT\b",
    re.I,
)


def _text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return " ".join("".join(node.itertext()).split())


def parse_jats_paragraphs(document_id: str, xml_bytes: bytes) -> list[Paragraph]:
    root = safe_xml_fromstring(xml_bytes)
    paragraphs: list[Paragraph] = []
    seen: set[tuple[str, str]] = set()
    for section_index, section in enumerate(root.findall(".//body//sec"), start=1):
        section_title = _text(section.find("./title")) or f"section-{section_index}"
        for paragraph_index, node in enumerate(section.findall("./p"), start=1):
            text = _text(node)
            if not text:
                continue
            paragraph_id = node.attrib.get("id") or f"sec-{section_index}-p-{paragraph_index}"
            key = (paragraph_id, text)
            if key in seen:
                continue
            seen.add(key)
            paragraphs.append(
                Paragraph(
                    document_id=document_id,
                    section=section_title,
                    paragraph_id=paragraph_id,
                    text=text,
                )
            )
    return paragraphs


def extract_article_metadata(
    document_id: str,
    xml_bytes: bytes,
    *,
    source_uri: str,
) -> ArticleMetadata:
    root = safe_xml_fromstring(xml_bytes)
    title = _text(root.find(".//article-title"))
    doi_node = root.find(".//article-id[@pub-id-type='doi']")
    doi = _text(doi_node) or None
    return ArticleMetadata(
        document_id=document_id,
        title=title,
        doi=doi,
        source_uri=source_uri,
        full_text_sha256=hashlib.sha256(xml_bytes).hexdigest(),
    )


def _fact_evidence(paragraph: Paragraph, start: int, end: int) -> Evidence:
    return Evidence(
        document_id=paragraph.document_id,
        section=paragraph.section,
        paragraph_id=paragraph.paragraph_id,
        quote=paragraph.text[start:end],
        start_char=start,
        end_char=end,
        context_sha256=hashlib.sha256(paragraph.text.encode("utf-8")).hexdigest(),
    )


def extract_literature_facts(paragraphs: list[Paragraph]) -> list[LiteratureFact]:
    facts: list[LiteratureFact] = []
    seen: set[tuple[str, str]] = set()

    def add_fact(
        paragraph: Paragraph,
        field: str,
        value: str | bool,
        start: int,
        end: int,
        method: str,
        confidence: float,
    ) -> None:
        key = (field, str(value).casefold())
        if key in seen:
            return
        seen.add(key)
        facts.append(
            LiteratureFact(
                field=field,
                value=value,
                evidence=_fact_evidence(paragraph, start, end),
                extraction_method=method,
                confidence=confidence,
            )
        )

    for paragraph in paragraphs:
        for block in _PDB_BLOCK.finditer(paragraph.text):
            body = block.group("ids")
            for identifier in _PDB_ID.finditer(body):
                start = block.start("ids") + identifier.start()
                end = block.start("ids") + identifier.end()
                add_fact(
                    paragraph,
                    "starting_pdb_id",
                    identifier.group(0).upper(),
                    start,
                    end,
                    "explicit_pdb_context_regex_v1",
                    0.99,
                )

        for field, patterns in _FACT_PATTERNS.items():
            for canonical, pattern in patterns:
                for match in pattern.finditer(paragraph.text):
                    value: str | bool
                    if field.startswith("system_contains_"):
                        value = True
                    elif canonical == "matched_text":
                        value = match.group(0)
                    else:
                        value = canonical
                    add_fact(
                        paragraph,
                        field,
                        value,
                        match.start(),
                        match.end(),
                        f"explicit_{field}_regex_v1",
                        0.9,
                    )
    return facts


def protocol_paragraphs(paragraphs: list[Paragraph]) -> list[Paragraph]:
    selected: list[Paragraph] = []
    for paragraph in paragraphs:
        title_match = any(term in paragraph.section.casefold() for term in _METHOD_TITLE_TERMS)
        if title_match or _PROTOCOL_SIGNAL.search(paragraph.text):
            selected.append(paragraph)
    return selected


def discover_uniprot_mappings(
    validator: IdentifierValidator,
    pdb_id: str,
) -> MappingDiscovery:
    normalized = pdb_id.lower()
    endpoint = PDBE_UNIPROT.format(pdb_id=normalized)
    retrieved = validator._retrieve(endpoint)  # deliberate reuse of audited retry/cache logic
    if (
        not retrieved.response_received
        or not retrieved.payload_valid
        or retrieved.http_status != 200
    ):
        return MappingDiscovery(
            pdb_id=pdb_id.upper(),
            state=ValidationState.UNRESOLVED,
            endpoint=endpoint,
            reason=retrieved.terminal_error or "mapping_response_unavailable",
            http_status=retrieved.http_status,
            response_sha256=retrieved.response_sha256,
            attempts=retrieved.attempts,
            cache_hit=retrieved.cache_hit,
        )

    payload = retrieved.payload or {}
    pdb_payload = payload.get(normalized)
    if pdb_payload is not None and not isinstance(pdb_payload, dict):
        return MappingDiscovery(
            pdb_id=pdb_id.upper(),
            state=ValidationState.UNRESOLVED,
            endpoint=endpoint,
            reason="malformed_mapping_payload",
            http_status=retrieved.http_status,
            response_sha256=retrieved.response_sha256,
            attempts=retrieved.attempts,
            cache_hit=retrieved.cache_hit,
        )
    uniprot = (pdb_payload or {}).get("UniProt", {})
    if not isinstance(uniprot, dict):
        return MappingDiscovery(
            pdb_id=pdb_id.upper(),
            state=ValidationState.UNRESOLVED,
            endpoint=endpoint,
            reason="malformed_mapping_payload",
            http_status=retrieved.http_status,
            response_sha256=retrieved.response_sha256,
            attempts=retrieved.attempts,
            cache_hit=retrieved.cache_hit,
        )
    segments: list[MappingSegment] = []
    for accession, accession_payload in sorted(uniprot.items()):
        if not isinstance(accession, str) or not isinstance(accession_payload, dict):
            return MappingDiscovery(
                pdb_id=pdb_id.upper(),
                state=ValidationState.UNRESOLVED,
                endpoint=endpoint,
                reason="malformed_mapping_payload",
                http_status=retrieved.http_status,
                response_sha256=retrieved.response_sha256,
                attempts=retrieved.attempts,
                cache_hit=retrieved.cache_hit,
            )
        mappings = accession_payload.get("mappings", [])
        if not isinstance(mappings, list) or not all(
            isinstance(item, dict) for item in mappings
        ):
            return MappingDiscovery(
                pdb_id=pdb_id.upper(),
                state=ValidationState.UNRESOLVED,
                endpoint=endpoint,
                reason="malformed_mapping_payload",
                http_status=retrieved.http_status,
                response_sha256=retrieved.response_sha256,
                attempts=retrieved.attempts,
                cache_hit=retrieved.cache_hit,
            )
        segments.extend(validator._mapping_segments(normalized, accession, mappings))
    accessions = sorted({segment.uniprot_accession for segment in segments})
    state = ValidationState.VALIDATED if segments else ValidationState.CONFLICT
    reason = (
        "sifts_mappings_discovered"
        if segments
        else "no_uniprot_mapping_in_successful_response"
    )
    return MappingDiscovery(
        pdb_id=pdb_id.upper(),
        state=state,
        endpoint=endpoint,
        reason=reason,
        http_status=retrieved.http_status,
        response_sha256=retrieved.response_sha256,
        attempts=retrieved.attempts,
        cache_hit=retrieved.cache_hit,
        accessions=accessions,
        mapping_segments=segments,
    )


def build_provenance(
    manifest: dict[str, Any] | None,
    *,
    base_dir: str | Path | None = None,
) -> ProvenanceRecord:
    if manifest is None:
        return ProvenanceRecord()

    root = Path(base_dir) if base_dir is not None else None
    assets: list[MDAsset] = []
    for row in manifest.get("assets", []):
        item = dict(row)
        availability = AssetAvailability(item["availability"])
        if availability is AssetAvailability.VERIFIED_LOCAL:
            if root is None:
                raise ValueError("base_dir is required for verified_local assets")
            path = root / item["local_path"]
            if not path.is_file():
                raise FileNotFoundError(path)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            expected = item.get("sha256")
            if expected is not None and digest != expected:
                raise ValueError(f"asset SHA-256 mismatch: {path}")
            item["sha256"] = digest
        assets.append(MDAsset.model_validate(item))

    steps = [WorkflowStep.model_validate(row) for row in manifest.get("workflow_steps", [])]
    mapping = manifest.get("md_to_pdb_mapping", {})
    return ProvenanceRecord(
        assets=assets,
        workflow_steps=steps,
        md_to_pdb_mapping_status=MDToPDBMappingStatus(
            mapping.get("status", MDToPDBMappingStatus.NOT_COMPUTABLE)
        ),
        md_to_pdb_mapping_reason=mapping.get(
            "reason", "no prepared structure or residue correspondence supplied"
        ),
    )


def _compact_validation(record: ValidationRecord, retain_payload: bool) -> ValidationRecord:
    return record if retain_payload else record.model_copy(update={"payload": None})


def _validation_completeness(records: list[ValidationRecord]) -> str:
    if not records:
        return "not_applicable"
    states = Counter(record.state for record in records)
    if states[ValidationState.VALIDATED] == len(records):
        return "complete"
    if states[ValidationState.VALIDATED] > 0:
        return "partial"
    if states[ValidationState.UNRESOLVED] > 0:
        return "unresolved"
    return "conflict"


def integrate_article(
    document_id: str,
    xml_bytes: bytes,
    *,
    source_uri: str,
    validator: IdentifierValidator,
    provenance_manifest: dict[str, Any] | None = None,
    provenance_base_dir: str | Path | None = None,
    event_extractor: Callable[[Paragraph], list[ProtocolEvent]] = extract_protocol_events,
    retain_external_payload: bool = False,
) -> IntegratedMDRecord:
    article = extract_article_metadata(document_id, xml_bytes, source_uri=source_uri)
    paragraphs = parse_jats_paragraphs(document_id, xml_bytes)
    facts = extract_literature_facts(paragraphs)
    events = [
        event
        for paragraph in protocol_paragraphs(paragraphs)
        for event in event_extractor(paragraph)
    ]
    pdb_ids = sorted(
        {str(fact.value) for fact in facts if fact.field == "starting_pdb_id"}
    )

    pdb_validations: list[ValidationRecord] = []
    discoveries: list[MappingDiscovery] = []
    uniprot_validations: list[ValidationRecord] = []
    mapping_validations: list[ValidationRecord] = []
    segments: list[MappingSegment] = []

    for pdb_id in pdb_ids:
        pdb_record = validator.validate_pdb(pdb_id)
        pdb_validations.append(_compact_validation(pdb_record, retain_external_payload))
        if pdb_record.state is not ValidationState.VALIDATED:
            continue
        discovery = discover_uniprot_mappings(validator, pdb_id)
        discoveries.append(discovery)
        segments.extend(discovery.mapping_segments)
        for accession in discovery.accessions:
            uniprot_record = validator.validate_uniprot(accession)
            mapping_record = validator.validate_mapping(pdb_id, accession)
            uniprot_validations.append(
                _compact_validation(uniprot_record, retain_external_payload)
            )
            mapping_validations.append(
                _compact_validation(mapping_record, retain_external_payload)
            )

    unique_segments: dict[tuple[Any, ...], MappingSegment] = {}
    for segment in segments:
        key = (
            segment.pdb_id,
            segment.uniprot_accession,
            segment.chain_id,
            segment.pdb_start,
            segment.pdb_end,
            segment.uniprot_start,
            segment.uniprot_end,
        )
        unique_segments[key] = segment
    provenance = build_provenance(provenance_manifest, base_dir=provenance_base_dir)

    if unique_segments:
        residue_status = (
            "md_to_pdb_to_uniprot_verified"
            if provenance.md_to_pdb_mapping_status is MDToPDBMappingStatus.VERIFIED
            else "pdb_to_uniprot_only"
        )
    else:
        residue_status = "not_computable"

    if not provenance.assets:
        provenance_status = "not_provided"
    elif all(
        asset.availability is AssetAvailability.VERIFIED_LOCAL
        for asset in provenance.assets
    ):
        provenance_status = "verified"
    else:
        provenance_status = "declared_not_fully_verified"

    completeness = {
        "literature_extraction": "complete" if facts else "no_supported_fact",
        "pdb_validation": _validation_completeness(pdb_validations),
        "uniprot_enrichment": _validation_completeness(uniprot_validations),
        "sifts_mapping": _validation_completeness(mapping_validations),
        "residue_mapping_scope": residue_status,
        "md_file_provenance": provenance_status,
    }
    return IntegratedMDRecord(
        article=article,
        literature_facts=facts,
        protocol_events=events,
        pdb_validations=pdb_validations,
        mapping_discoveries=discoveries,
        uniprot_validations=uniprot_validations,
        mapping_validations=mapping_validations,
        residue_mappings=list(unique_segments.values()),
        provenance=provenance,
        completeness=completeness,
    )


def summarize_integrated_records(
    records: list[IntegratedMDRecord],
    failures: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    failures = failures or []
    pdb_ids = {
        str(fact.value)
        for record in records
        for fact in record.literature_facts
        if fact.field == "starting_pdb_id"
    }
    accessions = {
        segment.uniprot_accession
        for record in records
        for segment in record.residue_mappings
    }
    return {
        "article_count_succeeded": len(records),
        "failure_count": len(failures),
        "article_count_with_pdb": sum(
            any(fact.field == "starting_pdb_id" for fact in record.literature_facts)
            for record in records
        ),
        "unique_pdb_id_count": len(pdb_ids),
        "unique_uniprot_accession_count": len(accessions),
        "residue_mapping_segment_count": sum(len(record.residue_mappings) for record in records),
        "protocol_event_count": sum(len(record.protocol_events) for record in records),
        "pdb_validation_state_counts": dict(
            sorted(
                Counter(
                    item.state.value
                    for record in records
                    for item in record.pdb_validations
                ).items()
            )
        ),
        "mapping_validation_state_counts": dict(
            sorted(
                Counter(
                    item.state.value
                    for record in records
                    for item in record.mapping_validations
                ).items()
            )
        ),
        "md_file_provenance_counts": dict(
            sorted(Counter(record.completeness["md_file_provenance"] for record in records).items())
        ),
        "failures": failures,
    }
