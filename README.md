# MD Metadata Pipeline

Evidence-linked extraction and validation for molecular-dynamics literature, designed for the EMBL-EBI JR3997 problem setting.

## Current research evidence

The frozen-v2 independent held-out result remains the primary model result: 15 articles, 165 reference facts, precision 0.844, recall 0.695, and F1 0.763. The 120-article unlabelled audit produced 1,204 evidence-linked facts with no execution failure; it does not provide an accuracy estimate.

Version 0.3 added two components without changing the frozen-v2 result:

1. a phase-aware protocol-event schema linking duration, temperature, pressure, ensemble, timestep, restraint text, and replicate count within a local evidence unit;
2. a PDBe, UniProt, and SIFTS-derived validation client with explicit `validated`, `conflict`, `unresolved`, and `not_applicable` states.

Version 0.4 added the execution layer required for a separate confirmatory study:

- Europe PMC metadata retrieval with response hashes;
- deterministic engine-stratified 30/10/20 corpus selection;
- prior-study exclusion with a minimum 30-ID gate;
- dual-annotation comparison at semantic and exact-span levels;
- machine-readable adjudication templates;
- exact-event, event-attribute, duration-phase, and article-bootstrap metrics.

Version 0.4.1 corrects event counting and error analysis:

- repeated identical events and attributes are evaluated as multisets rather than collapsed sets;
- duration-matched phase confusion is reported explicitly;
- missing and spurious duration events receive separate confusion states;
- regression tests cover sampling intervals, aggregate simulation time, and duplicate events.

External databases do not fill reference labels and never overwrite extracted literature values. Network failure is not treated as biological conflict.

## Run tests

```bash
python -m pip install -e '.[dev]'
ruff check .
pytest --cov=mdmeta --cov-branch --cov-report=term-missing --cov-fail-under=75
```

The combined v0.4.1 code was locally checked with 17 tests and 87.22% branch-aware coverage before opening the pull request. GitHub Actions runs Python 3.11 and 3.12 independently.

## Confirmatory corpus workflow

The manual workflow `Prepare confirmatory corpus manifest` retrieves Europe PMC metadata and attempts to create the locked split. It intentionally refuses to lock the corpus until `study/confirmatory_60/prior_article_ids.txt` contains at least 30 unique IDs from all earlier evaluation sets.

At present, 15 original development IDs are recorded; the 15 previous held-out IDs still need to be recovered. This is an explicit blocker rather than an ignored source of evaluation leakage.

```bash
python scripts/query_europe_pmc.py \
  --output study/confirmatory_60/generated/candidates.json \
  --max-candidates 500

python scripts/prepare_confirmatory_benchmark.py \
  --candidates study/confirmatory_60/generated/candidates.json \
  --excluded-ids study/confirmatory_60/prior_article_ids.txt \
  --minimum-excluded 30 \
  --output study/confirmatory_60/generated/locked_plan.json
```

## Dual annotation and evaluation

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

See `docs/CONFIRMATORY_BENCHMARK.md`, `docs/ANNOTATION_GUIDE.md`, and `docs/VALIDATION_SEMANTICS.md` for the study design and validation rules.
