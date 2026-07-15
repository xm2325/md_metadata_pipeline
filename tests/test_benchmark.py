import pytest

from mdmeta.benchmark import CandidateArticle, create_benchmark_plan


def _candidates(n: int = 80) -> list[CandidateArticle]:
    families = ["gromacs", "amber", "namd", "openmm", "unknown"]
    return [
        CandidateArticle(
            document_id=f"PMC{i:06d}",
            title=f"Article {i}",
            source_uri=f"https://example.org/PMC{i:06d}",
            software_family=families[i % len(families)],
            year=2018 + (i % 3),
        )
        for i in range(n)
    ]


def test_plan_is_deterministic_disjoint_and_excludes_prior_articles() -> None:
    candidates = _candidates()
    excluded = {"PMC000000", "PMC000001"}
    first = create_benchmark_plan(candidates, excluded_document_ids=excluded)
    second = create_benchmark_plan(candidates, excluded_document_ids=excluded)
    assert first == second
    dev = {item.document_id for item in first.development}
    val = {item.document_id for item in first.validation}
    test = {item.document_id for item in first.locked_test}
    assert (len(dev), len(val), len(test)) == (30, 10, 20)
    assert not (dev & val or dev & test or val & test)
    assert not (dev | val | test) & excluded
    assert len(first.plan_sha256) == 64
    assert len(first.candidate_manifest_sha256) == 64


def test_plan_requires_enough_eligible_articles() -> None:
    with pytest.raises(ValueError, match="need at least 60"):
        create_benchmark_plan(_candidates(59))


def test_temporal_isolation_filters_years_and_labels_plan_provisional() -> None:
    candidates = _candidates(100)
    candidates.append(
        CandidateArticle(
            document_id="PMC999998",
            title="Recent article",
            source_uri="https://example.org/recent",
            software_family="gromacs",
            year=2025,
        )
    )
    candidates.append(
        CandidateArticle(
            document_id="PMC999999",
            title="Unknown-year article",
            source_uri="https://example.org/unknown",
            software_family="amber",
            year=None,
        )
    )
    plan = create_benchmark_plan(
        candidates,
        excluded_document_ids={"PMC000000"},
        publication_year_max=2020,
        require_known_year=True,
        study_status="provisional_temporal_isolation",
    )
    selected = plan.development + plan.validation + plan.locked_test
    assert plan.study_status == "provisional_temporal_isolation"
    assert plan.study_id == "mdmeta-provisional-temporal-60-v1"
    assert all(article.year is not None and article.year <= 2020 for article in selected)
    reasons = {item["document_id"]: item["reason"] for item in plan.exclusions}
    assert reasons["PMC999998"] == "publication_year_above_window"
    assert reasons["PMC999999"] == "missing_publication_year"
    assert plan.eligibility_rules["publication_year_max"] == 2020


def test_custom_study_identity_supports_an_independent_candidate_pool() -> None:
    plan = create_benchmark_plan(
        _candidates(120),
        excluded_document_ids={"PMC000000"},
        development_size=100,
        validation_size=0,
        locked_test_size=0,
        study_status="independent_100_candidate_pool",
        study_id="mdmeta-independent-100-candidate-pool-v1",
    )
    assert plan.study_id == "mdmeta-independent-100-candidate-pool-v1"
    assert plan.study_status == "independent_100_candidate_pool"
    assert len(plan.development) == 100
    assert plan.validation == []
    assert plan.locked_test == []
