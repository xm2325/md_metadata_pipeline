# Scientific AI decision support

## Decision question

Given several candidate targets, systems, or molecular programmes, which candidates should receive the next unit of experimental budget, which should be held for review, and where is the evidence too weak for a responsible ranking?

The existing pipeline extracts evidence, links it to exact source locations, validates molecular identifiers, and records provenance. This module adds a separate decision layer. It does not change extracted facts and does not use external databases as reference labels.

## Why a separate decision layer is needed

A predictive model score is not a programme decision. Scientific teams also need to account for evidence coverage, uncertainty, translational relevance, experiment cost, feasibility, and the cost of a wrong decision. Combining these quantities inside an undocumented notebook makes review difficult. The decision module therefore uses a declared policy with explicit penalties and abstention rules.

## Inputs

Each candidate contains:

- evidence values from one or more predeclared evidence classes;
- uncertainty and data-completeness estimates;
- translational relevance and novelty values;
- a stable identifier and a human-readable label.

Each proposed experiment contains expected information gain, cost, feasibility, execution risk, and decision relevance. The example values are synthetic and demonstrate control flow only.

## Outputs

The workflow produces:

1. an auditable candidate ranking;
2. a decision tier: `prioritise`, `review`, `deprioritise`, or `insufficient evidence`;
3. explicit reasons when the system abstains;
4. a risk-adjusted next-experiment ranking based on expected information value per cost;
5. a sensitivity check under balanced, translation-led, and uncertainty-averse policies;
6. machine-readable JSON and a self-contained HTML decision brief.

## Governing rules

The default score is a weighted combination of evidence, translational relevance, and novelty, reduced by uncertainty and missingness penalties. A candidate is not ranked as actionable when any of the following applies:

- data completeness is below the declared minimum;
- uncertainty exceeds the declared maximum;
- fewer than two independent evidence types are available.

The policy is intentionally simple and inspectable. It is a baseline decision rule, not a learned biological law. A real deployment should set weights and thresholds before confirmatory evaluation, document who approved them, and test decision utility prospectively.

## Run

```bash
python scripts/run_scientific_ai_decision_demo.py \
  --candidates examples/scientific_ai/candidates.json \
  --experiments examples/scientific_ai/experiments.json \
  --json-output results/scientific_ai/decision_report.json \
  --html-output results/scientific_ai/index.html
```

## Interpretation limits

- The example does not claim that any real target is valid or druggable.
- Scores support resource prioritisation; they do not establish causality.
- Expected information gain must be estimated and validated for the relevant experimental system.
- Final decisions require scientific review, safety checks, and prospective evidence.
