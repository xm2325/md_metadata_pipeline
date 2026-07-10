from __future__ import annotations

import hashlib
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .extraction import PATTERNS
from .jats import Paragraph
from .models import EvidenceSpan, ExtractedFact, FieldName


class LLMBackend(Protocol):
    """Provider-independent contract for schema-constrained generation."""

    def complete(self, prompt: str, json_schema: dict[str, Any]) -> dict[str, Any]: ...


class LLMFactCandidate(BaseModel):
    """One proposed fact before evidence-integrity checks."""

    model_config = ConfigDict(extra="forbid")

    field_name: FieldName
    raw_value: str = Field(min_length=1)
    normalized_value: str | int | float
    unit: str | None = None
    paragraph_id: str = Field(min_length=1)
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    confidence: float = Field(ge=0, le=1)


class LLMExtractionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facts: list[LLMFactCandidate]


class EvidenceIntegrityError(ValueError):
    """Raised when a model output cannot be tied exactly to supplied text."""


class SchemaConstrainedLLMExtractor:
    """Validate model-proposed facts against immutable source paragraphs.

    The model proposes structured candidates. This class, not the model, creates
    evidence objects. A candidate is accepted only when its paragraph identifier
    exists and its character range reproduces ``raw_value`` exactly.
    """

    def __init__(self, backend: LLMBackend, model_id: str) -> None:
        self.backend = backend
        self.method_name = f"schema_constrained_llm:{model_id}"

    @staticmethod
    def _prompt(paragraphs: list[Paragraph]) -> str:
        fields = (
            "program, program_version, force_field, water_model, ensemble, "
            "temperature, pressure, time_step, simulation_duration, replicates, "
            "pdb_id, uniprot_accession"
        )
        blocks = "\n\n".join(
            f"[paragraph_id={p.paragraph_id}; section={p.section}]\n{p.text}" for p in paragraphs
        )
        return (
            "Extract only explicitly stated molecular-dynamics metadata. "
            f"Allowed fields: {fields}. Return JSON matching the supplied schema. "
            "For every fact, copy raw_value exactly from one paragraph and report "
            "zero-based start_char and end_char offsets relative to that paragraph. "
            "Do not infer missing values, do not use outside knowledge, and return an "
            "empty facts list when no supported fact is present.\n\n"
            f"SOURCE PARAGRAPHS\n{blocks}"
        )

    def extract(
        self,
        paragraphs: list[Paragraph],
        document_id: str,
        source_uri: str,
    ) -> list[ExtractedFact]:
        response = self.backend.complete(
            self._prompt(paragraphs),
            LLMExtractionResponse.model_json_schema(),
        )
        parsed = LLMExtractionResponse.model_validate(response)
        by_id = {paragraph.paragraph_id: paragraph for paragraph in paragraphs}
        facts: list[ExtractedFact] = []
        seen: set[tuple[str, str, str | None, str, int, int]] = set()

        for candidate in parsed.facts:
            paragraph = by_id.get(candidate.paragraph_id)
            if paragraph is None:
                raise EvidenceIntegrityError(f"Unknown paragraph_id: {candidate.paragraph_id}")
            if candidate.end_char > len(paragraph.text):
                raise EvidenceIntegrityError(
                    f"Evidence range exceeds paragraph length: {candidate.paragraph_id}"
                )
            source_slice = paragraph.text[candidate.start_char : candidate.end_char]
            if source_slice != candidate.raw_value:
                raise EvidenceIntegrityError(
                    "raw_value does not equal the source text at the supplied offsets"
                )

            specs = [spec for spec in PATTERNS if spec.field_name == candidate.field_name]
            supported = [
                (spec, match)
                for spec in specs
                if (match := spec.pattern.fullmatch(candidate.raw_value)) is not None
            ]
            if len(supported) != 1:
                raise EvidenceIntegrityError(
                    "raw_value is not accepted by the deterministic normalizer for the field"
                )
            spec, match = supported[0]
            expected_value, expected_unit = spec.normalizer(match)
            if candidate.normalized_value != expected_value or candidate.unit != expected_unit:
                raise EvidenceIntegrityError(
                    "model-proposed normalization does not match deterministic normalization"
                )

            key = (
                candidate.field_name,
                str(candidate.normalized_value),
                candidate.unit,
                candidate.paragraph_id,
                candidate.start_char,
                candidate.end_char,
            )
            if key in seen:
                continue
            seen.add(key)

            evidence = EvidenceSpan(
                document_id=document_id,
                source_uri=source_uri,
                section=paragraph.section,
                paragraph_id=paragraph.paragraph_id,
                start_char=candidate.start_char,
                end_char=candidate.end_char,
                quote=candidate.raw_value,
                context_sha256=hashlib.sha256(paragraph.text.encode("utf-8")).hexdigest(),
            )
            facts.append(
                ExtractedFact(
                    field_name=candidate.field_name,
                    raw_value=candidate.raw_value,
                    normalized_value=candidate.normalized_value,
                    unit=candidate.unit,
                    method=self.method_name,
                    confidence=candidate.confidence,
                    evidence=[evidence],
                )
            )
        return facts
