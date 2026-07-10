from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FieldName = Literal[
    "program",
    "program_version",
    "force_field",
    "water_model",
    "ensemble",
    "temperature",
    "pressure",
    "time_step",
    "simulation_duration",
    "replicates",
    "pdb_id",
    "uniprot_accession",
]

ProtocolPhase = Literal[
    "minimisation",
    "heating",
    "equilibration",
    "production",
    "sampling_interval",
    "analysis_window",
    "initialization",
    "reported_result",
    "unspecified",
]
ValidationStatus = Literal["validated", "invalid", "conflict", "unresolved", "not_checked"]
EventCompleteness = Literal["complete", "partial", "ambiguous"]


class EvidenceSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    source_uri: str
    section: str
    paragraph_id: str
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    quote: str = Field(min_length=1)
    context_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def valid_offsets(self) -> EvidenceSpan:
        if self.end_char <= self.start_char:
            raise ValueError("end_char must be greater than start_char")
        if self.end_char - self.start_char != len(self.quote):
            raise ValueError("offset length must equal quote length")
        return self


class ValidationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    validator: str
    status: ValidationStatus
    message: str
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_uri: str | None = None
    response_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class ExtractedFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_id: str | None = None
    field_name: FieldName
    raw_value: str
    normalized_value: str | int | float
    unit: str | None = None
    phase: ProtocolPhase | None = None
    method: str = "deterministic_baseline_v1"
    confidence: float = Field(ge=0, le=1)
    evidence: list[EvidenceSpan] = Field(min_length=1)
    validation: list[ValidationEvent] = Field(default_factory=list)

    @field_validator("raw_value")
    @classmethod
    def raw_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("raw_value cannot be blank")
        return value

    @model_validator(mode="after")
    def assign_stable_fact_id(self) -> ExtractedFact:
        if self.fact_id is None:
            evidence = self.evidence[0]
            payload = "|".join(
                [
                    evidence.document_id,
                    self.field_name,
                    evidence.paragraph_id,
                    str(evidence.start_char),
                    str(evidence.end_char),
                    str(self.normalized_value),
                    self.unit or "",
                    self.phase or "",
                ]
            )
            self.fact_id = f"fact-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"
        return self


class StructureSequenceMapping(BaseModel):
    model_config = ConfigDict(extra="allow")

    pdb_id: str
    uniprot_accession: str
    chain_id: str
    pdb_start: int | None = None
    pdb_end: int | None = None
    uniprot_start: int | None = None
    uniprot_end: int | None = None
    source: str = "PDBe SIFTS-derived mapping API"


class ProtocolEvent(BaseModel):
    """A phase-aware MD protocol event linked to source facts and evidence."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    order: int = Field(ge=0)
    phase: ProtocolPhase
    duration_value: int | float | None = None
    duration_unit: Literal["ns"] | None = None
    temperature_k: int | float | None = None
    pressure_bar: int | float | None = None
    ensemble: str | None = None
    time_step_ps: int | float | None = None
    replicates: int | None = Field(default=None, ge=1)
    completeness: EventCompleteness
    source_fact_ids: list[str] = Field(default_factory=list)
    evidence: list[EvidenceSpan] = Field(default_factory=list)
    validation: list[ValidationEvent] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_event_content(self) -> ProtocolEvent:
        fields = (
            self.duration_value,
            self.temperature_k,
            self.pressure_bar,
            self.ensemble,
            self.time_step_ps,
            self.replicates,
        )
        if all(value is None for value in fields):
            raise ValueError("protocol event must contain at least one protocol attribute")
        if self.duration_value is None and self.duration_unit is not None:
            raise ValueError("duration_unit requires duration_value")
        return self


class ArticleMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    title: str | None = None
    doi: str | None = None
    pmcid: str | None = None
    source_uri: str


class MDRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "0.2.0"
    article: ArticleMetadata
    facts: list[ExtractedFact]
    protocol_events: list[ProtocolEvent] = Field(default_factory=list)
    mappings: list[StructureSequenceMapping] = Field(default_factory=list)
    record_validation: list[ValidationEvent] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    software_version: str = "0.2.0"

    def facts_for(self, field_name: FieldName) -> list[ExtractedFact]:
        return [fact for fact in self.facts if fact.field_name == field_name]

    def to_mddb_partial(self) -> dict[str, Any]:
        """Export a traceable subset of MDDB-like keys.

        This is intentionally labelled partial. It is not an MDDB ingestion payload.
        """
        key_map = {
            "program": "PROGRAM",
            "program_version": "VERSION",
            "force_field": "FF",
            "water_model": "WAT",
            "ensemble": "ENSEMBLE",
            "temperature": "TEMP",
            "time_step": "TIMESTEP",
            "pdb_id": "PDBIDS",
            "uniprot_accession": "REFERENCES",
        }
        output: dict[str, Any] = {
            "_export_status": "partial_not_ingestion_ready",
            "_source_document": self.article.document_id,
            "_schema_version": self.schema_version,
            "_protocol_event_count": len(self.protocol_events),
        }
        for source_name, target_name in key_map.items():
            matches = self.facts_for(source_name)  # type: ignore[arg-type]
            if not matches:
                continue
            values = [m.normalized_value for m in matches]
            if target_name in {"FF", "PDBIDS", "REFERENCES"}:
                output[target_name] = values
            else:
                output[target_name] = values[0] if len(values) == 1 else values
        return output
