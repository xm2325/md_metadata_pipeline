from __future__ import annotations

import argparse
import hashlib
import json
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import httpx

from mdmeta.benchmark import canonical_sha256
from mdmeta.protocol_events import Paragraph, extract_protocol_events

FULLTEXT_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
METHOD_TITLE_TERMS = (
    "method",
    "simulation",
    "computational",
    "molecular dynamics",
    "system preparation",
)


def _text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return " ".join("".join(node.itertext()).split())


def read_cached_xml(cache_dir: Path, document_id: str) -> bytes:
    path = cache_dir / f"{document_id.upper()}.xml"
    if not path.is_file():
        raise FileNotFoundError(f"missing cached JATS snapshot: {path}")
    return path.read_bytes()


def method_paragraphs(document_id: str, xml_bytes: bytes) -> list[Paragraph]:
    root = ET.fromstring(xml_bytes)
    paragraphs: list[Paragraph] = []
    seen: set[tuple[str, str]] = set()
    for section_index, section in enumerate(root.findall(".//body//sec"), start=1):
        section_title = _text(section.find("./title")) or f"section-{section_index}"
        if not any(term in section_title.casefold() for term in METHOD_TITLE_TERMS):
            continue
        for paragraph_index, node in enumerate(section.findall("./p"), start=1):
            text = _text(node)
            if not text:
                continue
            paragraph_id = node.attrib.get("id") or f"sec-{section_index}-p-{paragraph_index}"
            key = (paragraph_id, text)
            if key in seen:
                continue
            seen.add(key)
            paragraphs.append(
                Paragraph(
                    document_id=document_id,
                    section=section_title,
                    paragraph_id=paragraph_id,
                    text=text,
                )
            )
    return paragraphs


def freeze_predictions(
    plan: dict,
    screen: dict,
    fetcher: Callable[[str], bytes],
    *,
    extractor_version: str = "protocol_events_v1",
) -> dict:
    if plan["screen_sha256"] != canonical_sha256(screen):
        raise ValueError("final plan does not match the supplied full-text screen")
    records = {record["document_id"]: record for record in screen["records"]}
    articles: list[dict] = []
    failures: list[dict] = []
    phase_counts: Counter[str] = Counter()
    attribute_counts: Counter[str] = Counter()

    for split in ("development", "validation", "locked_test"):
        for article in plan[split]:
            document_id = article["document_id"]
            screen_record = records.get(document_id)
            if screen_record is None:
                failures.append(
                    {
                        "document_id": document_id,
                        "split": split,
                        "reason": "missing_screen_record",
                    }
                )
                continue
            try:
                xml_bytes = fetcher(document_id)
                digest = hashlib.sha256(xml_bytes).hexdigest()
                if digest != screen_record["full_text_sha256"]:
                    raise ValueError(
                        "full-text SHA-256 changed between screening and prediction freezing"
                    )
                paragraphs = method_paragraphs(document_id, xml_bytes)
                events = [
                    event
                    for paragraph in paragraphs
                    for event in extract_protocol_events(paragraph)
                ]
                for event in events:
                    phase_counts[event.event_type.value] += 1
                    for name in (
                        "duration_ps",
                        "temperature_k",
                        "pressure_bar",
                        "timestep_fs",
                        "ensemble",
                        "restraints",
                        "replicates",
                    ):
                        if getattr(event, name) is not None:
                            attribute_counts[name] += 1
                    for evidence in event.evidence:
                        source = next(
                            paragraph.text
                            for paragraph in paragraphs
                            if paragraph.paragraph_id == evidence.paragraph_id
                        )
                        if source[evidence.start_char : evidence.end_char] != evidence.quote:
                            raise ValueError("event evidence offsets do not reproduce the quote")
                        if (
                            hashlib.sha256(source.encode("utf-8")).hexdigest()
                            != evidence.context_sha256
                        ):
                            raise ValueError(
                                "event evidence context hash does not match the paragraph"
                            )
                articles.append(
                    {
                        "document_id": document_id,
                        "split": split,
                        "source_uri": article["source_uri"],
                        "full_text_sha256": digest,
                        "method_paragraph_count": len(paragraphs),
                        "event_count": len(events),
                        "events": [event.model_dump(mode="json") for event in events],
                    }
                )
            except (httpx.HTTPError, ET.ParseError, OSError, ValueError, StopIteration) as exc:
                failures.append(
                    {
                        "document_id": document_id,
                        "split": split,
                        "reason": type(exc).__name__,
                        "message": str(exc),
                    }
                )

    core = {
        "study_status": plan["study_status"],
        "plan_sha256": plan["plan_sha256"],
        "screen_sha256": plan["screen_sha256"],
        "extractor": extractor_version,
        "accuracy_evaluated": False,
        "human_reference_used": False,
        "blinding_status": "separate_artifact_not_in_human_workpack",
        "source_snapshot_policy": "same_runner_ephemeral_jats_cache",
        "article_count_requested": sum(
            len(plan[split]) for split in ("development", "validation", "locked_test")
        ),
        "article_count_succeeded": len(articles),
        "failure_count": len(failures),
        "event_count": sum(article["event_count"] for article in articles),
        "phase_counts": dict(sorted(phase_counts.items())),
        "attribute_counts": dict(sorted(attribute_counts.items())),
        "articles": articles,
        "failures": failures,
    }
    return {
        **core,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "prediction_sha256": canonical_sha256(core),
    }


def fetch_xml(pmcid: str, client: httpx.Client) -> bytes:
    response = client.get(FULLTEXT_URL.format(pmcid=pmcid))
    response.raise_for_status()
    return response.content


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze deterministic event predictions without exposing them to annotators."
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--screen", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--xml-cache-dir", type=Path)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--delay", type=float, default=0.05)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    screen = json.loads(args.screen.read_text(encoding="utf-8"))

    if args.xml_cache_dir is not None:
        result = freeze_predictions(
            plan,
            screen,
            lambda pmcid: read_cached_xml(args.xml_cache_dir, pmcid),
        )
    else:
        headers = {"User-Agent": "md-metadata-pipeline/0.7 prediction-freeze"}
        with httpx.Client(
            timeout=args.timeout,
            headers=headers,
            follow_redirects=True,
        ) as client:

            def fetcher(pmcid: str) -> bytes:
                payload = fetch_xml(pmcid, client)
                if args.delay > 0:
                    time.sleep(args.delay)
                return payload

            result = freeze_predictions(plan, screen, fetcher)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "article_count_succeeded",
                    "failure_count",
                    "event_count",
                    "phase_counts",
                    "attribute_counts",
                    "prediction_sha256",
                )
            },
            indent=2,
        )
    )
    if result["failure_count"]:
        raise SystemExit("prediction freezing failed for one or more articles")


if __name__ == "__main__":
    main()
