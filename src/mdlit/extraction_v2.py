from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .extraction import DeterministicExtractor
from .jats import Paragraph
from .models import EvidenceSpan, ExtractedFact, FieldName, ProtocolPhase
from .normalization import (
    format_number,
    normalize_duration,
    normalize_pressure,
    normalize_temperature,
    normalize_time_step,
    parse_number,
)
from .protocol import infer_phase
from .retrieval import select_protocol_paragraphs

PROGRAM_RE = re.compile(r"\b(GROMACS|NAMD|OpenMM|Desmond|CHARMM|AMBER)\b", re.IGNORECASE)
PROGRAM_VERSION_RE = re.compile(
    r"\b(?P<program>GROMACS|NAMD|OpenMM|Desmond|CHARMM|AMBER)\s*"
    r"(?:version\s*)?(?P<version>(?:c\d+[a-z]\d+)|(?:\d+(?:\.\d+){0,2}))\b",
    re.IGNORECASE,
)
FORCE_FIELD_RE = re.compile(
    r"\b(?P<value>CHARMM(?:22(?:/CMAP)?|27|36m?|36)|"
    r"(?:AMBER\s*)?(?:ff99SB(?:-ILDN)?|ff14SB|ff19SB|GAFF2?|Lipid\d+)|"
    r"OPLS(?:\d+e|3e|-AA/M|-AA)?|Martini\s*(?:2(?:\.\d+)?|3)|"
    r"Generalized\s+Amber\s+Force\s+Field\s*\((?:GAFF2?|gaff2?)\))\b",
    re.IGNORECASE,
)
WATER_RE = re.compile(
    r"\b(?P<value>TIP3P|TPI3P|TIP4P(?:-Ew|/2005)?|TIP5P|SPC/E|SPCE|SPC|OPC3?|TIP3P-FB)\b",
    re.IGNORECASE,
)
ENSEMBLE_RE = re.compile(r"\b(?P<value>NPT|NVT|NVE)\s*(?:ensemble|conditions?)?\b", re.IGNORECASE)
TEMPERATURE_RE = re.compile(
    r"\b(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>K|kelvin|°C|Celsius)\b", re.IGNORECASE
)
PRESSURE_RE = re.compile(r"\b(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>bar|atm|Pa)\b", re.IGNORECASE)
TIME_STEP_RE = re.compile(
    r"\b(?:time[- ]?step|integration\s+(?:time\s*)?step|step size)"
    r"(?:\s+(?:of|was|=|set to))?\s*(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>fs|ps|ns|us|µs|μs)\b",
    re.IGNORECASE,
)
DURATION_PATTERNS = [
    re.compile(
        r"\b(?P<prefix>production|equilibration|equilibrated|heating|heated|simulation|simulations|"
        r"trajectory|trajectories|run|runs|analysis window|last|final)\b[^.;]{0,45}?"
        r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>ps|ns|us|µs|μs)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<value>\d+(?:\.\d+)?)\s*[- ]?(?P<unit>ps|ns|us|µs|μs)\s*"
        r"(?P<prefix>production|equilibration|MD|molecular dynamics|simulation|trajectory|run)s?\b",
        re.IGNORECASE,
    ),
]
WRITTEN_HUNDRED_DURATION_RE = re.compile(
    r"\b(?:a|one)\s+hundred\s+(?P<unit>ps|nanoseconds?|ns|microseconds?|us|µs|μs)\s*"
    r"(?:MD|molecular dynamics|simulation|trajectory|run)s?\b",
    re.IGNORECASE,
)
REPLICATE_RE = re.compile(
    r"\b(?P<value>\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
    r"(?:independent\s+)?(?:(?:production\s+)?simulations?|replicates|replicas|runs)\b",
    re.IGNORECASE,
)
PDB_RE = re.compile(
    r"\b(?:PDB(?:\s+ID|\s+entry|\s+code)?\s*[:#]?\s*)(?P<value>[0-9][A-Za-z0-9]{3})\b",
    re.IGNORECASE,
)
UNIPROT_RE = re.compile(
    r"\bUniProt(?:KB)?(?:\s+accession)?\s*[:#]?\s*"
    r"(?P<value>(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2}))\b",
    re.IGNORECASE,
)

NUMBER_WORDS = {
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


@dataclass(frozen=True)
class Candidate:
    field_name: FieldName
    match: re.Match[str]
    value: str | int | float
    unit: str | None
    confidence: float
    phase: ProtocolPhase | None = None


def _program_value(value: str) -> str:
    if value.lower() == "openmm":
        return "OpenMM"
    if value.lower() == "desmond":
        return "DESMOND"
    return value.upper()


def _normalise_force_field(raw: str) -> str:
    compact = re.sub(r"\s+", " ", raw).strip()
    upper = compact.upper()
    if "GENERALIZED AMBER" in upper:
        match = re.search(r"GAFF2?", upper)
        return match.group(0) if match else "GAFF"
    aliases = {
        "AMBER FF99SB-ILDN": "ff99SB-ILDN",
        "AMBER FF14SB": "ff14SB",
        "AMBER FF19SB": "ff19SB",
        "SPCE": "SPC/E",
    }
    return aliases.get(upper, compact)


def _normalise_water(raw: str) -> str:
    value = raw.upper()
    return "SPC/E" if value == "SPCE" else value


def _local_window(text: str, match: re.Match[str], left: int = 100, right: int = 100) -> str:
    return text[max(0, match.start() - left) : min(len(text), match.end() + right)]


def _reject_program(text: str, match: re.Match[str]) -> bool:
    value = match.group(0).upper()
    window = _local_window(text, match, 50, 70).lower()
    after = text[match.end() : match.end() + 8].lower()
    if value == "CHARMM" and after.startswith("-gui"):
        return True
    if value == "AMBER":
        force_field_context = any(
            term in window for term in ("force field", "ff14sb", "ff19sb", "gaff")
        )
        engine_context = any(
            term in window
            for term in (
                "software",
                "package",
                "program",
                "executed using",
                "performed using",
                "ambertools",
            )
        )
        if force_field_context and not engine_context:
            return True
    return False


def _reject_temperature(text: str, match: re.Match[str]) -> bool:
    window = _local_window(text, match, 100, 100).lower()
    negative = ("cell", "culture", "incubat", "assay", "electrophysi", "room temperature")
    positive = (
        "simulation",
        "ensemble",
        "thermostat",
        "equilibrat",
        "production",
        "heated",
        "temperature coupling",
        "npt",
        "nvt",
    )
    return any(term in window for term in negative) and not any(term in window for term in positive)


def _fact_from_candidate(
    candidate: Candidate,
    paragraph: Paragraph,
    document_id: str,
    source_uri: str,
    method: str,
) -> ExtractedFact:
    match = candidate.match
    digest = hashlib.sha256(paragraph.text.encode("utf-8")).hexdigest()
    evidence = EvidenceSpan(
        document_id=document_id,
        source_uri=source_uri,
        section=paragraph.section,
        paragraph_id=paragraph.paragraph_id,
        start_char=match.start(),
        end_char=match.end(),
        quote=match.group(0),
        context_sha256=digest,
    )
    return ExtractedFact(
        field_name=candidate.field_name,
        raw_value=match.group(0),
        normalized_value=candidate.value,
        unit=candidate.unit,
        phase=candidate.phase,
        method=method,
        confidence=candidate.confidence,
        evidence=[evidence],
    )


class ProtocolAwareExtractor:
    """Deterministic v2 extractor with protocol retrieval and phase assignment."""

    method_name = "deterministic_protocol_v2"

    def _candidates(self, paragraph: Paragraph, include_protocol: bool) -> list[Candidate]:
        text = paragraph.text
        candidates: list[Candidate] = []

        for match in PDB_RE.finditer(text):
            candidates.append(Candidate("pdb_id", match, match.group("value").upper(), None, 0.99))
        for match in UNIPROT_RE.finditer(text):
            candidates.append(
                Candidate("uniprot_accession", match, match.group("value").upper(), None, 0.99)
            )
        if not include_protocol:
            return candidates

        version_spans: set[tuple[int, int]] = set()
        for match in PROGRAM_VERSION_RE.finditer(text):
            program_match = re.match(r"\w+", match.group(0))
            if program_match is None:
                continue
            if PROGRAM_RE.fullmatch(program_match.group(0)) is None or _reject_program(text, match):
                continue
            program = _program_value(match.group("program"))
            candidates.append(Candidate("program", match, program, None, 0.97))
            candidates.append(
                Candidate("program_version", match, match.group("version"), None, 0.95)
            )
            version_spans.add((match.start(), match.end()))
        for match in PROGRAM_RE.finditer(text):
            if any(start <= match.start() < end for start, end in version_spans):
                continue
            if _reject_program(text, match):
                continue
            candidates.append(
                Candidate("program", match, _program_value(match.group(0)), None, 0.96)
            )

        for match in FORCE_FIELD_RE.finditer(text):
            candidates.append(
                Candidate(
                    "force_field", match, _normalise_force_field(match.group("value")), None, 0.97
                )
            )
        for match in WATER_RE.finditer(text):
            candidates.append(
                Candidate("water_model", match, _normalise_water(match.group("value")), None, 0.97)
            )
        for match in ENSEMBLE_RE.finditer(text):
            phase = infer_phase(text, match.start(), match.end())
            candidates.append(
                Candidate("ensemble", match, match.group("value").upper(), None, 0.98, phase)
            )
        for match in TEMPERATURE_RE.finditer(text):
            if _reject_temperature(text, match):
                continue
            value, unit = normalize_temperature(
                parse_number(match.group("value")), match.group("unit")
            )
            phase = infer_phase(text, match.start(), match.end())
            candidates.append(
                Candidate("temperature", match, format_number(value), unit, 0.91, phase)
            )
        for match in PRESSURE_RE.finditer(text):
            value, unit = normalize_pressure(
                parse_number(match.group("value")), match.group("unit")
            )
            phase = infer_phase(text, match.start(), match.end())
            candidates.append(Candidate("pressure", match, format_number(value), unit, 0.93, phase))
        for match in TIME_STEP_RE.finditer(text):
            value, unit = normalize_time_step(
                parse_number(match.group("value")), match.group("unit")
            )
            phase = infer_phase(text, match.start(), match.end())
            candidates.append(
                Candidate("time_step", match, format_number(value), unit, 0.98, phase)
            )
        for pattern in DURATION_PATTERNS:
            for match in pattern.finditer(text):
                window = _local_window(text, match, 20, 20).lower()
                if "every" in window:
                    continue
                value, unit = normalize_duration(
                    parse_number(match.group("value")), match.group("unit")
                )
                phase = infer_phase(text, match.start(), match.end())
                candidates.append(
                    Candidate("simulation_duration", match, format_number(value), unit, 0.90, phase)
                )
        for match in WRITTEN_HUNDRED_DURATION_RE.finditer(text):
            unit_raw = match.group("unit").lower()
            unit_alias = {
                "nanosecond": "ns",
                "nanoseconds": "ns",
                "microsecond": "us",
                "microseconds": "us",
            }.get(unit_raw, unit_raw)
            value, unit = normalize_duration(100.0, unit_alias)
            phase = infer_phase(text, match.start(), match.end())
            if phase == "unspecified":
                phase = "production"
            candidates.append(
                Candidate("simulation_duration", match, format_number(value), unit, 0.88, phase)
            )
        for match in REPLICATE_RE.finditer(text):
            raw = match.group("value").lower()
            value = int(raw) if raw.isdigit() else NUMBER_WORDS[raw]
            window = _local_window(text, match, 80, 80).lower()
            if not any(term in window for term in ("simulation", "trajectory", "md", "production")):
                continue
            phase = infer_phase(text, match.start(), match.end())
            candidates.append(Candidate("replicates", match, value, None, 0.96, phase))
        return candidates

    @staticmethod
    def _assign_contextual_phases(facts: list[ExtractedFact], paragraphs: list[Paragraph]) -> None:
        paragraph_map = {paragraph.paragraph_id: paragraph for paragraph in paragraphs}
        by_paragraph: dict[str, list[ExtractedFact]] = {}
        for fact in facts:
            by_paragraph.setdefault(fact.evidence[0].paragraph_id, []).append(fact)

        for paragraph_id, paragraph_facts in by_paragraph.items():
            paragraph = paragraph_map[paragraph_id]
            explicit = [fact for fact in paragraph_facts if fact.phase not in {None, "unspecified"}]
            for fact in paragraph_facts:
                if fact.phase not in {None, "unspecified"}:
                    continue
                if explicit:
                    nearest = min(
                        explicit,
                        key=lambda other: abs(
                            other.evidence[0].start_char - fact.evidence[0].start_char
                        ),
                    )
                    if abs(
                        nearest.evidence[0].start_char - fact.evidence[0].start_char
                    ) <= 260 and fact.field_name in {
                        "simulation_duration",
                        "temperature",
                        "pressure",
                        "ensemble",
                        "time_step",
                        "replicates",
                    }:
                        fact.phase = nearest.phase
                        continue
                text_lower = paragraph.text.lower()
                section_lower = paragraph.section.lower()
                if fact.field_name == "simulation_duration":
                    if any(term in text_lower for term in ("revealed", "showed", "demonstrated")):
                        fact.phase = "reported_result"
                    elif "equilibr" not in text_lower and "heat" not in text_lower:
                        fact.phase = "production"
                elif (
                    fact.field_name
                    in {"temperature", "pressure", "ensemble", "time_step", "replicates"}
                    and any(
                        term in section_lower
                        for term in ("molecular dynamics", "md simulation", "simulation")
                    )
                    and "equilibr" not in text_lower
                ):
                    fact.phase = "production"

        section_has_production: set[str] = set()
        for fact in facts:
            paragraph = paragraph_map[fact.evidence[0].paragraph_id]
            if fact.phase == "production":
                section_has_production.add(paragraph.section)
        for fact in facts:
            if fact.phase not in {None, "unspecified"}:
                continue
            paragraph = paragraph_map[fact.evidence[0].paragraph_id]
            if (
                paragraph.section in section_has_production
                and fact.field_name
                in {"temperature", "pressure", "ensemble", "time_step", "replicates"}
                and not any(
                    term in paragraph.text.lower() for term in ("equilibr", "heat", "initial")
                )
            ):
                fact.phase = "production"

    def extract(
        self, paragraphs: list[Paragraph], document_id: str, source_uri: str
    ) -> list[ExtractedFact]:
        selected_ids = {
            selection.paragraph.paragraph_id for selection in select_protocol_paragraphs(paragraphs)
        }
        facts: list[ExtractedFact] = []
        seen: set[tuple[str, str, str | None, str, str | None]] = set()
        for paragraph in paragraphs:
            candidates = self._candidates(
                paragraph, include_protocol=paragraph.paragraph_id in selected_ids
            )
            for candidate in candidates:
                key = (
                    candidate.field_name,
                    str(candidate.value),
                    candidate.unit,
                    paragraph.paragraph_id,
                    candidate.phase,
                )
                if key in seen:
                    continue
                seen.add(key)
                facts.append(
                    _fact_from_candidate(
                        candidate, paragraph, document_id, source_uri, self.method_name
                    )
                )
        self._assign_contextual_phases(facts, paragraphs)
        return sorted(
            facts,
            key=lambda fact: (
                fact.evidence[0].paragraph_id,
                fact.evidence[0].start_char,
                fact.field_name,
            ),
        )


class HybridExtractor:
    """Select the transparent v1 baseline or the protocol-aware v2 extractor."""

    def __init__(self, version: str = "v2") -> None:
        self.extractor = ProtocolAwareExtractor() if version == "v2" else DeterministicExtractor()

    def extract(
        self, paragraphs: list[Paragraph], document_id: str, source_uri: str
    ) -> list[ExtractedFact]:
        return self.extractor.extract(paragraphs, document_id, source_uri)
