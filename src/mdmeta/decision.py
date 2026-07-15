"""Evidence-aware decision support for scientific AI programmes.

The module converts heterogeneous evidence into an auditable candidate ranking,
adds explicit abstention rules, and selects follow-up experiments by expected
information value per unit cost. It is intentionally model-agnostic: upstream
models may provide the evidence values, while this layer governs decisions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Iterable, Mapping, Sequence


DEFAULT_EVIDENCE_WEIGHTS: dict[str, float] = {
    "genetic": 0.20,
    "structure": 0.15,
    "assay": 0.20,
    "literature": 0.10,
    "clinical": 0.25,
    "external_validation": 0.10,
}


def _unit_interval(name: str, value: float) -> float:
    value = float(value)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be in [0, 1], got {value}")
    return value


@dataclass(frozen=True)
class CandidateEvidence:
    """Evidence and uncertainty for one scientific candidate."""

    candidate_id: str
    label: str
    evidence: Mapping[str, float]
    uncertainty: float
    data_completeness: float
    translational_relevance: float
    novelty: float = 0.5
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("candidate_id must not be empty")
        if not self.label.strip():
            raise ValueError("label must not be empty")
        if not self.evidence:
            raise ValueError("at least one evidence value is required")
        for key, value in self.evidence.items():
            if not str(key).strip():
                raise ValueError("evidence names must not be empty")
            _unit_interval(f"evidence[{key}]", value)
        _unit_interval("uncertainty", self.uncertainty)
        _unit_interval("data_completeness", self.data_completeness)
        _unit_interval("translational_relevance", self.translational_relevance)
        _unit_interval("novelty", self.novelty)


@dataclass(frozen=True)
class ExperimentOption:
    """A possible follow-up experiment for a candidate."""

    experiment_id: str
    candidate_id: str
    name: str
    expected_information_gain: float
    cost: float
    feasibility: float
    execution_risk: float
    decision_relevance: float

    def __post_init__(self) -> None:
        if not self.experiment_id.strip() or not self.candidate_id.strip():
            raise ValueError("experiment_id and candidate_id must not be empty")
        if self.cost <= 0:
            raise ValueError("cost must be positive")
        _unit_interval("expected_information_gain", self.expected_information_gain)
        _unit_interval("feasibility", self.feasibility)
        _unit_interval("execution_risk", self.execution_risk)
        _unit_interval("decision_relevance", self.decision_relevance)


@dataclass(frozen=True)
class DecisionPolicy:
    """Transparent scoring and abstention policy."""

    evidence_weights: Mapping[str, float] = field(
        default_factory=lambda: dict(DEFAULT_EVIDENCE_WEIGHTS)
    )
    evidence_share: float = 0.75
    translational_share: float = 0.15
    novelty_share: float = 0.10
    uncertainty_penalty: float = 0.25
    missingness_penalty: float = 0.15
    minimum_completeness: float = 0.55
    maximum_uncertainty: float = 0.65
    minimum_evidence_types: int = 2
    priority_threshold: float = 0.65
    review_threshold: float = 0.45

    def __post_init__(self) -> None:
        if not self.evidence_weights:
            raise ValueError("evidence_weights must not be empty")
        if any(weight < 0 for weight in self.evidence_weights.values()):
            raise ValueError("evidence weights must be non-negative")
        if sum(self.evidence_weights.values()) <= 0:
            raise ValueError("evidence weights must have a positive sum")
        for name in (
            "evidence_share",
            "translational_share",
            "novelty_share",
            "uncertainty_penalty",
            "missingness_penalty",
            "minimum_completeness",
            "maximum_uncertainty",
            "priority_threshold",
            "review_threshold",
        ):
            _unit_interval(name, getattr(self, name))
        if self.minimum_evidence_types < 1:
            raise ValueError("minimum_evidence_types must be at least one")
        if self.review_threshold > self.priority_threshold:
            raise ValueError("review_threshold cannot exceed priority_threshold")


@dataclass(frozen=True)
class CandidateDecision:
    candidate_id: str
    label: str
    evidence_score: float
    adjusted_score: float
    decision_confidence: float
    tier: str
    abstain: bool
    reasons: tuple[str, ...]
    evidence_types: int

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["reasons"] = list(self.reasons)
        return result


@dataclass(frozen=True)
class ExperimentDecision:
    experiment_id: str
    candidate_id: str
    name: str
    value_of_information: float
    expected_information_gain: float
    cost: float
    rationale: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _clip(value: float) -> float:
    return max(0.0, min(1.0, value))


def _weighted_evidence(
    evidence: Mapping[str, float], weights: Mapping[str, float]
) -> tuple[float, int]:
    matched = [(float(evidence[name]), weight) for name, weight in weights.items() if name in evidence]
    if not matched:
        return 0.0, 0
    denominator = sum(weight for _, weight in matched)
    if denominator <= 0:
        return 0.0, len(matched)
    return sum(value * weight for value, weight in matched) / denominator, len(matched)


def score_candidate(
    candidate: CandidateEvidence, policy: DecisionPolicy | None = None
) -> CandidateDecision:
    """Score one candidate while preserving explicit reasons for abstention."""

    policy = policy or DecisionPolicy()
    evidence_score, evidence_types = _weighted_evidence(
        candidate.evidence, policy.evidence_weights
    )
    raw_score = (
        policy.evidence_share * evidence_score
        + policy.translational_share * candidate.translational_relevance
        + policy.novelty_share * candidate.novelty
    )
    adjusted_score = _clip(
        raw_score
        - policy.uncertainty_penalty * candidate.uncertainty
        - policy.missingness_penalty * (1.0 - candidate.data_completeness)
    )
    confidence = _clip(candidate.data_completeness * (1.0 - candidate.uncertainty))

    reasons: list[str] = []
    if candidate.data_completeness < policy.minimum_completeness:
        reasons.append("insufficient data completeness")
    if candidate.uncertainty > policy.maximum_uncertainty:
        reasons.append("uncertainty exceeds policy limit")
    if evidence_types < policy.minimum_evidence_types:
        reasons.append("too few independent evidence types")
    abstain = bool(reasons)

    if abstain:
        tier = "insufficient evidence"
    elif adjusted_score >= policy.priority_threshold:
        tier = "prioritise"
    elif adjusted_score >= policy.review_threshold:
        tier = "review"
    else:
        tier = "deprioritise"

    return CandidateDecision(
        candidate_id=candidate.candidate_id,
        label=candidate.label,
        evidence_score=round(evidence_score, 6),
        adjusted_score=round(adjusted_score, 6),
        decision_confidence=round(confidence, 6),
        tier=tier,
        abstain=abstain,
        reasons=tuple(reasons),
        evidence_types=evidence_types,
    )


def rank_candidates(
    candidates: Iterable[CandidateEvidence], policy: DecisionPolicy | None = None
) -> list[CandidateDecision]:
    """Return candidates ordered by decision status, score, then confidence."""

    decisions = [score_candidate(candidate, policy) for candidate in candidates]
    tier_order = {
        "prioritise": 0,
        "review": 1,
        "deprioritise": 2,
        "insufficient evidence": 3,
    }
    return sorted(
        decisions,
        key=lambda item: (
            tier_order[item.tier],
            -item.adjusted_score,
            -item.decision_confidence,
            item.candidate_id,
        ),
    )


def recommend_experiments(
    candidates: Sequence[CandidateEvidence],
    experiments: Iterable[ExperimentOption],
    *,
    top_k: int = 5,
) -> list[ExperimentDecision]:
    """Rank experiments by risk-adjusted expected information value per cost."""

    if top_k < 1:
        raise ValueError("top_k must be at least one")
    candidate_map = {candidate.candidate_id: candidate for candidate in candidates}
    recommendations: list[ExperimentDecision] = []
    for experiment in experiments:
        candidate = candidate_map.get(experiment.candidate_id)
        if candidate is None:
            raise ValueError(
                f"experiment {experiment.experiment_id} references unknown candidate "
                f"{experiment.candidate_id}"
            )
        uncertainty_need = 0.5 + 0.5 * candidate.uncertainty
        completeness_need = 0.5 + 0.5 * (1.0 - candidate.data_completeness)
        value = (
            experiment.expected_information_gain
            * experiment.decision_relevance
            * experiment.feasibility
            * (1.0 - experiment.execution_risk)
            * uncertainty_need
            * completeness_need
            / experiment.cost
        )
        rationale = (
            "High value reflects expected information gain, decision relevance, feasibility, "
            "execution risk, current uncertainty, data gaps, and cost."
        )
        recommendations.append(
            ExperimentDecision(
                experiment_id=experiment.experiment_id,
                candidate_id=experiment.candidate_id,
                name=experiment.name,
                value_of_information=round(value, 8),
                expected_information_gain=experiment.expected_information_gain,
                cost=experiment.cost,
                rationale=rationale,
            )
        )
    recommendations.sort(
        key=lambda item: (-item.value_of_information, item.cost, item.experiment_id)
    )
    return recommendations[:top_k]


def sensitivity_analysis(candidates: Sequence[CandidateEvidence]) -> dict[str, object]:
    """Compare rankings under three predeclared decision policies."""

    policies = {
        "balanced": DecisionPolicy(),
        "translation_led": DecisionPolicy(
            evidence_share=0.65,
            translational_share=0.25,
            novelty_share=0.10,
        ),
        "uncertainty_averse": DecisionPolicy(
            uncertainty_penalty=0.40,
            missingness_penalty=0.25,
            maximum_uncertainty=0.55,
        ),
    }
    rankings: dict[str, list[str]] = {
        name: [item.candidate_id for item in rank_candidates(candidates, policy)]
        for name, policy in policies.items()
    }
    top_candidates = {ranking[0] for ranking in rankings.values() if ranking}
    return {
        "rankings": rankings,
        "stable_top_candidate": len(top_candidates) == 1,
        "top_candidates": sorted(top_candidates),
    }
