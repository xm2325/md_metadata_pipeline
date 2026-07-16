from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .integration import (
    AssetAvailability,
    FactOrigin,
    LiteratureFact,
    MappingDiscovery,
    MDToPDBMappingStatus,
)
from .models import MappingSegment, ProtocolEvent, ValidationRecord
from .pdbekb import PDBeKBEnrichment


class _APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ValidationIssue(_APIModel):
    location: list[str | int]
    message: str
    error_type: str


class ProblemDetail(_APIModel):
    """Stable RFC 9457-compatible error envelope with trace correlation."""

    type: str
    title: str
    status: int = Field(ge=400, le=599)
    detail: str
    instance: str
    code: str
    request_id: str
    errors: list[ValidationIssue] | None = None


class HealthResponse(_APIModel):
    status: Literal["ok"]
    article_count: int = Field(ge=0)


class LivenessResponse(_APIModel):
    status: Literal["ok"]
    version: str


class ReadinessResponse(_APIModel):
    status: Literal["ready"]
    version: str
    database_schema_version: int = Field(ge=1)
    article_count: int = Field(ge=0)


class MetadataResponse(_APIModel):
    service: Literal["md-metadata-pipeline"]
    version: str
    record_schema: Literal["integrated-md-record-v1"]
    database_schema_version: int = Field(ge=1)
    article_count: int = Field(ge=0)
    database_mode: Literal["read_only", "read_write"]
    dataset_sha256: str
    build_sha: str


class PublicArticleMetadata(_APIModel):
    """Article metadata after server-local source locations are removed."""

    document_id: str
    title: str
    doi: str | None = None
    source_uri: str | None = None
    full_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PublicMDAsset(_APIModel):
    """Public asset view without the internal verified-local invariant."""

    role: str
    identifier: str | None = None
    availability: AssetAvailability
    source_uri: str | None = None
    local_path: None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    media_type: str | None = None
    origin: FactOrigin = FactOrigin.ASSET_MANIFEST
    reason: str | None = None


class PublicWorkflowStep(_APIModel):
    name: str
    software: str | None = None
    version: str | None = None
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    origin: FactOrigin = FactOrigin.LITERATURE
    evidence_quote: str | None = None


class PublicProvenanceRecord(_APIModel):
    assets: list[PublicMDAsset] = Field(default_factory=list)
    workflow_steps: list[PublicWorkflowStep] = Field(default_factory=list)
    md_to_pdb_mapping_status: MDToPDBMappingStatus = MDToPDBMappingStatus.NOT_COMPUTABLE
    md_to_pdb_mapping_reason: str = (
        "no prepared structure or residue correspondence supplied"
    )


class PublicIntegratedMDRecord(_APIModel):
    schema_version: Literal["integrated-md-record-v1"] = "integrated-md-record-v1"
    article: PublicArticleMetadata
    literature_facts: list[LiteratureFact]
    protocol_events: list[ProtocolEvent]
    pdb_validations: list[ValidationRecord]
    mapping_discoveries: list[MappingDiscovery]
    uniprot_validations: list[ValidationRecord]
    mapping_validations: list[ValidationRecord]
    residue_mappings: list[MappingSegment]
    provenance: PublicProvenanceRecord
    completeness: dict[str, str]


class SearchResponse(_APIModel):
    count: int = Field(ge=0)
    records: list[PublicIntegratedMDRecord]


class PDBeKBResponse(_APIModel):
    accession: str
    count: int = Field(ge=0)
    enrichments: list[PDBeKBEnrichment]
