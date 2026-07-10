from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from mdlit.benchmark import CandidateArticle, create_benchmark_plan
from mdlit.clients import EuropePMCClient

DEFAULT_QUERY = (
    'OPEN_ACCESS:Y AND HAS_FT:Y AND (TITLE_ABS:"molecular dynamics" OR TITLE_ABS:"MD simulation")'
)
SOFTWARE_PATTERNS = {
    "gromacs": re.compile(r"\bgromacs\b", re.IGNORECASE),
    "amber": re.compile(r"\bamber(?:tools)?\b", re.IGNORECASE),
    "namd": re.compile(r"\bnamd\b", re.IGNORECASE),
    "openmm": re.compile(r"\bopenmm\b", re.IGNORECASE),
    "charmm": re.compile(r"\bcharmm\b", re.IGNORECASE),
    "desmond": re.compile(r"\bdesmond\b", re.IGNORECASE),
}


def software_family(text: str) -> str:
    matches = [name for name, pattern in SOFTWARE_PATTERNS.items() if pattern.search(text)]
    return "+".join(matches) if matches else "unknown"


def results_to_candidates(payload: dict[str, Any]) -> list[CandidateArticle]:
    rows = payload.get("resultList", {}).get("result", [])
    candidates = []
    for row in rows:
        pmcid = str(row.get("pmcid") or "").upper()
        if not pmcid.startswith("PMC"):
            continue
        title = str(row.get("title") or "").strip()
        abstract = str(row.get("abstractText") or "")
        candidates.append(
            CandidateArticle(
                document_id=pmcid,
                title=title or pmcid,
                doi=row.get("doi"),
                year=int(row["pubYear"]) if str(row.get("pubYear", "")).isdigit() else None,
                software_family=software_family(f"{title} {abstract}"),
                licence=row.get("license"),
                full_text_available=True,
                source_uri=f"https://europepmc.org/articles/{pmcid}",
            )
        )
    return candidates


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--page-size", type=int, default=500)
    parser.add_argument("--seed", type=int, default=3997)
    parser.add_argument("--excluded-ids", type=Path)
    args = parser.parse_args()

    payload, digest, url = EuropePMCClient().search(args.query, page_size=args.page_size)
    candidates = results_to_candidates(payload)
    excluded = set()
    if args.excluded_ids:
        excluded = {
            line.strip()
            for line in args.excluded_ids.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    plan = create_benchmark_plan(candidates, seed=args.seed, excluded_document_ids=excluded)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "search_response.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    (args.output_dir / "candidate_manifest.json").write_text(
        json.dumps(
            {
                "query": args.query,
                "query_url": url,
                "response_sha256": digest,
                "articles": [candidate.model_dump(mode="json") for candidate in candidates],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (args.output_dir / "locked_plan.json").write_text(
        plan.model_dump_json(indent=2), encoding="utf-8"
    )
    print(plan.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
