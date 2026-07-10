import pytest

from scripts.build_annotation_workpack import build_workpack
from scripts.finalize_screened_plan import finalize_screened_plan


def _article(index: int) -> dict:
    return {
        "document_id": f"PMC{index:06d}",
        "title": f"Article {index}",
        "doi": f"10.1/{index}",
        "year": 2019,
        "source_uri": f"https://example.org/{index}",
    }


def _pool(n: int = 70) -> dict:
    articles = [_article(i) for i in range(n)]
    return {
        "plan_sha256": "a" * 64,
        "development": articles,
        "validation": [],
        "locked_test": [],
    }


def _screen(n: int = 70, ineligible: set[int] | None = None) -> dict:
    ineligible = ineligible or set()
    return {
        "plan_sha256": "a" * 64,
        "screening_scope": "machine_triage_not_human_eligibility",
        "records": [
            {
                "document_id": f"PMC{i:06d}",
                "full_text_sha256": f"{i:064x}",
                "article_type": "research-article",
                "machine_eligible_for_annotation": i not in ineligible,
                "machine_screen_status": (
                    "strong_biomolecular_protocol_signal"
                    if i not in ineligible
                    else "non_biomolecular_or_weak_signal"
                ),
                "engine_mentions": ["gromacs"],
                "method_section_titles": ["Molecular dynamics methods"],
            }
            for i in range(n)
        ],
    }


def test_finalize_uses_first_60_eligible_and_is_disjoint() -> None:
    result = finalize_screened_plan(_pool(), _screen(ineligible={1, 3, 5}))
    ids = [
        row["document_id"]
        for split in ("development", "validation", "locked_test")
        for row in result[split]
    ]
    assert len(ids) == len(set(ids)) == 60
    assert not {"PMC000001", "PMC000003", "PMC000005"} & set(ids)
    assert result["study_status"] == "provisional_temporal_isolation_machine_screened"
    assert len(result["plan_sha256"]) == 64


def test_finalize_rejects_mismatch_and_small_eligible_set() -> None:
    screen = _screen()
    screen["plan_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="does not match"):
        finalize_screened_plan(_pool(), screen)
    with pytest.raises(ValueError, match="need at least 60"):
        finalize_screened_plan(_pool(59), _screen(59))


def test_workpack_has_fixed_order_and_blank_independent_reviews() -> None:
    screen = _screen(ineligible={1, 3, 5})
    plan = finalize_screened_plan(_pool(), screen)
    rows, metadata = build_workpack(plan, screen)
    assert len(rows) == 60
    assert [row["work_order"] for row in rows] == list(range(1, 61))
    assert metadata["split_counts"] == {
        "development": 30,
        "validation": 10,
        "locked_test": 20,
    }
    assert all(row["reviewer_a_eligible"] == "" for row in rows)
    assert all(row["reviewer_b_eligible"] == "" for row in rows)
    assert "properties" in metadata["annotation_schema"]
    assert "production" in metadata["event_types"]


def test_workpack_rejects_missing_screen_record() -> None:
    screen = _screen(ineligible={1, 3, 5})
    plan = finalize_screened_plan(_pool(), screen)
    selected_id = plan["locked_test"][-1]["document_id"]
    screen["records"] = [row for row in screen["records"] if row["document_id"] != selected_id]
    with pytest.raises(ValueError, match="missing screen record"):
        build_workpack(plan, screen)
