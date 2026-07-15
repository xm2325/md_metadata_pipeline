"""Generate compact JSON and HTML decision reports without template dependencies."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Mapping, Sequence

from mdmeta.decision import CandidateDecision, ExperimentDecision


def build_payload(
    candidate_decisions: Sequence[CandidateDecision],
    experiment_decisions: Sequence[ExperimentDecision],
    sensitivity: Mapping[str, object],
) -> dict[str, object]:
    return {
        "decision_summary": {
            "candidate_count": len(candidate_decisions),
            "prioritise_count": sum(item.tier == "prioritise" for item in candidate_decisions),
            "abstention_count": sum(item.abstain for item in candidate_decisions),
            "stable_top_candidate": bool(sensitivity.get("stable_top_candidate", False)),
        },
        "candidates": [item.to_dict() for item in candidate_decisions],
        "recommended_experiments": [item.to_dict() for item in experiment_decisions],
        "sensitivity": dict(sensitivity),
        "interpretation_guardrails": [
            "Scores support prioritisation; they do not establish biological causality.",
            "Abstention is a valid output when evidence coverage or uncertainty is unacceptable.",
            "A final programme decision requires scientific review and prospective validation.",
        ],
    }


def write_json_report(payload: Mapping[str, object], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _candidate_rows(candidates: Sequence[Mapping[str, object]]) -> str:
    rows: list[str] = []
    for index, candidate in enumerate(candidates, start=1):
        reasons = "; ".join(str(item) for item in candidate.get("reasons", [])) or "—"
        rows.append(
            "<tr>"
            f"<td>{index}</td>"
            f"<td>{html.escape(str(candidate['label']))}</td>"
            f"<td>{float(candidate['adjusted_score']):.3f}</td>"
            f"<td>{float(candidate['decision_confidence']):.3f}</td>"
            f"<td>{html.escape(str(candidate['tier']))}</td>"
            f"<td>{html.escape(reasons)}</td>"
            "</tr>"
        )
    return "".join(rows)


def _experiment_rows(experiments: Sequence[Mapping[str, object]]) -> str:
    rows: list[str] = []
    for index, experiment in enumerate(experiments, start=1):
        rows.append(
            "<tr>"
            f"<td>{index}</td>"
            f"<td>{html.escape(str(experiment['candidate_id']))}</td>"
            f"<td>{html.escape(str(experiment['name']))}</td>"
            f"<td>{float(experiment['value_of_information']):.5f}</td>"
            f"<td>{float(experiment['cost']):.1f}</td>"
            "</tr>"
        )
    return "".join(rows)


def write_html_report(payload: Mapping[str, object], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    summary = payload["decision_summary"]
    candidates = payload["candidates"]
    experiments = payload["recommended_experiments"]
    sensitivity = payload["sensitivity"]
    top_candidates = ", ".join(sensitivity.get("top_candidates", [])) or "none"
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Scientific AI Decision Brief</title>
<style>
:root {{ font-family: Inter, system-ui, sans-serif; color: #17212b; background: #f5f7fa; }}
body {{ margin: 0; }}
main {{ max-width: 1120px; margin: 0 auto; padding: 32px 20px 56px; }}
header {{ background: #17212b; color: white; padding: 28px; border-radius: 16px; }}
h1 {{ margin: 0 0 8px; font-size: 2rem; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; margin: 18px 0; }}
.card, section {{ background: white; border-radius: 14px; padding: 18px; box-shadow: 0 2px 12px rgba(23,33,43,.08); }}
.metric {{ font-size: 1.8rem; font-weight: 700; }}
section {{ margin-top: 18px; overflow-x: auto; }}
table {{ width: 100%; border-collapse: collapse; min-width: 760px; }}
th, td {{ text-align: left; padding: 11px; border-bottom: 1px solid #dfe5eb; vertical-align: top; }}
th {{ font-size: .84rem; text-transform: uppercase; letter-spacing: .04em; }}
.guardrail {{ border-left: 4px solid #7a5af8; padding-left: 12px; }}
.small {{ color: #52616f; font-size: .94rem; }}
</style>
</head>
<body><main>
<header>
<h1>Scientific AI decision brief</h1>
<p>Evidence-linked candidate prioritisation with explicit uncertainty, abstention, and next-experiment selection.</p>
</header>
<div class="grid">
<div class="card"><div class="small">Candidates reviewed</div><div class="metric">{summary['candidate_count']}</div></div>
<div class="card"><div class="small">Prioritise</div><div class="metric">{summary['prioritise_count']}</div></div>
<div class="card"><div class="small">Abstentions</div><div class="metric">{summary['abstention_count']}</div></div>
<div class="card"><div class="small">Stable top rank</div><div class="metric">{'Yes' if summary['stable_top_candidate'] else 'No'}</div><div class="small">{html.escape(top_candidates)}</div></div>
</div>
<section>
<h2>Candidate decision table</h2>
<p class="small">The ranking is policy-governed. Low completeness, excessive uncertainty, or too few evidence types triggers abstention.</p>
<table><thead><tr><th>Rank</th><th>Candidate</th><th>Adjusted score</th><th>Confidence</th><th>Decision</th><th>Reason</th></tr></thead>
<tbody>{_candidate_rows(candidates)}</tbody></table>
</section>
<section>
<h2>Recommended next experiments</h2>
<p class="small">Value combines information gain, relevance, feasibility, execution risk, current evidence gaps, and cost.</p>
<table><thead><tr><th>Rank</th><th>Candidate</th><th>Experiment</th><th>Value / cost</th><th>Cost units</th></tr></thead>
<tbody>{_experiment_rows(experiments)}</tbody></table>
</section>
<section>
<h2>Decision guardrails</h2>
{''.join(f'<p class="guardrail">{html.escape(str(item))}</p>' for item in payload['interpretation_guardrails'])}
</section>
</main></body></html>"""
    output.write_text(document, encoding="utf-8")
