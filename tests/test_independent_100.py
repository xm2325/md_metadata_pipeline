import json
from pathlib import Path

from scripts.audit_independent_plan import audit_independent_plan
from scripts.build_exclusion_registry import build_registry
from scripts.finalize_screened_plan import finalize_screened_plan


def _article(index: int) -> dict:
    families = ("gromacs", "amber", "namd", "openmm", "unknown")
    return {
        "document_id": f"PMC{index:06d}",
        "title": f"Article {index}",
        "doi": f"10.1/{index}",
        "year": 2025,
        "source_uri": f"https://example.org/{index}",
        "software_family": families[index % len(families)],
        "licence": "CC BY",
    }


def _pool(n: int = 130) -> dict:
    return {
        "plan_sha256": "a" * 64,
        "development": [_article(index) for index in range(n)],
        "validation": [],
        "locked_test": [],
    }


def _screen(n: int = 130) -> dict:
    return {
        "plan_sha256": "a" * 64,
        "screening_scope": "machine_triage_not_human_eligibility",
        "records": [
            {
                "document_id": f"PMC{index:06d}",
                "full_text_sha256": f"{index:064x}",
                "article_type": "research-article",
                "machine_eligible_for_annotation": index % 11 != 0,
                "machine_screen_status": "strong_biomolecular_protocol_signal",
                "engine_mentions": ["gromacs"],
                "method_section_titles": ["MD methods"],
            }
            for index in range(n)
        ],
    }


def test_exclusion_registry_is_recursive_deterministic_and_traceable(tmp_path: Path) -> None:
    text_path = tmp_path / "prior.txt"
    text_path.write_text("# prior\nPMC1\npmc2\nnot-an-id\n", encoding="utf-8")
    json_path = tmp_path / "manifest.json"
    json_path.write_text(
        json.dumps(
            {
                "articles": [{"document_id": "PMC2"}, {"document_id": "PMC3"}],
                "source_uri": "https://example.test/articles/PMC999",
            }
        ),
        encoding="utf-8",
    )
    first = build_registry([text_path], [json_path])
    second = build_registry([text_path], [json_path])
    assert first == second
    assert first["document_ids"] == ["PMC1", "PMC2", "PMC3"]
    assert first["unique_document_id_count"] == 3
    assert len(first["registry_sha256"]) == 64


def test_independent_plan_is_80_scale_plus_stratified_sealed_gold20() -> None:
    plan = finalize_screened_plan(
        _pool(),
        _screen(),
        development_size=80,
        validation_size=0,
        locked_test_size=20,
        study_id="mdmeta-independent-100-v1",
        study_status="independent_100_machine_screened_unreviewed",
        split_strategy="locked_test_stratified",
        split_seed=3997,
    )
    assert len(plan["development"]) == 80
    assert plan["validation"] == []
    assert len(plan["locked_test"]) == 20
    assert {row["software_family"] for row in plan["locked_test"]} == {
        "gromacs",
        "amber",
        "namd",
        "openmm",
        "unknown",
    }
    assert plan["model_output_used_for_selection"] is False
    assert plan["gold_predictions_generated"] is False

    registry = {
        "document_ids": ["PMC999999"],
        "registry_sha256": "b" * 64,
    }
    audit = audit_independent_plan(plan, registry)
    assert audit["passed"] is True
    assert audit["selected_article_count"] == 100
    assert audit["prior_article_overlap"] == []
