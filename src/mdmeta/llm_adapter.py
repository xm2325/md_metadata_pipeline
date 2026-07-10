from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .models import EventType, Evidence, ProtocolEvent
from .protocol_events import Paragraph


class StructuredBackend(Protocol):
    """Provider-independent interface for structured model generation."""

    def complete(self, prompt: str, json_schema: dict[str, Any]) -> dict[str, Any]: ...


class RawQuantity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_text: str = Field(min_length=1)
    value: float
    unit: str = Field(min_length=1)


class RawCount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_text: str = Field(min_length=1)
    value: int = Field(ge=1)


class LLMEventCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: EventType
    paragraph_id: str = Field(min_length=1)
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    quote: str = Field(min_length=1)
    duration: RawQuantity | None = None
    temperature: RawQuantity | None = None
    pressure: RawQuantity | None = None
    timestep: RawQuantity | None = None
    ensemble: str | None = None
    restraints: str | None = None
    replicates: RawCount | None = None
    confidence: float = Field(ge=0, le=1)


class LLMEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[LLMEventCandidate]


class EvidenceIntegrityError(ValueError):
    """Raised when a proposed event is not exactly supported by supplied text."""


_QUANTITY = re.compile(
    r"\s*(?P<value>[+-]?\d+(?:\.\d+)?)\s*"
    r"(?P<unit>fs|ps|ns|us|µs|μs|ms|K|kelvin|°C|Celsius|bar|atm)\s*",
    re.IGNORECASE,
)
_COUNT_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}
_ALLOWED_ENSEMBLES = {"NVE", "NVT", "NPT", "NPAT", "NPH"}


def _canonical_unit(unit: str) -> str:
    compact = unit.strip().replace("μ", "µ")
    aliases = {"kelvin": "K", "celsius": "°C", "c": "°C"}
    return aliases.get(compact.casefold(), compact)


def _verify_quantity(quantity: RawQuantity, quote: str) -> tuple[float, str]:
    if quantity.raw_text not in quote:
        raise EvidenceIntegrityError("quantity raw_text is not present in the evidence quote")
    match = _QUANTITY.fullmatch(quantity.raw_text)
    if match is None:
        raise EvidenceIntegrityError("quantity raw_text does not match the accepted numeric-unit form")
    parsed_value = float(match.group("value"))
    parsed_unit = _canonical_unit(match.group("unit"))
    supplied_unit = _canonical_unit(quantity.unit)
    if not math.isclose(parsed_value, quantity.value, rel_tol=0.0, abs_tol=1e-12):
        raise EvidenceIntegrityError("quantity value disagrees with raw_text")
    if parsed_unit.casefold() != supplied_unit.casefold():
        raise EvidenceIntegrityError("quantity unit disagrees with raw_text")
    return parsed_value, parsed_unit


def _duration_ps(quantity: RawQuantity, quote: str) -> float:
    value, unit = _verify_quantity(quantity, quote)
    factor = {"fs": 1e-3, "ps": 1.0, "ns": 1e3, "us": 1e6, "µs": 1e6, "ms": 1e9}.get(
        unit.casefold().replace("μ", "µ")
    )
    if factor is None:
        raise EvidenceIntegrityError("unsupported duration unit")
    return value * factor


def _temperature_k(quantity: RawQuantity, quote: str) -> float:
    value, unit = _verify_quantity(quantity, quote)
    if unit.casefold() == "k":
        return value
    if unit == "°C":
        return value + 273.15
    raise EvidenceIntegrityError("unsupported temperature unit")


def _pressure_bar(quantity: RawQuantity, quote: str) -> float:
    value, unit = _verify_quantity(quantity, quote)
    if unit.casefold() == "bar":
        return value
    if unit.casefold() == "atm":
        return value * 1.01325
    raise EvidenceIntegrityError("unsupported pressure unit")


def _timestep_fs(quantity: RawQuantity, quote: str) -> float:
    value, unit = _verify_quantity(quantity, quote)
    if unit.casefold() == "fs":
        return value
    if unit.casefold() == "ps":
        return value * 1000
    raise EvidenceIntegrityError("unsupported timestep unit")


def _replicate_count(count: RawCount, quote: str) -> int:
    if count.raw_text not in quote:
        raise EvidenceIntegrityError("replicate raw_text is not present in the evidence quote")
    token = count.raw_text.strip().casefold()
    parsed = int(token) if token.isdigit() else _COUNT_WORDS.get(token)
    if parsed is None:
        raise EvidenceIntegrityError("replicate raw_text is not an accepted count")
    if parsed != count.value:
        raise EvidenceIntegrityError("replicate value disagrees with raw_text")
    return parsed


class SchemaConstrainedEventExtractor:
    """Accept only model events that pass exact evidence and deterministic unit checks."""

    def __init__(self, backend: StructuredBackend, model_id: str) -> None:
        self.backend = backend
        self.model_id = model_id

    @staticmethod
    def _prompt(paragraphs: list[Paragraph]) -> str:
        blocks = "\n\n".join(
            f"[paragraph_id={paragraph.paragraph_id}; section={paragraph.section}]\n{paragraph.text}"
            for paragraph in paragraphs
        )
        return (
            "Extract only explicitly stated molecular-dynamics protocol events. "
            "Do not infer missing values and do not use outside knowledge. "
            "For each event, copy one exact evidence quote from one supplied paragraph and provide "
            "zero-based character offsets relative to that paragraph. For every numeric field, "
            "copy the exact numeric-unit expression into raw_text and also return its parsed value "
            "and unit. Return an empty events list when no supported event is present.\n\n"
            f"SOURCE PARAGRAPHS\n{blocks}"
        )

    def extract(self, paragraphs: list[Paragraph]) -> list[ProtocolEvent]:
        response = self.backend.complete(
            self._prompt(paragraphs),
            LLMEventResponse.model_json_schema(),
        )
        parsed = LLMEventResponse.model_validate(response)
        by_id = {paragraph.paragraph_id: paragraph for paragraph in paragraphs}
        events: list[ProtocolEvent] = []
        seen: set[str] = set()

        for candidate in parsed.events:
            paragraph = by_id.get(candidate.paragraph_id)
            if paragraph is None:
                raise EvidenceIntegrityError(f"unknown paragraph_id: {candidate.paragraph_id}")
            if candidate.end_char > len(paragraph.text):
                raise EvidenceIntegrityError("evidence range exceeds paragraph length")
            if paragraph.text[candidate.start_char : candidate.end_char] != candidate.quote:
                raise EvidenceIntegrityError("evidence quote does not match source offsets")

            attributes_present = any(
                value is not None
                for value in (
                    candidate.duration,
                    candidate.temperature,
                    candidate.pressure,
                    candidate.timestep,
                    candidate.ensemble,
                    candidate.restraints,
                    candidate.replicates,
                )
            )
            if not attributes_present:
                raise EvidenceIntegrityError("event has no protocol attribute")

            ensemble = candidate.ensemble.upper() if candidate.ensemble is not None else None
            if ensemble is not None:
                if candidate.ensemble not in candidate.quote:
                    raise EvidenceIntegrityError("ensemble text is not present in the evidence quote")
                if ensemble not in _ALLOWED_ENSEMBLES:
                    raise EvidenceIntegrityError("unsupported ensemble")
            if candidate.restraints is not None and candidate.restraints not in candidate.quote:
                raise EvidenceIntegrityError("restraints text is not present in the evidence quote")

            normalized = {
                "duration_ps": _duration_ps(candidate.duration, candidate.quote)
                if candidate.duration is not None
                else None,
                "temperature_k": _temperature_k(candidate.temperature, candidate.quote)
                if candidate.temperature is not None
                else None,
                "pressure_bar": _pressure_bar(candidate.pressure, candidate.quote)
                if candidate.pressure is not None
                else None,
                "timestep_fs": _timestep_fs(candidate.timestep, candidate.quote)
                if candidate.timestep is not None
                else None,
                "replicates": _replicate_count(candidate.replicates, candidate.quote)
                if candidate.replicates is not None
                else None,
            }
            stable_payload = "|".join(
                [
                    paragraph.document_id,
                    paragraph.paragraph_id,
                    str(candidate.start_char),
                    str(candidate.end_char),
                    candidate.event_type.value,
                    repr(sorted(normalized.items())),
                    ensemble or "",
                    candidate.restraints or "",
                ]
            )
            event_id = f"llm-event-{hashlib.sha256(stable_payload.encode('utf-8')).hexdigest()[:16]}"
            if event_id in seen:
                continue
            seen.add(event_id)
            evidence = Evidence(
                document_id=paragraph.document_id,
                section=paragraph.section,
                paragraph_id=paragraph.paragraph_id,
                quote=candidate.quote,
                start_char=candidate.start_char,
                end_char=candidate.end_char,
                context_sha256=hashlib.sha256(paragraph.text.encode("utf-8")).hexdigest(),
            )
            events.append(
                ProtocolEvent(
                    event_id=event_id,
                    event_type=candidate.event_type,
                    duration_ps=normalized["duration_ps"],
                    temperature_k=normalized["temperature_k"],
                    pressure_bar=normalized["pressure_bar"],
                    timestep_fs=normalized["timestep_fs"],
                    ensemble=ensemble,
                    restraints=candidate.restraints,
                    replicates=normalized["replicates"],
                    evidence=[evidence],
                    relation_method=f"schema_constrained_llm:{self.model_id}:exact_span_v1",
                    confidence=candidate.confidence,
                )
            )
        return events
