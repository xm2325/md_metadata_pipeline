from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from mdmeta.benchmark import canonical_sha256


def audit_independent_plan(
    plan: dict,
    exclusion_registry: dict,
    *,
    scale_size: int = 80,
    gold_size: int = 20,
) -> dict:
    scale = plan["development"]
    validation = plan["validation"]
    gold = plan["locked_test"]
    scale_ids = {row["document_id"] for row in scale}
    validation_ids = {row["document_id"] for row in validation}
    gold_ids = {row["document_id"] for row in gold}
    selected_ids = scale_ids | validation_ids | gold_ids
    exclusions = set(exclusion_registry["document_ids"])
    checks = {
        "scale_count_is_frozen": len(scale) == scale_size,
        "validation_is_empty": len(validation) == 0,
        "gold_count_is_frozen": len(gold) == gold_size,
        "selected_identifiers_are_unique": len(selected_ids)
        == len(scale) + len(validation) + len(gold),
        "splits_are_disjoint": not (
            scale_ids & validation_ids or scale_ids & gold_ids or validation_ids & gold_ids
        ),
        "prior_article_overlap_is_zero": not selected_ids & exclusions,
        "selection_is_model_output_free": plan.get("model_output_used_for_selection") is False,
        "gold_predictions_are_absent": plan.get("gold_predictions_generated") is False,
        "gold_role_is_sealed_dual_human": plan.get("split_roles", {}).get("locked_test")
        == "sealed_dual_human_gold",
    }
    failures = sorted(name for name, passed in checks.items() if not passed)
    core = {
        "schema_version": "mdmeta.independent-plan-audit.v1",
        "study_id": plan.get("study_id"),
        "study_status": plan.get("study_status"),
        "plan_sha256": plan.get("plan_sha256"),
        "exclusion_registry_sha256": exclusion_registry.get("registry_sha256"),
        "expected_split_counts": {
            "development_scale": scale_size,
            "validation": 0,
            "locked_test_gold": gold_size,
        },
        "observed_split_counts": {
            "development_scale": len(scale),
            "validation": len(validation),
            "locked_test_gold": len(gold),
        },
        "selected_article_count": len(selected_ids),
        "prior_article_overlap": sorted(selected_ids & exclusions),
        "gold_software_strata": dict(
            sorted(Counter(row.get("software_family") or "unknown" for row in gold).items())
        ),
        "selected_licence_missing_count": sum(
            not row.get("licence") for row in scale + validation + gold
        ),
        "checks": checks,
        "failures": failures,
        "passed": not failures,
    }
    return {**core, "audit_sha256": canonical_sha256(core)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit an independent 80/20 study plan.")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--exclusion-registry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scale-size", type=int, default=80)
    parser.add_argument("--gold-size", type=int, default=20)
    args = parser.parse_args()
    result = audit_independent_plan(
        json.loads(args.plan.read_text(encoding="utf-8")),
        json.loads(args.exclusion_registry.read_text(encoding="utf-8")),
        scale_size=args.scale_size,
        gold_size=args.gold_size,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    if not result["passed"]:
        raise SystemExit("independent plan audit failed")


if __name__ == "__main__":
    main()
