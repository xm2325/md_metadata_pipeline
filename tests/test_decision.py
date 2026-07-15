from mdmeta.decision import (
    CandidateEvidence,
    ExperimentOption,
    rank_candidates,
    recommend_experiments,
    score_candidate,
    sensitivity_analysis,
)


def candidate(candidate_id: str, **overrides: object) -> CandidateEvidence:
    values = {
        "candidate_id": candidate_id,
        "label": candidate_id,
        "evidence": {"genetic": 0.8, "assay": 0.8, "clinical": 0.7},
        "uncertainty": 0.2,
        "data_completeness": 0.9,
        "translational_relevance": 0.8,
        "novelty": 0.5,
    }
    values.update(overrides)
    return CandidateEvidence(**values)


def test_stronger_evidence_ranks_first() -> None:
    strong = candidate("strong")
    weak = candidate(
        "weak",
        evidence={"genetic": 0.3, "assay": 0.4, "clinical": 0.2},
        translational_relevance=0.4,
    )
    assert [item.candidate_id for item in rank_candidates([weak, strong])][0] == "strong"


def test_uncertainty_reduces_score() -> None:
    low = score_candidate(candidate("low", uncertainty=0.1))
    high = score_candidate(candidate("high", uncertainty=0.6))
    assert low.adjusted_score > high.adjusted_score
    assert low.decision_confidence > high.decision_confidence


def test_abstains_for_sparse_evidence() -> None:
    decision = score_candidate(
        candidate(
            "sparse",
            evidence={"assay": 0.9},
            data_completeness=0.4,
            uncertainty=0.7,
        )
    )
    assert decision.abstain
    assert decision.tier == "insufficient evidence"
    assert len(decision.reasons) == 3


def test_experiment_ranking_uses_information_value_per_cost() -> None:
    candidates = [candidate("c1", uncertainty=0.6, data_completeness=0.6)]
    experiments = [
        ExperimentOption("exp-high", "c1", "Low-cost assay", 0.8, 2.0, 0.9, 0.1, 0.9),
        ExperimentOption("exp-low", "c1", "Expensive assay", 0.8, 8.0, 0.9, 0.1, 0.9),
    ]
    ranked = recommend_experiments(candidates, experiments)
    assert ranked[0].experiment_id == "exp-high"


def test_sensitivity_reports_stable_top_candidate() -> None:
    result = sensitivity_analysis(
        [
            candidate("clear-leader"),
            candidate(
                "second",
                evidence={"genetic": 0.45, "assay": 0.45, "clinical": 0.4},
                translational_relevance=0.4,
            ),
        ]
    )
    assert result["stable_top_candidate"] is True
    assert result["top_candidates"] == ["clear-leader"]
