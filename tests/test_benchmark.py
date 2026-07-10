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
