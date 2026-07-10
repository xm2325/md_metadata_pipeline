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

Version 0.4.1 corrected event counting and error analysis:

- repeated identical events and attributes are evaluated as multisets rather than collapsed sets;
- duration-matched phase confusion is reported explicitly;
- missing and spurious duration events receive separate confusion states;
- regression tests cover sampling intervals, aggregate simulation time, and duplicate events.

Version 0.5 added reproducible external-validation audit support:

- an optional response cache with canonical JSON hash checks and atomic writes;
- retry and exponential-backoff logic for network errors, rate limits, and transient server responses;
- bounded support for numeric `Retry-After` values;
- request-attempt provenance attached to every validation decision;
- PDB-chain and UniProt residue ranges parsed from SIFTS-derived mappings;
- aggregate validation summaries that do not modify source records.

Version 0.6 adds a provider-independent schema-constrained model adapter:

- models propose strict JSON candidates rather than final database records;
- every event must include an exact paragraph-relative evidence span;
- numeric values must include source `raw_text` and pass deterministic number/unit checks;
- Python, not the model, performs unit conversion;
- unsupported units, inconsistent values, missing source text, unknown paragraphs, and empty events fail closed;
- no model provider or model performance claim is included in the release.

External databases do not fill reference labels and never overwrite extracted literature values. Network failure is not treated as biological conflict. Cached responses are validation evidence, not literature evidence. Model output is a candidate until code-level evidence checks pass.

## Run tests

```bash
python -m pip install -e '.[dev]'
ruff check .
pytest --cov=mdmeta --cov-branch --cov-report=term-missing --cov-fail-under=75
```

The combined v0.6 code was locally checked with 30 tests and 86.48% branch-aware coverage before opening the pull request. GitHub Actions runs Python 3.11 and 3.12 independently.

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

See `docs/CONFIRMATORY_BENCHMARK.md`, `docs/ANNOTATION_GUIDE.md`, `docs/VALIDATION_SEMANTICS.md`, and `docs/LLM_ADAPTER.md` for study, validation, and model-adapter rules.
