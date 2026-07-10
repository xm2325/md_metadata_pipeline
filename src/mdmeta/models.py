from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class EventType(StrEnum):
    MINIMISATION = "minimisation"
    HEATING = "heating"
    EQUILIBRATION = "equilibration"
    PRODUCTION = "production"
    ANALYSIS_WINDOW = "analysis_window"
    SAMPLING_INTERVAL = "sampling_interval"
    UNKNOWN = "unknown"


class Evidence(BaseModel):
    document_id: str
    section: str
    paragraph_id: str
    quote: str
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def check_span(self) -> "Evidence":
        if self.end_char <= self.start_char:
            raise ValueError("end_char must exceed start_char")
        if len(self.quote) != self.end_char - self.start_char:
            raise ValueError("quote length must equal evidence span length")
        return self


class ProtocolEvent(BaseModel):
    event_id: str
    event_type: EventType
    duration_ps: float | None = Field(default=None, gt=0)
    temperature_k: float | None = Field(default=None, gt=0)
    pressure_bar: float | None = Field(default=None, gt=0)
    timestep_fs: float | None = Field(default=None, gt=0)
    ensemble: Literal["NVE", "NVT", "NPT", "NPAT", "NPH"] | None = None
    restraints: str | None = None
    replicates: int | None = Field(default=None, ge=1)
    evidence: list[Evidence]
    relation_method: str
    confidence: float = Field(ge=0, le=1)


class ValidationState(StrEnum):
    VALIDATED = "validated"
    CONFLICT = "conflict"
    UNRESOLVED = "unresolved"
    NOT_APPLICABLE = "not_applicable"


class ValidationRecord(BaseModel):
    identifier_type: Literal["pdb", "uniprot", "pdb_uniprot_mapping"]
    query: dict[str, str]
    state: ValidationState
    endpoint: str
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    response_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    http_status: int | None = None
    reason: str
    payload: dict[str, Any] | None = None
