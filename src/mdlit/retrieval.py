from __future__ import annotations

from dataclasses import dataclass

from .jats import Paragraph

POSITIVE_SECTION_TERMS = {
    "molecular dynamics": 6,
    "md simulation": 6,
    "simulation methods": 5,
    "computational methods": 4,
    "methods": 2,
    "materials and methods": 2,
    "system preparation": 4,
    "simulation setup": 5,
}
PROTOCOL_TERMS = {
    "gromacs": 3,
    "namd": 3,
    "openmm": 3,
    "amber": 2,
    "charmm": 2,
    "desmond": 3,
    "force field": 3,
    "water model": 3,
    "time step": 3,
    "timestep": 3,
    "ensemble": 2,
    "equilibrat": 2,
    "production": 2,
    "thermostat": 2,
    "barostat": 2,
    "periodic boundary": 2,
}
NEGATIVE_TERMS = {
    "cell culture": -6,
    "incubat": -4,
    "electrophysiological": -4,
    "assay": -3,
    "experimental protocol": -2,
}


@dataclass(frozen=True)
class ParagraphSelection:
    paragraph: Paragraph
    score: int
    reasons: tuple[str, ...]


def score_protocol_paragraph(paragraph: Paragraph) -> ParagraphSelection:
    section = paragraph.section.lower()
    text = paragraph.text.lower()
    score = 0
    reasons: list[str] = []

    for term, weight in POSITIVE_SECTION_TERMS.items():
        if term in section:
            score += weight
            reasons.append(f"section:{term}:{weight:+d}")
    for term, weight in PROTOCOL_TERMS.items():
        if term in text:
            score += weight
            reasons.append(f"text:{term}:{weight:+d}")
    for term, weight in NEGATIVE_TERMS.items():
        if term in text and not any(x in section for x in ("molecular dynamics", "simulation")):
            score += weight
            reasons.append(f"negative:{term}:{weight:+d}")

    return ParagraphSelection(paragraph=paragraph, score=score, reasons=tuple(reasons))


def select_protocol_paragraphs(
    paragraphs: list[Paragraph], threshold: int = 4
) -> list[ParagraphSelection]:
    selections = [score_protocol_paragraph(paragraph) for paragraph in paragraphs]
    return [selection for selection in selections if selection.score >= threshold]
