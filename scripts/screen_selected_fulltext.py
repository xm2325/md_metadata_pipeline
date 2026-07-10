from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Callable

import httpx

FULLTEXT_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
ENGINE_PATTERNS = {
    "gromacs": re.compile(r"\bgromacs\b", re.I),
    "amber": re.compile(r"\b(?:amber|ambertools)\b", re.I),
    "namd": re.compile(r"\bnamd\b", re.I),
    "openmm": re.compile(r"\bopenmm\b", re.I),
    "charmm": re.compile(r"\bcharmm\b", re.I),
    "desmond": re.compile(r"\bdesmond\b", re.I),
}
PROTOCOL_PATTERNS = {
    "molecular_dynamics": re.compile(r"\bmolecular dynamics\b|\bMD simulations?\b", re.I),
    "force_field": re.compile(r"\bforce field\b|\bCHARMM\d|\bff\d{2}SB\b|\bOPLS\b", re.I),
    "water_model": re.compile(r"\bTIP[345]P\b|\bSPC(?:/E)?\b|\bwater model\b", re.I),
    "ensemble": re.compile(r"\bNPT\b|\bNVT\b|\bNVE\b", re.I),
    "temperature": re.compile(r"\b\d+(?:\.\d+)?\s*K\b", re.I),
    "pressure": re.compile(r"\b\d+(?:\.\d+)?\s*(?:bar|atm)\b", re.I),
    "timestep": re.compile(r"\b(?:time\s*step|timestep|integration step)\b", re.I),
    "duration": re.compile(r"\b\d+(?:\.\d+)?\s*(?:ps|ns|µs|us)\b", re.I),
    "equilibration": re.compile(r"\bequilibrat", re.I),
    "production": re.compile(r"\bproduction\s+(?:MD|simulation|run)", re.I),
}
METHOD_TITLE = re.compile(
    r"method|simulation|computational|molecular dynamics|system preparation",
    re.I,
)
BIOMOLECULAR_PATTERNS = {
    "protein": re.compile(r"\bproteins?\b|\benzymes?\b|\breceptors?\b", re.I),
    "ligand": re.compile(r"\bligands?\b|\bdrug[- ]like\b|\bbinding pocket\b", re.I),
    "peptide": re.compile(r"\bpeptides?\b|\bamino acids?\b", re.I),
    "membrane": re.compile(r"\bmembranes?\b|\blipid bilayer\b", re.I),
    "nucleic_acid": re.compile(r"\bDNA\b|\bRNA\b|\bnucleic acids?\b", re.I),
}


def _text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return " ".join("".join(node.itertext()).split())


def screen_xml(document_id: str, xml_bytes: bytes, split: str) -> dict:
    digest = hashlib.sha256(xml_bytes).hexdigest()
    root = ET.fromstring(xml_bytes)
    body = root.find(".//body")
    body_text = _text(body)
    title = _text(root.find(".//article-title"))
    method_sections: list[str] = []
    for section in root.findall(".//body//sec"):
        section_title = _text(section.find("./title"))
        if section_title and METHOD_TITLE.search(section_title):
            method_sections.append(section_title)
    engines = sorted(
        name for name, pattern in ENGINE_PATTERNS.items() if pattern.search(body_text)
    )
    hits = {
        name: len(pattern.findall(body_text))
        for name, pattern in PROTOCOL_PATTERNS.items()
    }
    biomolecular_hits = {
        name: len(pattern.findall(body_text))
        for name, pattern in BIOMOLECULAR_PATTERNS.items()
    }
    positive_fields = sum(
        hits[name] > 0 for name in hits if name != "molecular_dynamics"
    )
    has_biomolecular_signal = any(value > 0 for value in biomolecular_hits.values())
    article_type = root.attrib.get("article-type")
    if (
        engines
        and positive_fields >= 2
        and hits["molecular_dynamics"] > 0
        and has_biomolecular_signal
    ):
        status = "strong_biomolecular_protocol_signal"
    elif hits["molecular_dynamics"] > 0 and positive_fields >= 2 and has_biomolecular_signal:
        status = "generic_biomolecular_protocol_signal"
    else:
        status = "non_biomolecular_or_weak_signal"
    machine_eligible = (
        status
        in {
            "strong_biomolecular_protocol_signal",
            "generic_biomolecular_protocol_signal",
        }
        and article_type != "review-article"
    )
    return {
        "document_id": document_id,
        "split": split,
        "title": title,
        "article_type": article_type,
        "full_text_sha256": digest,
        "xml_size_bytes": len(xml_bytes),
        "engine_mentions": engines,
        "protocol_term_hits": hits,
        "biomolecular_term_hits": biomolecular_hits,
        "biomolecular_domain_signal": has_biomolecular_signal,
        "method_section_titles": method_sections,
        "machine_screen_status": status,
        "machine_eligible_for_annotation": machine_eligible,
        "screening_scope": "machine_triage_not_human_eligibility",
    }


def fetch_xml(pmcid: str, client: httpx.Client) -> bytes:
    response = client.get(FULLTEXT_URL.format(pmcid=pmcid))
    response.raise_for_status()
    return response.content


def screen_plan(plan: dict, fetcher: Callable[[str], bytes]) -> dict:
    records: list[dict] = []
    failures: list[dict] = []
    for split in ("development", "validation", "locked_test"):
        for article in plan[split]:
            document_id = article["document_id"]
            try:
                records.append(screen_xml(document_id, fetcher(document_id), split))
            except (httpx.HTTPError, ET.ParseError, OSError, ValueError) as exc:
                failures.append(
                    {
                        "document_id": document_id,
                        "split": split,
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    }
                )
    status_counts = Counter(record["machine_screen_status"] for record in records)
    engine_counts = Counter(
        engine for record in records for engine in record["engine_mentions"]
    )
    eligible_count = sum(
        record["machine_eligible_for_annotation"] for record in records
    )
    return {
        "study_id": plan.get("study_id"),
        "study_status": plan.get("study_status"),
        "plan_sha256": plan.get("plan_sha256"),
        "screening_scope": "machine_triage_not_human_eligibility",
        "requested_articles": sum(
            len(plan[name]) for name in ("development", "validation", "locked_test")
        ),
        "screened_articles": len(records),
        "failure_count": len(failures),
        "status_counts": dict(sorted(status_counts.items())),
        "engine_mention_counts": dict(sorted(engine_counts.items())),
        "machine_eligible_count": eligible_count,
        "records": records,
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Screen selected Europe PMC full text without storing XML."
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--delay", type=float, default=0.05)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    headers = {"User-Agent": "md-metadata-pipeline/0.7 fulltext-screen"}
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

        result = screen_plan(plan, fetcher)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "screened_articles",
                    "failure_count",
                    "status_counts",
                    "engine_mention_counts",
                    "machine_eligible_count",
                )
            },
            indent=2,
        )
    )
    if result["failure_count"]:
        raise SystemExit("one or more selected articles could not be screened")


if __name__ == "__main__":
    main()
