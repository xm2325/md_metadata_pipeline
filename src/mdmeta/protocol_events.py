from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .models import EventType, Evidence, ProtocolEvent

_DURATION = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>fs|ps|ns|µs|μs|us|ms)\b", re.I)
_TEMPERATURE = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*K\b", re.I)
_PRESSURE = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>bar|atm)\b", re.I)
_TIMESTEP = re.compile(
    r"(?:(?:time\s*step|timestep|integration step)[^.;]{0,35}?(?P<value1>\d+(?:\.\d+)?)\s*(?P<unit1>fs|ps)|(?P<value2>\d+(?:\.\d+)?)\s*(?P<unit2>fs|ps)[^.;]{0,20}?(?:time\s*step|timestep|integration step))",
    re.I,
)
_REPLICATES = re.compile(
    r"(?P<value>\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:independent\s+)?(?:replicates|runs|simulations)\b",
    re.I,
)
_NUMBER_WORDS = {
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
_PHASE_PATTERNS = [
    (EventType.MINIMISATION, re.compile(r"minimi[sz]", re.I)),
    (EventType.HEATING, re.compile(r"heat(?:ed|ing)?|ramp(?:ed|ing)?", re.I)),
    (EventType.EQUILIBRATION, re.compile(r"equilibrat", re.I)),
    (
        EventType.PRODUCTION,
        re.compile(r"production|unrestrained\s+(?:md|simulation)|md\s+run", re.I),
    ),
    (
        EventType.ANALYSIS_WINDOW,
        re.compile(r"last\s+\d|final\s+\d|used for (?:further )?analys", re.I),
    ),
    (
        EventType.SAMPLING_INTERVAL,
        re.compile(r"saved|written|recorded|sampled|output", re.I),
    ),
]
_UNIT_TO_PS = {
    "fs": 1e-3,
    "ps": 1.0,
    "ns": 1e3,
    "us": 1e6,
    "µs": 1e6,
    "μs": 1e6,
    "ms": 1e9,
}


@dataclass(frozen=True)
class Paragraph:
    document_id: str
    section: str
    paragraph_id: str
    text: str


def _phase(text: str, start: int, end: int) -> EventType:
    window_start = max(0, start - 100)
    window = text[window_start : min(len(text), end + 100)]
    matches: list[tuple[int, EventType]] = []
    for event_type, pattern in _PHASE_PATTERNS:
        for match in pattern.finditer(window):
            centre = (match.start() + match.end()) // 2 + window_start
            matches.append((abs(centre - ((start + end) // 2)), event_type))
    return min(matches, default=(10**9, EventType.UNKNOWN))[1]


def _evidence(paragraph: Paragraph, start: int, end: int) -> Evidence:
    return Evidence(
        document_id=paragraph.document_id,
        section=paragraph.section,
        paragraph_id=paragraph.paragraph_id,
        quote=paragraph.text[start:end],
        start_char=start,
        end_char=end,
        context_sha256=hashlib.sha256(paragraph.text.encode()).hexdigest(),
    )


def extract_protocol_events(paragraph: Paragraph) -> list[ProtocolEvent]:
    """Extract duration-anchored protocol events from one evidence paragraph.

    Conditions are linked only when they occur within 180 characters of the
    duration anchor. A time-step expression is never emitted as a duration event.
    """
    events: list[ProtocolEvent] = []
    event_index = 0
    for duration in _DURATION.finditer(paragraph.text):
        start, end = duration.span()
        prefix = paragraph.text[max(0, start - 32) : start].lower()
        suffix = paragraph.text[end : min(len(paragraph.text), end + 24)].lower()
        if re.search(r"(?:time\s*step|timestep|integration step)[^.;]{0,24}$", prefix):
            continue
        if re.match(r"\s*(?:time\s*step|timestep|integration step)", suffix):
            continue

        event_type = _phase(paragraph.text, start, end)
        if event_type is EventType.UNKNOWN:
            context = paragraph.text[max(0, start - 80) : min(len(paragraph.text), end + 80)]
            if not any(token in context.lower() for token in ("simulation", "dynamics", "trajectory", "md ")):
                continue

        left, right = max(0, start - 180), min(len(paragraph.text), end + 180)
        local = paragraph.text[left:right]

        def nearest(pattern: re.Pattern[str]):
            candidates = list(pattern.finditer(local))
            return min(candidates, key=lambda item: abs((left + item.start()) - start)) if candidates else None

        temperature = nearest(_TEMPERATURE)
        pressure = nearest(_PRESSURE)
        timestep = nearest(_TIMESTEP)
        replicates = nearest(_REPLICATES)
        ensemble_match = re.search(r"\b(NVE|NVT|NPT|NPAT|NPH)\b", local, re.I)

        unit = duration.group("unit").lower()
        duration_ps = float(duration.group("value")) * _UNIT_TO_PS[unit]
        pressure_bar = None
        if pressure:
            pressure_bar = float(pressure.group("value"))
            if pressure.group("unit").lower() == "atm":
                pressure_bar *= 1.01325
        timestep_fs = None
        if timestep:
            timestep_value = timestep.group("value1") or timestep.group("value2")
            timestep_unit = timestep.group("unit1") or timestep.group("unit2")
            timestep_fs = float(timestep_value)
            if timestep_unit.lower() == "ps":
                timestep_fs *= 1000
        replicate_count = None
        if replicates:
            token = replicates.group("value").lower()
            replicate_count = int(token) if token.isdigit() else _NUMBER_WORDS[token]

        event_index += 1
        events.append(
            ProtocolEvent(
                event_id=f"{paragraph.document_id}:{paragraph.paragraph_id}:event-{event_index}",
                event_type=event_type,
                duration_ps=duration_ps,
                temperature_k=float(temperature.group("value")) if temperature else None,
                pressure_bar=pressure_bar,
                timestep_fs=timestep_fs,
                ensemble=ensemble_match.group(1).upper() if ensemble_match else None,
                replicates=replicate_count,
                evidence=[_evidence(paragraph, start, end)],
                relation_method="same_paragraph_nearest_within_180_chars",
                confidence=0.92 if event_type is not EventType.UNKNOWN else 0.65,
            )
        )
    return events
