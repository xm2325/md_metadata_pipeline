from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from .jats import Paragraph
from .models import EvidenceSpan, ExtractedFact
from .normalization import (
    format_number,
    normalize_duration,
    normalize_pressure,
    normalize_temperature,
    normalize_time_step,
    parse_number,
)


class Extractor(Protocol):
    def extract(
        self, paragraphs: list[Paragraph], document_id: str, source_uri: str
    ) -> list[ExtractedFact]: ...


@dataclass(frozen=True)
class PatternSpec:
    field_name: str
    pattern: re.Pattern[str]
    normalizer: Callable[[re.Match[str]], tuple[str | int | float, str | None]]
    confidence: float


def _identity(group: str = "value") -> Callable[[re.Match[str]], tuple[str, None]]:
    return lambda match: (match.group(group), None)


def _numeric_with_unit(
    value_group: str,
    unit_group: str,
    fn: Callable[[float, str], tuple[float, str]],
) -> Callable[[re.Match[str]], tuple[int | float, str]]:
    def normalize(match: re.Match[str]) -> tuple[int | float, str]:
        value, unit = fn(parse_number(match.group(value_group)), match.group(unit_group))
        return format_number(value), unit

    return normalize


PROGRAMS = r"GROMACS|AMBER|NAMD|OpenMM|CHARMM|Desmond"
FORCE_FIELDS = (
    r"CHARMM36m|CHARMM36|AMBER99SB-ILDN|AMBER14SB|ff14SB|OPLS-AA/M|OPLS-AA|Martini\s*3|Martini"
)
WATER_MODELS = r"TIP3P|TIP4P-Ew|TIP4P|SPC/E|SPCE|SPC"

PATTERNS: list[PatternSpec] = [
    PatternSpec(
        "program",
        re.compile(rf"\b(?P<value>{PROGRAMS})\b", re.IGNORECASE),
        lambda m: (
            m.group("value").upper() if m.group("value").lower() != "openmm" else "OpenMM",
            None,
        ),
        0.99,
    ),
    PatternSpec(
        "program_version",
        re.compile(rf"\b(?:{PROGRAMS})\s+(?:version\s+)?(?P<value>\d+(?:\.\d+)+)\b", re.IGNORECASE),
        _identity(),
        0.95,
    ),
    PatternSpec(
        "force_field",
        re.compile(rf"\b(?P<value>{FORCE_FIELDS})\b", re.IGNORECASE),
        lambda m: (re.sub(r"\s+", " ", m.group("value")), None),
        0.98,
    ),
    PatternSpec(
        "water_model",
        re.compile(rf"\b(?P<value>{WATER_MODELS})\b", re.IGNORECASE),
        lambda m: (m.group("value").upper().replace("SPCE", "SPC/E"), None),
        0.98,
    ),
    PatternSpec(
        "ensemble",
        re.compile(r"\b(?P<value>NPT|NVT|NVE)\s+(?:ensemble)?\b", re.IGNORECASE),
        lambda m: (m.group("value").upper(), None),
        0.99,
    ),
    PatternSpec(
        "temperature",
        re.compile(r"\b(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>K|kelvin|°C|Celsius)\b", re.IGNORECASE),
        _numeric_with_unit("value", "unit", normalize_temperature),
        0.92,
    ),
    PatternSpec(
        "pressure",
        re.compile(r"\b(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>bar|atm|Pa)\b", re.IGNORECASE),
        _numeric_with_unit("value", "unit", normalize_pressure),
        0.92,
    ),
    PatternSpec(
        "time_step",
        re.compile(
            r"\b(?:time[- ]?step|integration step)(?:\s+(?:of|was|=))?\s*"
            r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>fs|ps|ns|us|µs|μs)\b",
            re.IGNORECASE,
        ),
        _numeric_with_unit("value", "unit", normalize_time_step),
        0.98,
    ),
    PatternSpec(
        "simulation_duration",
        re.compile(
            r"\b(?:production(?:\s+simulation)?|simulation|trajectory|run)(?:s)?"
            r"(?:\s+(?:of|for|was|were|lasting))?\s*"
            r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>ps|ns|us|µs|μs)\b",
            re.IGNORECASE,
        ),
        _numeric_with_unit("value", "unit", normalize_duration),
        0.90,
    ),
    PatternSpec(
        "replicates",
        re.compile(
            r"\b(?P<value>\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
            r"(?:independent\s+)?(?:replicates|replicas)\b",
            re.IGNORECASE,
        ),
        lambda m: (
            int(m.group("value"))
            if m.group("value").isdigit()
            else {
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
            }[m.group("value").lower()],
            None,
        ),
        0.98,
    ),
    PatternSpec(
        "pdb_id",
        re.compile(
            r"\bPDB(?:\s+ID|\s+entry)?\s*[:#]?\s*(?P<value>[0-9][A-Za-z0-9]{3})\b", re.IGNORECASE
        ),
        lambda m: (m.group("value").upper(), None),
        0.99,
    ),
    PatternSpec(
        "uniprot_accession",
        re.compile(
            r"\bUniProt(?:KB)?(?:\s+accession)?\s*[:#]?\s*"
            r"(?P<value>(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2}))\b",
            re.IGNORECASE,
        ),
        lambda m: (m.group("value").upper(), None),
        0.99,
    ),
]


class DeterministicExtractor:
    method_name = "deterministic_baseline_v1"

    def extract(
        self, paragraphs: list[Paragraph], document_id: str, source_uri: str
    ) -> list[ExtractedFact]:
        facts: list[ExtractedFact] = []
        seen: set[tuple[str, str, str | None, str]] = set()
        for paragraph in paragraphs:
            digest = hashlib.sha256(paragraph.text.encode("utf-8")).hexdigest()
            for spec in PATTERNS:
                for match in spec.pattern.finditer(paragraph.text):
                    normalized_value, unit = spec.normalizer(match)
                    raw = match.group(0)
                    evidence = EvidenceSpan(
                        document_id=document_id,
                        source_uri=source_uri,
                        section=paragraph.section,
                        paragraph_id=paragraph.paragraph_id,
                        start_char=match.start(),
                        end_char=match.end(),
                        quote=raw,
                        context_sha256=digest,
                    )
                    dedup_key = (
                        spec.field_name,
                        str(normalized_value),
                        unit,
                        paragraph.paragraph_id,
                    )
                    if dedup_key in seen:
                        continue
                    seen.add(dedup_key)
                    facts.append(
                        ExtractedFact(
                            field_name=spec.field_name,
                            raw_value=raw,
                            normalized_value=normalized_value,
                            unit=unit,
                            method=self.method_name,
                            confidence=spec.confidence,
                            evidence=[evidence],
                        )
                    )
        return facts
