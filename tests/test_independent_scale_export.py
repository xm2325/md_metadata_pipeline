from mdmeta.benchmark import canonical_sha256
from scripts.audit_independent_plan import audit_independent_plan
from scripts.export_independent_scale_manifest import export_scale_manifest
from scripts.finalize_screened_plan import finalize_screened_plan


def _article(index: int) -> dict:
    return {
        "document_id": f"PMC{index:06d}",
        "title": f"Article {index}",
        "source_uri": f"https://example.test/PMC{index:06d}",
        "software_family": ("gromacs", "amber", "unknown")[index % 3],
        "licence": "CC BY",
    }


def _inputs() -> tuple[dict, dict, dict, dict]:
    pool = {
        "plan_sha256": "a" * 64,
        "development": [_article(index) for index in range(110)],
        "validation": [],
        "locked_test": [],
    }
    screen = {
        "plan_sha256": "a" * 64,
        "screening_scope": "machine_triage_not_human_eligibility",
        "records": [
            {
                "document_id": f"PMC{index:06d}",
                "full_text_sha256": f"{index:064x}",
                "machine_eligible_for_annotation": True,
                "machine_screen_status": "strong_biomolecular_protocol_signal",
                "article_type": "research-article",
            }
            for index in range(110)
        ],
    }
    plan = finalize_screened_plan(
        pool,
        screen,
        development_size=80,
        validation_size=0,
        locked_test_size=20,
        study_id="mdmeta-independent-100-v1",
        study_status="independent_100_machine_screened_unreviewed",
        split_strategy="locked_test_stratified",
        split_seed=3997,
    )
    exclusion_registry = {
        "document_ids": ["PMC999999"],
        "registry_sha256": "b" * 64,
    }
    audit = audit_independent_plan(plan, exclusion_registry)
    context = {
        "source_commit": "c" * 40,
        "github_run_id": "123",
        "selection_uses_model_output": False,
        "gold_predictions_generated": False,
    }
    return plan, screen, audit, context


def test_export_contains_scale80_and_no_gold_or_predictions() -> None:
    plan, screen, audit, context = _inputs()
    manifest, export_audit = export_scale_manifest(
        plan,
        screen,
        audit,
        context,
        upstream_run_id=123,
        upstream_artifact_id=456,
        upstream_artifact_zip_sha256="d" * 64,
        expected_source_commit="c" * 40,
        expected_plan_sha256=plan["plan_sha256"],
        expected_audit_sha256=audit["audit_sha256"],
    )
    scale_ids = {row["document_id"] for row in manifest["articles"]}
    gold_ids = {row["document_id"] for row in plan["locked_test"]}
    assert len(scale_ids) == 80
    assert not scale_ids & gold_ids
    assert {row["split"] for row in manifest["articles"]} == {"scale"}
    assert manifest["contains_locked_test_articles"] is False
    assert manifest["contains_human_reference_labels"] is False
    core = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    assert manifest["manifest_sha256"] == canonical_sha256(core)
    assert export_audit["gold_article_count_exported"] == 0
    assert export_audit["contains_machine_predictions"] is False
    assert export_audit["passed"] is True
