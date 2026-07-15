from __future__ import annotations

import argparse
import json
from pathlib import Path

from mdmeta.benchmark import canonical_sha256

REQUIRED_PLAN_AUDIT_CHECKS = {
    "scale_count_is_frozen",
    "validation_is_empty",
    "gold_count_is_frozen",
    "selected_identifiers_are_unique",
    "splits_are_disjoint",
    "prior_article_overlap_is_zero",
    "selection_is_model_output_free",
    "gold_predictions_are_absent",
    "gold_role_is_sealed_dual_human",
}


def _is_lower_hex(value: object, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(char in "0123456789abcdef" for char in value)
    )


def _validate_final_plan_commitment(plan: dict) -> None:
    core = {
        key: value
        for key, value in plan.items()
        if key not in {"plan_sha256", "interpretation"}
    }
    for split in ("development", "validation", "locked_test"):
        core[split] = [row["document_id"] for row in plan[split]]
    if plan.get("plan_sha256") != canonical_sha256(core):
        raise ValueError("frozen plan commitment is invalid")


def export_scale_manifest(
    plan: dict,
    screen: dict,
    plan_audit: dict,
    study_context: dict,
    *,
    upstream_run_id: int,
    upstream_artifact_id: int,
    upstream_artifact_zip_sha256: str,
    expected_source_commit: str,
    expected_plan_sha256: str,
    expected_audit_sha256: str,
) -> tuple[dict, dict]:
    if upstream_run_id < 1 or upstream_artifact_id < 1:
        raise ValueError("upstream run and artifact identifiers must be positive")
    if not _is_lower_hex(upstream_artifact_zip_sha256, 64):
        raise ValueError("upstream artifact ZIP SHA-256 is invalid")
    if not _is_lower_hex(expected_source_commit, 40):
        raise ValueError("expected selection source commit is invalid")
    if not _is_lower_hex(expected_plan_sha256, 64) or not _is_lower_hex(
        expected_audit_sha256, 64
    ):
        raise ValueError("expected plan or audit SHA-256 is invalid")
    _validate_final_plan_commitment(plan)
    if study_context.get("source_commit") != expected_source_commit:
        raise ValueError("study context source commit differs from the accepted commit")
    if plan.get("plan_sha256") != expected_plan_sha256:
        raise ValueError("frozen plan differs from the accepted plan")
    if plan_audit.get("audit_sha256") != expected_audit_sha256:
        raise ValueError("plan audit differs from the accepted audit")
    audit_core = {
        key: value for key, value in plan_audit.items() if key != "audit_sha256"
    }
    if canonical_sha256(audit_core) != expected_audit_sha256:
        raise ValueError("plan audit commitment is invalid")
    if plan_audit.get("plan_sha256") != expected_plan_sha256:
        raise ValueError("plan audit does not bind the accepted plan")
    if plan_audit.get("passed") is not True or plan_audit.get("failures") != []:
        raise ValueError("independent plan audit did not pass")
    audit_checks = plan_audit.get("checks", {})
    if not REQUIRED_PLAN_AUDIT_CHECKS.issubset(audit_checks) or not all(
        audit_checks[name] is True for name in REQUIRED_PLAN_AUDIT_CHECKS
    ):
        raise ValueError("one or more independent plan audit checks did not pass")
    if plan.get("model_output_used_for_selection") is not False:
        raise ValueError("frozen plan selection is not model-output-free")
    if plan.get("gold_predictions_generated") is not False:
        raise ValueError("gold predictions already exist")
    if int(study_context.get("github_run_id", 0)) != upstream_run_id:
        raise ValueError("study context does not match the accepted upstream run")
    if (
        study_context.get("selection_uses_model_output") is not False
        or study_context.get("gold_predictions_generated") is not False
    ):
        raise ValueError("study context does not preserve the pre-inference seal")
    if canonical_sha256(screen) != plan.get("screen_sha256"):
        raise ValueError("full-text screen does not match the frozen plan")
    if screen.get("plan_sha256") != plan.get("source_pool_plan_sha256"):
        raise ValueError("full-text screen does not match the source-pool plan")

    scale = plan["development"]
    validation = plan["validation"]
    gold = plan["locked_test"]
    if len(scale) != 80 or validation or len(gold) != 20:
        raise ValueError("accepted plan must contain scale80, validation0 and sealed gold20")
    screen_records = {row["document_id"]: row for row in screen["records"]}
    articles = []
    for article in scale:
        record = screen_records.get(article["document_id"])
        if record is None:
            raise ValueError(f"missing screen record for scale article {article['document_id']}")
        if record.get("machine_eligible_for_annotation") is not True:
            raise ValueError(
                f"scale article failed the frozen rule screen: {article['document_id']}"
            )
        if not _is_lower_hex(record.get("full_text_sha256"), 64):
            raise ValueError(f"scale source hash is invalid: {article['document_id']}")
        articles.append(
            {
                "document_id": article["document_id"],
                "split": "scale",
                "source_uri": article["source_uri"],
                "full_text_sha256": record["full_text_sha256"],
            }
        )
    scale_ids = {row["document_id"] for row in articles}
    gold_ids = {row["document_id"] for row in gold}
    if scale_ids & gold_ids:
        raise ValueError("scale export overlaps the sealed gold split")

    manifest_core = {
        "schema_version": "mdmeta.independent-scale-source.v1",
        "study_id": "mdmeta-independent-100-scale80-v1",
        "study_status": "independent_scale80_frozen_preinference",
        "parent_study_id": plan["study_id"],
        "parent_plan_sha256": plan["plan_sha256"],
        "parent_audit_sha256": plan_audit["audit_sha256"],
        "source_screen_sha256": plan["screen_sha256"],
        "selection_source_commit": expected_source_commit,
        "selection_artifact": {
            "github_run_id": upstream_run_id,
            "artifact_id": upstream_artifact_id,
            "zip_sha256": upstream_artifact_zip_sha256,
        },
        "selection_method": "development_scale_split_only_locked_test_excluded",
        "contains_locked_test_articles": False,
        "contains_human_reference_labels": False,
        "model_output_used_for_selection": False,
        "articles": articles,
    }
    manifest = {
        **manifest_core,
        "manifest_sha256": canonical_sha256(manifest_core),
    }
    audit_core = {
        "schema_version": "mdmeta.independent-scale-export-audit.v1",
        "source_commit": expected_source_commit,
        "upstream_github_run_id": upstream_run_id,
        "upstream_artifact_id": upstream_artifact_id,
        "upstream_artifact_zip_sha256": upstream_artifact_zip_sha256,
        "parent_plan_sha256": plan["plan_sha256"],
        "parent_audit_sha256": plan_audit["audit_sha256"],
        "source_manifest_sha256": manifest["manifest_sha256"],
        "scale_article_count": len(articles),
        "validation_article_count_exported": 0,
        "gold_article_count_exported": 0,
        "gold_article_count_sealed_upstream": len(gold),
        "scale_gold_overlap_count": len(scale_ids & gold_ids),
        "scale_article_order_sha256": canonical_sha256(
            [row["document_id"] for row in articles]
        ),
        "contains_locked_test_articles": False,
        "contains_human_reference_labels": False,
        "contains_machine_predictions": False,
        "passed": True,
    }
    audit = {**audit_core, "audit_sha256": canonical_sha256(audit_core)}
    return manifest, audit


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export only the accepted scale80 split for model inference."
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--screen", type=Path, required=True)
    parser.add_argument("--plan-audit", type=Path, required=True)
    parser.add_argument("--study-context", type=Path, required=True)
    parser.add_argument("--upstream-run-id", type=int, required=True)
    parser.add_argument("--upstream-artifact-id", type=int, required=True)
    parser.add_argument("--upstream-artifact-zip-sha256", required=True)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--expected-plan-sha256", required=True)
    parser.add_argument("--expected-audit-sha256", required=True)
    parser.add_argument("--output-manifest", type=Path, required=True)
    parser.add_argument("--output-audit", type=Path, required=True)
    args = parser.parse_args()
    manifest, audit = export_scale_manifest(
        json.loads(args.plan.read_text(encoding="utf-8")),
        json.loads(args.screen.read_text(encoding="utf-8")),
        json.loads(args.plan_audit.read_text(encoding="utf-8")),
        json.loads(args.study_context.read_text(encoding="utf-8")),
        upstream_run_id=args.upstream_run_id,
        upstream_artifact_id=args.upstream_artifact_id,
        upstream_artifact_zip_sha256=args.upstream_artifact_zip_sha256,
        expected_source_commit=args.expected_source_commit,
        expected_plan_sha256=args.expected_plan_sha256,
        expected_audit_sha256=args.expected_audit_sha256,
    )
    args.output_manifest.parent.mkdir(parents=True, exist_ok=True)
    args.output_audit.parent.mkdir(parents=True, exist_ok=True)
    args.output_manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    args.output_audit.write_text(json.dumps(audit, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "source_manifest_sha256": manifest["manifest_sha256"],
                "scale_article_count": audit["scale_article_count"],
                "gold_article_count_exported": audit["gold_article_count_exported"],
                "scale_gold_overlap_count": audit["scale_gold_overlap_count"],
                "export_audit_sha256": audit["audit_sha256"],
                "passed": audit["passed"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
