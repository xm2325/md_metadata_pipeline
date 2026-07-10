from scripts.build_annotation_workpack import build_workpack


def _article(index: int) -> dict:
    return {
        "document_id": f"PMC{index:06d}",
        "title": f"Article {index}",
        "doi": f"10.1/{index}",
        "year": 2019,
        "source_uri": f"https://example.org/{index}",
    }


def _fixtures() -> tuple[dict, dict]:
    articles = [_article(i) for i in range(60)]
    plan = {
        "study_status": "provisional_temporal_isolation_machine_screened",
        "plan_sha256": "f" * 64,
        "source_pool_plan_sha256": "a" * 64,
        "screen_sha256": "b" * 64,
        "development": articles[:30],
        "validation": articles[30:40],
        "locked_test": articles[40:],
    }
    screen = {
        "plan_sha256": "a" * 64,
        "records": [
            {
                "document_id": article["document_id"],
                "full_text_sha256": f"{i:064x}",
                "article_type": "research-article",
                "machine_screen_status": "strong_biomolecular_protocol_signal",
                "engine_mentions": ["gromacs"],
                "method_section_titles": ["Molecular dynamics methods"],
            }
            for i, article in enumerate(articles)
        ],
    }
    return plan, screen


def test_workpack_has_fixed_order_and_blank_independent_reviews() -> None:
    rows, metadata = build_workpack(*_fixtures())
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


def test_workpack_rejects_wrong_screen_or_missing_record() -> None:
    plan, screen = _fixtures()
    screen["plan_sha256"] = "c" * 64
    try:
        build_workpack(plan, screen)
    except ValueError as exc:
        assert "same pool plan" in str(exc)
    else:
        raise AssertionError("mismatched plan should fail")

    plan, screen = _fixtures()
    screen["records"].pop()
    try:
        build_workpack(plan, screen)
    except ValueError as exc:
        assert "missing screen record" in str(exc)
    else:
        raise AssertionError("missing record should fail")
