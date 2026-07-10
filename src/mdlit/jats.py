from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lxml import etree


@dataclass(frozen=True)
class Paragraph:
    section: str
    paragraph_id: str
    text: str


@dataclass(frozen=True)
class ParsedArticle:
    title: str | None
    doi: str | None
    pmcid: str | None
    paragraphs: list[Paragraph]


def _plain_text(node: etree._Element) -> str:
    return " ".join("".join(node.itertext()).split())


def parse_jats(path: str | Path) -> ParsedArticle:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
    tree = etree.parse(str(path), parser)
    root = tree.getroot()

    title_node = root.find(".//article-title")
    title = _plain_text(title_node) if title_node is not None else None

    doi = None
    pmcid = None
    for node in root.findall(".//article-id"):
        id_type = (node.get("pub-id-type") or "").lower()
        value = _plain_text(node)
        if id_type == "doi":
            doi = value
        elif id_type in {"pmc", "pmcid"}:
            pmcid = value if value.startswith("PMC") else f"PMC{value}"

    paragraphs: list[Paragraph] = []
    for sec_index, sec in enumerate(root.findall(".//body//sec"), start=1):
        title_element = sec.find("./title")
        section_title = (
            _plain_text(title_element) if title_element is not None else f"section-{sec_index}"
        )
        for p_index, paragraph in enumerate(sec.findall("./p"), start=1):
            text = _plain_text(paragraph)
            if text:
                paragraph_id = paragraph.get("id") or f"sec-{sec_index}-p-{p_index}"
                paragraphs.append(Paragraph(section_title, paragraph_id, text))

    if not paragraphs:
        for p_index, paragraph in enumerate(root.findall(".//body//p"), start=1):
            text = _plain_text(paragraph)
            if text:
                paragraphs.append(Paragraph("body", f"body-p-{p_index}", text))

    return ParsedArticle(title=title, doi=doi, pmcid=pmcid, paragraphs=paragraphs)
