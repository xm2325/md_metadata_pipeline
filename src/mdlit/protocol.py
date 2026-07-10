from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from .models import ExtractedFact, ProtocolEvent, ProtocolPhase, ValidationEvent

PHASE_PATTERNS: list[tuple[ProtocolPhase, re.Pattern[str]]] = [
    (
        "initialization",
        re.compile(r"\b(?:initiali[sz](?:e|ed|ation)|initial velocities)\b", re.IGNORECASE),
    ),
    ("minimisation", re.compile(r"\bminimi[sz](?:e|ed|ation|ing)\b", re.IGNORECASE)),
    (
        "heating",
        re.compile(r"\b(?:heat(?:ed|ing)?|temperature (?:increase|ramp))\b", re.IGNORECASE),
    ),
    (
        "equilibration",
        re.compile(r"\b(?:equilibrat(?:e|ed|ion|ing)|thermodynamic equilibrium)\b", re.IGNORECASE),
    ),
    (
        "production",
        re.compile(
            r"\b(?:production|unrestrained|final simulation step|third step)\b", re.IGNORECASE
        ),
    ),
    (
        "sampling_interval",
        re.compile(
            r"\b(?:saved|written|recorded|sampled|frame|snapshot).*?\bevery\b", re.IGNORECASE
        ),
    ),
    (
        "analysis_window",
        re.compile(r"\b(?:last|final|first)\s+\d+(?:\.\d+)?\s*(?:ps|ns|[µμu]s)\b", re.IGNORECASE),
    ),
    (
        "reported_result",
        re.compile(
            r"\b(?:simulations? conducted over|simulations? of).*?\b(?:revealed|showed|demonstrated)\b",
            re.IGNORECASE,
        ),
    ),
]


def _sentence_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    left = max(text.rfind(".", 0, start), text.rfind(";", 0, start), text.rfind("\n", 0, start))
    right_candidates = [
        index
        for index in (text.find(".", end), text.find(";", end), text.find("\n", end))
        if index >= 0
    ]
    right = min(right_candidates) if right_candidates else len(text)
    return left + 1, right


def infer_phase(text: str, start: int, end: int) -> ProtocolPhase:
    sentence_start, sentence_end = _sentence_bounds(text, start, end)
    sentence = text[sentence_start:sentence_end]
    matches: list[tuple[int, ProtocolPhase]] = []
    for phase, pattern in PHASE_PATTERNS:
        for match in pattern.finditer(sentence):
            absolute = sentence_start + match.start()
            distance = min(abs(absolute - start), abs(absolute - end))
            matches.append((distance, phase))
    if matches:
        return min(matches, key=lambda item: item[0])[1]

    wider_start = max(0, start - 220)
    wider_end = min(len(text), end + 160)
    wider = text[wider_start:wider_end]
    for phase, pattern in PHASE_PATTERNS:
        for match in pattern.finditer(wider):
            absolute = wider_start + match.start()
            distance = min(abs(absolute - start), abs(absolute - end))
            matches.append((distance, phase))
    return min(matches, default=(10**9, "unspecified"), key=lambda item: item[0])[1]


def build_protocol_events(facts: list[ExtractedFact]) -> list[ProtocolEvent]:
    """Construct phase-aware events without copying values across paragraphs.

    Duration facts are event anchors. If a paragraph has no duration but contains other
    protocol fields, one partial event is created for that paragraph and phase.
    """
    by_paragraph: dict[str, list[ExtractedFact]] = defaultdict(list)
    for fact in facts:
        if fact.field_name in {
            "simulation_duration",
            "temperature",
            "pressure",
            "ensemble",
            "time_step",
            "replicates",
        }:
            by_paragraph[fact.evidence[0].paragraph_id].append(fact)

    events: list[ProtocolEvent] = []
    event_order = 0
    for paragraph_id, paragraph_facts in sorted(
        by_paragraph.items(), key=lambda item: min(f.evidence[0].start_char for f in item[1])
    ):
        anchors = [fact for fact in paragraph_facts if fact.field_name == "simulation_duration"]
        if not anchors:
            anchors = [min(paragraph_facts, key=lambda fact: fact.evidence[0].start_char)]

        for anchor in anchors:
            anchor_ev = anchor.evidence[0]
            phase = anchor.phase or "unspecified"
            nearby = []
            for fact in paragraph_facts:
                ev = fact.evidence[0]
                if fact is anchor or abs(ev.start_char - anchor_ev.start_char) <= 320:
                    if fact.phase in {None, "unspecified", phase} or phase == "unspecified":
                        nearby.append(fact)

            values: dict[str, object] = {}
            for fact in sorted(nearby, key=lambda item: item.confidence, reverse=True):
                values.setdefault(fact.field_name, fact.normalized_value)

            source_ids = [fact.fact_id for fact in nearby if fact.fact_id]
            evidence = []
            seen_evidence: set[tuple[str, int, int]] = set()
            for fact in nearby:
                for ev in fact.evidence:
                    key = (ev.paragraph_id, ev.start_char, ev.end_char)
                    if key not in seen_evidence:
                        seen_evidence.add(key)
                        evidence.append(ev)

            payload = "|".join(
                [
                    anchor_ev.document_id,
                    paragraph_id,
                    str(anchor_ev.start_char),
                    phase,
                    str(values.get("simulation_duration", "")),
                ]
            )
            event_id = f"event-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"
            present = sum(
                values.get(name) is not None
                for name in (
                    "simulation_duration",
                    "temperature",
                    "pressure",
                    "ensemble",
                    "time_step",
                    "replicates",
                )
            )
            completeness = "complete" if present >= 4 and phase != "unspecified" else "partial"
            if phase == "unspecified" and len(anchors) > 1:
                completeness = "ambiguous"

            event = ProtocolEvent(
                event_id=event_id,
                order=event_order,
                phase=phase,
                duration_value=values.get("simulation_duration"),  # type: ignore[arg-type]
                duration_unit="ns" if values.get("simulation_duration") is not None else None,
                temperature_k=values.get("temperature"),  # type: ignore[arg-type]
                pressure_bar=values.get("pressure"),  # type: ignore[arg-type]
                ensemble=str(values["ensemble"]) if values.get("ensemble") is not None else None,
                time_step_ps=values.get("time_step"),  # type: ignore[arg-type]
                replicates=int(values["replicates"])
                if values.get("replicates") is not None
                else None,
                completeness=completeness,  # type: ignore[arg-type]
                source_fact_ids=source_ids,
                evidence=evidence,
            )
            if phase == "unspecified":
                event.validation.append(
                    ValidationEvent(
                        validator="protocol_phase_assignment_v1",
                        status="unresolved",
                        message="No explicit phase term was found near the event anchor.",
                    )
                )
            else:
                event.validation.append(
                    ValidationEvent(
                        validator="protocol_phase_assignment_v1",
                        status="validated",
                        message=f"Phase assigned from local evidence: {phase}",
                    )
                )
            events.append(event)
            event_order += 1
    return events
