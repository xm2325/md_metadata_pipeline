from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from mdmeta.benchmark import canonical_sha256


def finalize_screened_plan(
    pool_plan: dict,
    screen: dict,
    *,
    development_size: int = 30,
    validation_size: int = 10,
    locked_test_size: int = 20,
    study_id: str = "mdmeta-provisional-temporal-screened-60-v1",
    study_status: str = "provisional_temporal_isolation_machine_screened",
    split_strategy: str = "ordered",
    split_seed: int = 3997,
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
    if split_strategy == "ordered":
        development = selected[:development_size]
        validation = selected[development_size : development_size + validation_size]
        locked_test = selected[development_size + validation_size : target]
    elif split_strategy == "locked_test_stratified":
        if validation_size != 0:
            raise ValueError("locked_test_stratified requires validation_size=0")
        strata: dict[str, list[dict]] = defaultdict(list)
        for article in selected:
            stratum = str(article.get("software_family") or "unknown").strip().lower()
            strata[stratum or "unknown"].append(article)
        for articles in strata.values():
            articles.sort(
                key=lambda article: hashlib.sha256(
                    f"{split_seed}|gold|{article['document_id']}".encode()
                ).hexdigest()
            )
        locked_test = []
        active = sorted(strata)
        while active and len(locked_test) < locked_test_size:
            remaining = []
            for stratum in active:
                if strata[stratum] and len(locked_test) < locked_test_size:
                    locked_test.append(strata[stratum].pop(0))
                if strata[stratum]:
                    remaining.append(stratum)
            active = remaining
        locked_ids = {article["document_id"] for article in locked_test}
        development = [
            article for article in selected if article["document_id"] not in locked_ids
        ][:development_size]
        validation = []
    else:
        raise ValueError(f"unsupported split strategy: {split_strategy}")
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
        "study_id": study_id,
        "study_status": study_status,
        "source_pool_plan_sha256": pool_plan["plan_sha256"],
        "screen_sha256": screen_sha,
        "screening_scope": screen["screening_scope"],
        "development": [article["document_id"] for article in development],
        "validation": [article["document_id"] for article in validation],
        "locked_test": [article["document_id"] for article in locked_test],
        "rejected_or_reserve": rejected,
    }
    if split_strategy == "locked_test_stratified":
        core.update(
            {
                "split_selection_method": (
                    "machine_triage_then_locked_test_round_robin_software_strata_sha256"
                ),
                "split_seed": split_seed,
                "split_roles": {
                    "development": "scale_only_no_accuracy_claim",
                    "validation": "unused",
                    "locked_test": "sealed_dual_human_gold",
                },
                "model_output_used_for_selection": False,
                "gold_predictions_generated": False,
            }
        )
    return {
        **core,
        "development": development,
        "validation": validation,
        "locked_test": locked_test,
        "plan_sha256": canonical_sha256(core),
        "interpretation": (
            "machine-screened provisional plan; human eligibility review is still required"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Finalize a deterministic plan after machine screening."
    )
    parser.add_argument("--pool-plan", type=Path, required=True)
    parser.add_argument("--screen", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--development-size", type=int, default=30)
    parser.add_argument("--validation-size", type=int, default=10)
    parser.add_argument("--locked-test-size", type=int, default=20)
    parser.add_argument(
        "--study-id", default="mdmeta-provisional-temporal-screened-60-v1"
    )
    parser.add_argument(
        "--study-status", default="provisional_temporal_isolation_machine_screened"
    )
    parser.add_argument(
        "--split-strategy",
        choices=["ordered", "locked_test_stratified"],
        default="ordered",
    )
    parser.add_argument("--split-seed", type=int, default=3997)
    args = parser.parse_args()
    pool_plan = json.loads(args.pool_plan.read_text(encoding="utf-8"))
    screen = json.loads(args.screen.read_text(encoding="utf-8"))
    result = finalize_screened_plan(
        pool_plan,
        screen,
        development_size=args.development_size,
        validation_size=args.validation_size,
        locked_test_size=args.locked_test_size,
        study_id=args.study_id,
        study_status=args.study_status,
        split_strategy=args.split_strategy,
        split_seed=args.split_seed,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    selected = sum(
        len(result[split]) for split in ("development", "validation", "locked_test")
    )
    print(json.dumps({"plan_sha256": result["plan_sha256"], "selected": selected}, indent=2))


if __name__ == "__main__":
    main()
