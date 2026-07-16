from __future__ import annotations

import argparse
import json
from pathlib import Path


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} is not a JSON object")
    return value


def check_outputs(results: Path, trace: Path, git_commit: str) -> None:
    database = _load(results / "database" / "database-manifest.json")
    if database.get("valid") is not True or database.get("article_count") != 1:
        raise ValueError("workflow database verification did not accept one article")

    queue = _load(results / "review" / "human-review-queue.json")
    if queue.get("implementation_git_commit") != git_commit:
        raise ValueError("review queue is not bound to the workflow Git commit")
    if queue.get("review_tier_counts") != {"single_review": 1}:
        raise ValueError("smoke uncertainty was not routed to one human reviewer")
    reason_counts = queue.get("review_reason_counts")
    if (
        not isinstance(reason_counts, dict)
        or reason_counts.get("missing_pdbekb_enrichment") != 1
    ):
        raise ValueError("smoke review queue did not identify missing PDBe-KB evidence")

    graph = _load(results / "graph" / "graph-manifest.json")
    if graph.get("source_article_count") != 1:
        raise ValueError("graph export does not contain the smoke article")
    if graph.get("relationship_type_counts", {}).get("SIFTS_MAPS_TO") != 1:
        raise ValueError("graph export lost the SIFTS residue mapping")

    verification = results / "verification"
    for name in (
        "review-verification.json",
        "graph-verification.json",
        "checksums.sha256",
        "WORKFLOW_COMPLETE",
    ):
        if not (verification / name).is_file():
            raise ValueError(f"workflow verification output is missing: {name}")
    checksum_lines = (verification / "checksums.sha256").read_text().splitlines()
    if len(checksum_lines) != 5:
        raise ValueError("workflow checksum receipt must bind exactly five deliverables")

    rows = trace.read_text(encoding="utf-8").splitlines()
    if not rows:
        raise ValueError("Nextflow resume trace is empty")
    header = rows[0].split("\t")
    if "status" not in header:
        raise ValueError("Nextflow resume trace has no status column")
    status_index = header.index("status")
    statuses = [row.split("\t")[status_index] for row in rows[1:] if row]
    if len(statuses) != 4 or set(statuses) != {"CACHED"}:
        raise ValueError(f"expected four resumed processes, observed statuses={statuses}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify the Nextflow smoke deliverables.")
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--resume-trace", type=Path, required=True)
    parser.add_argument("--git-commit", required=True)
    args = parser.parse_args()
    check_outputs(args.results, args.resume_trace, args.git_commit)


if __name__ == "__main__":
    main()
