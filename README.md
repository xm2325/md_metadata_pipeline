# MD Metadata Pipeline

Evidence-linked extraction and validation for molecular-dynamics literature, designed for the EMBL-EBI JR3997 problem setting.

## Current research evidence

The frozen-v2 independent held-out result remains the primary model result: 15 articles, 165 reference facts, precision 0.844, recall 0.695, and F1 0.763. The 120-article unlabelled audit produced 1,204 evidence-linked facts with no execution failure; it does not provide an accuracy estimate.

Version 0.3 added a phase-aware protocol-event schema and PDBe, UniProt, and SIFTS-derived validation states.

Version 0.4 added hashed Europe PMC retrieval, deterministic 30/10/20 planning, dual-annotation comparison, adjudication templates, and event-level evaluation.

Version 0.4.1 changed event scoring from sets to multisets and added duration-matched phase confusion.

Version 0.5 added hashed response caching, retry provenance, bounded `Retry-After`, SIFTS-derived residue ranges, and validation audit summaries.

Version 0.6 added a provider-independent schema-constrained model adapter. Model outputs remain candidates until exact source offsets, raw numeric expressions, and deterministic unit conversions pass code checks.

Version 0.7 adds a provisional temporal-isolation path:

- candidate articles can be restricted to an explicit publication-year window;
- plans are labelled `provisional_temporal_isolation`, never `locked_confirmatory`;
- the original minimum prior-ID gate remains mandatory for a locked confirmatory plan;
- selected Europe PMC full text is screened in memory and only hashes, aggregate signals, and limited metadata are stored;
- machine triage requires an MD protocol signal and a biomolecular-domain signal;
- machine eligibility is not treated as human eligibility or reference annotation.

External databases do not fill reference labels and never overwrite extracted literature values. Network failure is not treated as biological conflict. Model output is not a final record until evidence checks pass.

## Run tests

```bash
python -m pip install -e '.[dev]'
ruff check .
pytest --cov=mdmeta --cov-branch --cov-report=term-missing --cov-fail-under=75
```

The combined v0.7 code was locally checked with 32 tests and 86.48% branch-aware coverage before opening the pull request. GitHub Actions runs Python 3.11 and 3.12 independently.

## Locked confirmatory workflow

A locked 60-article plan still requires at least 30 unique IDs from all earlier evaluation sets:

```bash
python scripts/prepare_confirmatory_benchmark.py \
  --candidates study/confirmatory_60/generated/candidates.json \
  --excluded-ids study/confirmatory_60/prior_article_ids.txt \
  --minimum-excluded 30 \
  --output study/confirmatory_60/generated/locked_plan.json
```

Only 15 original development IDs are currently recorded; the 15 previous held-out IDs still need to be recovered. The command therefore refuses to lock the confirmatory corpus.

## Provisional temporal isolation

The temporal path is a separate research status, intended to create a working annotation queue while the prior held-out IDs remain unavailable:

```bash
python scripts/prepare_confirmatory_benchmark.py \
  --candidates study/confirmatory_60/generated/temporal/historical_candidates.json \
  --excluded-ids study/confirmatory_60/prior_article_ids.txt \
  --minimum-excluded 0 \
  --publication-year-min 2016 \
  --publication-year-max 2020 \
  --require-known-year \
  --study-status provisional_temporal_isolation \
  --output study/confirmatory_60/generated/temporal/provisional_temporal_plan.json

python scripts/screen_selected_fulltext.py \
  --plan study/confirmatory_60/generated/temporal/provisional_temporal_plan.json \
  --output study/confirmatory_60/generated/temporal/fulltext_machine_screen.json
```

The screening output contains no full article text. It stores article and split identifiers, source hashes, term counts, method-section titles, engine mentions, biomolecular signals, machine status, and failures. Human review remains required before annotation.

## Dual annotation and event evaluation

```bash
python scripts/compare_annotations.py \
  --annotator-a annotations/annotator_a.jsonl \
  --annotator-b annotations/annotator_b.jsonl \
  --output results/agreement.json \
  --adjudication-template results/adjudication.json

python scripts/evaluate_protocol_events.py \
  --predictions results/predictions.json \
  --references results/adjudicated_reference.json \
  --output results/event_metrics.json
```

## Validation audit

```bash
python scripts/summarize_validation.py \
  --records results/validation_records.json \
  --output results/validation_summary.json
```

Offline validation tests use mocked service responses. No current live PDBe, UniProt, or SIFTS batch result is claimed by those tests.

See `docs/CONFIRMATORY_BENCHMARK.md`, `docs/ANNOTATION_GUIDE.md`, `docs/VALIDATION_SEMANTICS.md`, `docs/LLM_ADAPTER.md`, and `docs/TEMPORAL_ISOLATION.md`.
