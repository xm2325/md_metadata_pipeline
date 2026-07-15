#!/usr/bin/env python3
"""Run the evidence-to-decision demonstration from JSON inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mdmeta.decision import (
    CandidateEvidence,
    ExperimentOption,
    rank_candidates,
    recommend_experiments,
    sensitivity_analysis,
)
from mdmeta.decision_report import build_payload, write_html_report, write_json_report


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--experiments", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--html-output", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    candidates = [CandidateEvidence(**item) for item in _load(args.candidates)]
    experiments = [ExperimentOption(**item) for item in _load(args.experiments)]
    candidate_decisions = rank_candidates(candidates)
    experiment_decisions = recommend_experiments(candidates, experiments, top_k=args.top_k)
    sensitivity = sensitivity_analysis(candidates)
    payload = build_payload(candidate_decisions, experiment_decisions, sensitivity)
    write_json_report(payload, args.json_output)
    write_html_report(payload, args.html_output)


if __name__ == "__main__":
    main()
