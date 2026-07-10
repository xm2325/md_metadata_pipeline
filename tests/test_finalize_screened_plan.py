import pytest

from scripts.finalize_screened_plan import finalize_screened_plan


def _pool(n: int = 70) -> dict:
    articles = [
        {"document_id": f"PMC{i:06d}", "title": f"A{i}", "source_uri": f"https://x/{i}"}
        for i in range(n)
    ]
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
                "machine_eligible_for_annotation": i not in ineligible,
                "machine_screen_status": "strong" if i not in ineligible else "weak",
                "article_type": "research-article",
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


def test_finalize_rejects_mismatched_screen_and_small_eligible_set() -> None:
    screen = _screen()
    screen["plan_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="does not match"):
        finalize_screened_plan(_pool(), screen)
    with pytest.raises(ValueError, match="need at least 60"):
        finalize_screened_plan(_pool(59), _screen(59))
