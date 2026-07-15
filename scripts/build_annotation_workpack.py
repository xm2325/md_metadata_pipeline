from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from mdmeta.annotation import AnnotationFact
from mdmeta.models import EventType

TARGET_FIELDS = [
    "program",
    "program_version",
    "force_field",
    "water_model",
    "ensemble",
    "temperature",
    "pressure",
    "timestep",
    "duration",
    "replicates",
    "restraints",
    "pdb_id",
    "uniprot_accession",
    "chain_id",
    "pdb_uniprot_relation",
]
ELIGIBILITY_REASONS = [
    "eligible_biomolecular_md_protocol",
    "not_original_research",
    "no_performed_md_simulation",
    "not_biomolecular_system",
    "protocol_text_insufficient",
    "full_text_or_encoding_failure",
    "duplicate_or_secondary_report",
    "other",
]


def build_workpack(
    plan: dict,
    screen: dict,
    *,
    splits: tuple[str, ...] = ("development", "validation", "locked_test"),
) -> tuple[list[dict], dict]:
    if plan["source_pool_plan_sha256"] != screen["plan_sha256"]:
        raise ValueError("final plan and full-text screen do not share the same pool plan")
    records = {row["document_id"]: row for row in screen["records"]}
    rows: list[dict] = []
    order = 0
    for split in splits:
        for article in plan[split]:
            order += 1
            record = records.get(article["document_id"])
            if record is None:
                raise ValueError(f"missing screen record for {article['document_id']}")
            rows.append(
                {
                    "work_order": order,
                    "document_id": article["document_id"],
                    "split": split,
                    "title": article["title"],
                    "doi": article.get("doi") or "",
                    "year": article.get("year") or "",
                    "source_uri": article["source_uri"],
                    "full_text_sha256": record["full_text_sha256"],
                    "article_type": record.get("article_type") or "",
                    "machine_screen_status": record["machine_screen_status"],
                    "engine_mentions": ";".join(record["engine_mentions"]),
                    "method_section_titles": ";".join(record["method_section_titles"]),
                    "reviewer_a_eligible": "",
                    "reviewer_a_reason": "",
                    "reviewer_a_note": "",
                    "reviewer_b_eligible": "",
                    "reviewer_b_reason": "",
                    "reviewer_b_note": "",
                    "adjudicated_eligible": "",
                    "adjudicated_reason": "",
                    "adjudicator_note": "",
                }
            )
    metadata = {
        "workpack_version": "1.0.0",
        "study_status": plan["study_status"],
        "plan_sha256": plan["plan_sha256"],
        "screen_sha256": plan["screen_sha256"],
        "article_count": len(rows),
        "included_splits": list(splits),
        "split_counts": {
            split: sum(row["split"] == split for row in rows)
            for split in ("development", "validation", "locked_test")
        },
        "eligibility_values": ["yes", "no", "uncertain"],
        "eligibility_reasons": ELIGIBILITY_REASONS,
        "target_fields": TARGET_FIELDS,
        "event_types": [event.value for event in EventType],
        "annotation_schema": AnnotationFact.model_json_schema(),
        "guardrails": [
            "Reviewers work independently before comparison.",
            "Machine screening is triage only and must not be copied as a human decision.",
            "Model predictions are not shown during reference annotation.",
            "Exact quotes and offsets are recorded only in annotator-owned JSONL exports.",
            "Database validation cannot populate reference labels.",
            (
                "No accuracy claim is allowed until dual review, adjudication and the "
                "reference freeze are complete."
            ),
            (
                "Locked-test reference labels stay hidden from model developers, and model "
                "predictions stay hidden from annotators, until evaluation unsealing."
            ),
        ],
    }
    return rows, metadata


def write_workpack(
    plan: dict,
    screen: dict,
    output_dir: Path,
    *,
    splits: tuple[str, ...] = ("development", "validation", "locked_test"),
) -> None:
    rows, metadata = build_workpack(plan, screen, splits=splits)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "human_eligibility_review.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (output_dir / "annotation_workpack.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    (output_dir / "annotation_fact.schema.json").write_text(
        json.dumps(metadata["annotation_schema"], indent=2), encoding="utf-8"
    )
    (output_dir / "annotator_a.jsonl").write_text("", encoding="utf-8")
    (output_dir / "annotator_b.jsonl").write_text("", encoding="utf-8")
    (output_dir / "README.md").write_text(
        "# Human eligibility and annotation workpack\n\n"
        "1. Reviewer A and Reviewer B independently complete `human_eligibility_review.csv`.\n"
        "2. Resolve disagreements before reference annotation begins.\n"
        "3. Each annotator records exact-span facts in their own JSONL file using "
        "`annotation_fact.schema.json`.\n"
        "4. Do not inspect model predictions during first-pass annotation.\n"
        "5. Keep locked-test human labels hidden from model developers and predictions hidden "
        "from annotators until unsealing.\n"
        "6. This corpus is not an accuracy benchmark until dual review, adjudication and the "
        "reference freeze are complete.\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a no-full-text dual-review workpack.")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--screen", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--split",
        action="append",
        choices=["development", "validation", "locked_test"],
        dest="splits",
    )
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    screen = json.loads(args.screen.read_text(encoding="utf-8"))
    splits = tuple(args.splits or ("development", "validation", "locked_test"))
    write_workpack(plan, screen, args.output_dir, splits=splits)
    article_count = sum(len(plan[split]) for split in splits)
    print(json.dumps({"articles": article_count, "output_dir": str(args.output_dir)}, indent=2))


if __name__ == "__main__":
    main()
