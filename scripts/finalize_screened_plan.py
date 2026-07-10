from __future__ import annotations

import argparse
import json
from pathlib import Path

from mdmeta.benchmark import canonical_sha256


def finalize_screened_plan(
    pool_plan: dict,
    screen: dict,
    *,
    development_size: int = 30,
    validation_size: int = 10,
    locked_test_size: int = 20,
) -> dict:
    target = development_size + validation_size + locked_test_size
    if screen.get("plan_sha256") != pool_plan.get("plan_sha256"):
        raise ValueError("screen result does not match the candidate-pool plan")
    records = {record["document_id"]: record for record in screen["records"]}
    ordered_articles = [
        article
        for split in ("development", "validation", "locked_test")
        for article in pool_plan[split]
    ]
    eligible = [
        article
        for article in ordered_articles
        if records.get(article["document_id"], {}).get("machine_eligible_for_annotation") is True
    ]
    if len(eligible) < target:
        raise ValueError(f"need at least {target} machine-eligible articles; found {len(eligible)}")
    selected = eligible[:target]
    selected_ids = {article["document_id"] for article in selected}
    rejected = []
    for article in ordered_articles:
        record = records.get(article["document_id"])
        if article["document_id"] in selected_ids:
            continue
        rejected.append(
            {
                "document_id": article["document_id"],
                "reason": (
                    "not_machine_eligible"
                    if record is not None and not record["machine_eligible_for_annotation"]
                    else "eligible_reserve_not_selected"
                ),
                "machine_screen_status": record.get("machine_screen_status") if record else None,
                "article_type": record.get("article_type") if record else None,
            }
        )
    screen_sha = canonical_sha256(screen)
    core = {
        "study_id": "mdmeta-provisional-temporal-screened-60-v1",
        "study_status": "provisional_temporal_isolation_machine_screened",
        "source_pool_plan_sha256": pool_plan["plan_sha256"],
        "screen_sha256": screen_sha,
        "screening_scope": screen["screening_scope"],
        "development": [article["document_id"] for article in selected[:development_size]],
        "validation": [
            article["document_id"]
            for article in selected[development_size : development_size + validation_size]
        ],
        "locked_test": [
            article["document_id"]
            for article in selected[development_size + validation_size : target]
        ],
        "rejected_or_reserve": rejected,
    }
    return {
        **core,
        "development": selected[:development_size],
        "validation": selected[development_size : development_size + validation_size],
        "locked_test": selected[development_size + validation_size : target],
        "plan_sha256": canonical_sha256(core),
        "interpretation": (
            "machine-screened provisional plan; human eligibility review is still required"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Finalize a 30/10/20 plan after machine screening."
    )
    parser.add_argument("--pool-plan", type=Path, required=True)
    parser.add_argument("--screen", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    pool_plan = json.loads(args.pool_plan.read_text(encoding="utf-8"))
    screen = json.loads(args.screen.read_text(encoding="utf-8"))
    result = finalize_screened_plan(pool_plan, screen)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"plan_sha256": result["plan_sha256"], "selected": 60}, indent=2))


if __name__ == "__main__":
    main()
