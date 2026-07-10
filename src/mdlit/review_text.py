from __future__ import annotations

import re
from pathlib import Path

from .jats import Paragraph

SECTION_RE = re.compile(r"^## SEC \d+:\s*(?P<title>.+?)\s*$", re.MULTILINE)
PARAGRAPH_RE = re.compile(
    r"^\[(?P<label>\d+:\d+)\]\s+id=(?P<id>\S+)\s*\n(?P<text>.*?)(?=\n\n\[\d+:\d+\]|\n\n## SEC|\Z)",
    re.MULTILINE | re.DOTALL,
)


def parse_review_text(path: str | Path) -> tuple[str, str | None, list[Paragraph]]:
    text = Path(path).read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines:
        raise ValueError("review text is empty")
    document_id = lines[0].strip()
    title = lines[1].strip() if len(lines) > 1 and lines[1].strip() else None

    section_positions = [
        (match.start(), match.group("title").strip()) for match in SECTION_RE.finditer(text)
    ]

    def section_for(position: int) -> str:
        current = "body"
        for start, title_value in section_positions:
            if start > position:
                break
            current = title_value
        return current

    paragraphs = []
    for match in PARAGRAPH_RE.finditer(text):
        paragraph_text = " ".join(match.group("text").split())
        paragraphs.append(
            Paragraph(
                section=section_for(match.start()),
                paragraph_id=match.group("id"),
                text=paragraph_text,
            )
        )
    if not paragraphs:
        raise ValueError(f"no review paragraphs parsed from {path}")
    return document_id, title, paragraphs
