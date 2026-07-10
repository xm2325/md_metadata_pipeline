# MD Metadata Pipeline

Evidence-linked extraction and validation for molecular-dynamics literature, designed for the EMBL-EBI JR3997 problem setting.

## Current research evidence

The frozen-v2 independent held-out result remains the primary model result: 15 articles, 165 reference facts, precision 0.844, recall 0.695, and F1 0.763. The 120-article unlabelled audit produced 1,204 evidence-linked facts with no execution failure; it does not provide an accuracy estimate.

Version 0.3 added a phase-aware protocol-event schema and PDBe, UniProt, and SIFTS-derived validation states.

Version 0.4 added hashed Europe PMC retrieval, deterministic 30/10/20 planning, dual-annotation comparison, adjudication templates, and event-level evaluation.

Version 0.4.1 changed event scoring from sets to multisets and added duration-matched phase confusion.

Version 0.5 added hashed response caching, retry provenance, bounded `Retry-After`, SIFTS-derived residue ranges, and validation audit summaries.

Version 0.6 added a provider-independent schema-constrained model adapter. Model outputs remain candidates until exact source offsets, raw numeric expressions, and deterministic unit conversions pass code checks.

Version 0.7 added a provisional temporal-isolation path:

- candidate articles can be restricted to an explicit publication-year window;
- plans are labelled `provisional_temporal_isolation`, never `locked_confirmatory`;
- the original minimum prior-ID gate remains mandatory for a locked confirmatory plan;
- selected Europe PMC full text is screened in memory and only hashes, aggregate signals, and limited metadata are stored;
- machine triage requires an MD protocol signal and a biomolecular-domain signal;
- machine eligibility is not treated as human eligibility or reference annotation.

Current `main` extends the provisional workflow with deterministic oversampling before the 30/10/20 split. It screens a larger full-text pool, selects only machine-eligible records, keeps rejected and reserve records, and creates a metadata-only dual-review workpack. The executed 2026-07-10 run screened 90 JATS articles with no download or parse failure, found 78 machine-eligible records, and produced a 60-record provisional review queue. See [`study/confirmatory_60/RUN_2026-07-10.md`](study/confirmatory_60/RUN_2026-07-10.md).

The same workflow now freezes deterministic protocol-event predictions before human annotation. Screening and prediction use the same ephemeral JATS snapshots; the snapshots are deleted before artifact upload. The verified run completed 60/60 articles with zero failure and produced 281 machine-generated event candidates in an artifact that is separate from the human workpack. These counts are not accuracy results. See [`study/confirmatory_60/PREDICTION_FREEZE_2026-07-10.md`](study/confirmatory_60/PREDICTION_FREEZE_2026-07-10.md).

External databases do not fill reference labels and never overwrite extracted literature values. Network failure is not treated as biological conflict. Model output is not a final record until evidence checks pass.

## Run tests

```bash
python -m pip install -e '.[dev]'
ruff check .
pytest --cov=mdmeta --cov-branch --cov-report=term-missing --cov-fail-under=75
```

GitHub Actions runs Python 3.11 and 3.12 independently. The corpus workflow also executes a live Europe PMC metadata query, in-memory JATS screening, deterministic finalization, checksum generation, workpack construction, and blinded prediction freezing.

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

The provisional path creates a working annotation queue while the prior held-out IDs remain unavailable. A larger deterministic pool is screened before the final 60 records are assigned to development, validation, and locked-test placeholders.

```bash
CACHE_DIR="$(mktemp -d)"

python scripts/prepare_confirmatory_benchmark.py \
  --candidates study/confirmatory_60/generated/temporal/historical_candidates.json \
  --excluded-ids study/confirmatory_60/prior_article_ids.txt \
  --minimum-excluded 0 \
  --publication-year-min 2016 \
  --publication-year-max 2020 \
  --require-known-year \
  --study-status provisional_temporal_isolation \
  --development-size 90 \
  --validation-size 0 \
  --locked-test-size 0 \
  --output study/confirmatory_60/generated/temporal/provisional_screening_pool.json

python scripts/screen_selected_fulltext.py \
  --plan study/confirmatory_60/generated/temporal/provisional_screening_pool.json \
  --output study/confirmatory_60/generated/temporal/fulltext_machine_screen.json \
  --xml-cache-dir "$CACHE_DIR"

python scripts/finalize_screened_plan.py \
  --pool-plan study/confirmatory_60/generated/temporal/provisional_screening_pool.json \
  --screen study/confirmatory_60/generated/temporal/fulltext_machine_screen.json \
  --output study/confirmatory_60/generated/temporal/provisional_temporal_plan.json

python scripts/build_annotation_workpack.py \
  --plan study/confirmatory_60/generated/temporal/provisional_temporal_plan.json \
  --screen study/confirmatory_60/generated/temporal/fulltext_machine_screen.json \
  --output-dir study/confirmatory_60/generated/temporal/workpack

python scripts/freeze_machine_predictions.py \
  --plan study/confirmatory_60/generated/temporal/provisional_temporal_plan.json \
  --screen study/confirmatory_60/generated/temporal/fulltext_machine_screen.json \
  --xml-cache-dir "$CACHE_DIR" \
  --output study/confirmatory_60/generated/temporal/predictions/machine_predictions.json

rm -rf "$CACHE_DIR"
```

The generated artifacts contain no full article text. The corpus artifact stores source hashes, limited article metadata, protocol and biomolecular signal counts, and the final plan commitment. The human artifact stores a 60-row eligibility-review CSV, an annotation JSON schema, and separate empty JSONL files for two annotators. The machine-prediction artifact is separate and must not be provided to annotators before independent annotation and adjudication.

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
