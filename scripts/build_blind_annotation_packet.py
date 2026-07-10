from __future__ import annotations

import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from mdmeta.benchmark import canonical_sha256

METHOD_TITLE = re.compile(
    r"method|simulation|computational|molecular dynamics|system preparation|model(?:ing|ling)|docking",
    re.IGNORECASE,
)
MD_SIGNAL = re.compile(r"\bmolecular dynamics\b|\bMD simulations?\b", re.IGNORECASE)
PROTOCOL_SIGNALS = (
    re.compile(r"\bGROMACS\b|\bAMBER(?:TOOLS)?\b|\bNAMD\b|\bOpenMM\b|\bCHARMM\b|\bDesmond\b", re.IGNORECASE),
    re.compile(r"\bforce field\b|\bCHARMM\d|\bff\d{2}SB\b|\bOPLS\b|\bAMBER\d+SB\b", re.IGNORECASE),
    re.compile(r"\bTIP[345]P\b|\bSPC(?:/E)?\b|\bwater model\b", re.IGNORECASE),
    re.compile(r"\bNPT\b|\bNVT\b|\bNVE\b|\bNPAT\b|\bNPH\b", re.IGNORECASE),
    re.compile(r"\b\d+(?:\.\d+)?\s*(?:fs|ps|ns|us|µs|μs|ms|K|bar|atm)\b", re.IGNORECASE),
    re.compile(r"\bequilibrat|\bproduction\s+(?:MD|simulation|run)|\bminimi[sz]|\bheating\b", re.IGNORECASE),
)


def _text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return " ".join(part.strip() for part in node.itertext() if part.strip())


def _paragraphs(section: ET.Element, section_index: int) -> list[dict]:
    rows: list[dict] = []
    section_title = _text(section.find("./title")) or f"section-{section_index}"
    for paragraph_index, node in enumerate(section.findall("./p"), start=1):
        text = _text(node)
        if not text:
            continue
        paragraph_id = node.attrib.get("id") or f"sec-{section_index}-p-{paragraph_index}"
        rows.append(
            {
                "paragraph_id": paragraph_id,
                "section": section_title,
                "text": text,
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "character_count": len(text),
            }
        )
    return rows


def _protocol_rich(section_text: str) -> bool:
    if MD_SIGNAL.search(section_text) is None:
        return False
    return sum(pattern.search(section_text) is not None for pattern in PROTOCOL_SIGNALS) >= 2


def build_packet(plan: dict, screen: dict, xml_cache_dir: Path) -> dict:
    if plan["screen_sha256"] != canonical_sha256(screen):
        raise ValueError("final plan does not match the supplied full-text screen")
    screen_records = {row["document_id"]: row for row in screen["records"]}
    articles: list[dict] = []
    for split in ("development", "validation", "locked_test"):
        for article in plan[split]:
            document_id = article["document_id"]
            record = screen_records.get(document_id)
            if record is None:
                raise ValueError(f"missing screen record for {document_id}")
            xml_path = xml_cache_dir / f"{document_id.upper()}.xml"
            xml_bytes = xml_path.read_bytes()
            digest = hashlib.sha256(xml_bytes).hexdigest()
            if digest != record["full_text_sha256"]:
                raise ValueError(f"source hash mismatch for {document_id}")
            root = ET.fromstring(xml_bytes)
            abstract = _text(root.find(".//abstract"))
            method_sections: list[dict] = []
            for section_index, section in enumerate(root.findall(".//body//sec"), start=1):
                section_title = _text(section.find("./title"))
                section_text = _text(section)
                selected_by_title = METHOD_TITLE.search(section_title) is not None
                selected_by_protocol = _protocol_rich(section_text)
                if not selected_by_title and not selected_by_protocol:
                    continue
                paragraphs = _paragraphs(section, section_index)
                if paragraphs:
                    method_sections.append(
                        {
                            "section": section_title or f"section-{section_index}",
                            "selection_reason": (
                                "method_like_title"
                                if selected_by_title
                                else "protocol_rich_section_text"
                            ),
                            "paragraphs": paragraphs,
                        }
                    )
            articles.append(
                {
                    "document_id": document_id,
                    "split": split,
                    "title": _text(root.find(".//article-title")) or article["title"],
                    "doi": article.get("doi"),
                    "year": article.get("year"),
                    "source_uri": article["source_uri"],
                    "article_type": root.attrib.get("article-type"),
                    "source_sha256": digest,
                    "abstract": abstract,
                    "method_sections": method_sections,
                    "method_paragraph_count": sum(
                        len(section["paragraphs"]) for section in method_sections
                    ),
                    "eligibility": "unreviewed",
                    "eligibility_reason": None,
                    "annotation_status": "unreviewed",
                }
            )
    core = {
        "study_status": plan["study_status"],
        "plan_sha256": plan["plan_sha256"],
        "screen_sha256": plan["screen_sha256"],
        "packet_scope": "blinded_ai_annotation_input",
        "source_policy": "same_runner_ephemeral_jats_cache",
        "contains_machine_predictions": False,
        "contains_full_article_xml": False,
        "article_count": len(articles),
        "articles": articles,
    }
    return {**core, "packet_sha256": canonical_sha256(core)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a blinded article reading packet.")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--screen", type=Path, required=True)
    parser.add_argument("--xml-cache-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    screen = json.loads(args.screen.read_text(encoding="utf-8"))
    packet = build_packet(plan, screen, args.xml_cache_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(packet, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "article_count": packet["article_count"],
                "packet_sha256": packet["packet_sha256"],
                "contains_machine_predictions": packet["contains_machine_predictions"],
                "contains_full_article_xml": packet["contains_full_article_xml"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
