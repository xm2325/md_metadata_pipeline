# MD Metadata Pipeline

An auditable literature-to-database pipeline for molecular-dynamics (MD) metadata. The project is designed around the data-integration, scientific-text-mining, SIFTS, FAIR-data, and research-software requirements of EMBL-EBI role JR3997.

## Current release

Version `0.2.0` adds three research components:

1. **Phase-aware protocol events** linking minimisation, heating, equilibration, production, sampling, and analysis statements to exact source spans.
2. **A locked 60-article benchmark planner** with deterministic stratified selection, explicit exclusion of previous development articles, and separate development, validation, and locked-test sets.
3. **PDBe, UniProt, and SIFTS-derived validation audits** that preserve `validated`, `conflict`, and `unresolved` as separate states.

The repository does not treat external database values as literature-derived facts and does not fill missing article fields silently.

## Pipeline

```text
Europe PMC JATS XML
        |
        v
section-aware parsing and protocol-paragraph retrieval
        |
        v
v1 transparent baseline or v2 protocol-aware extraction
        |
        v
exact evidence spans + deterministic unit normalization
        |
        +------> phase-aware protocol event graph
        |
        +------> MDDB-compatible partial metadata
        |
        +------> PDBe / UniProt / SIFTS-derived validation
        |
        v
JSON + SQLite + HTML + read-only API
```

## Development-set result

The phase-aware code was evaluated on the existing 15-article, single-reviewer development set containing 164 primary reference facts.

| System | Phase-aware precision | Recall | F1 | Duration + phase F1 |
|---|---:|---:|---:|---:|
| v1 deterministic baseline | 0.389 | 0.256 | 0.309 | 0.000 |
| v2 protocol-aware extractor | 0.665 | 0.665 | 0.665 | 0.459 |

These are **development diagnostics**, not independent performance estimates. The reference set has one reviewer, and event graphs were derived from fact annotations rather than independently annotated as complete graphs. The results must not be described as a confirmatory benchmark.

The machine-readable result is in [`real_study/results/protocol_event_pilot.json`](real_study/results/protocol_event_pilot.json), with the scope declaration in [`PROTOCOL_EVENT_PILOT.md`](real_study/results/PROTOCOL_EVENT_PILOT.md).

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,api]'
make lint
make test
make demo
```

Extract a real open-access JATS article:

```bash
mdlit fetch-europe-pmc --pmcid PMC1234567 --output data/raw/PMC1234567.xml
mdlit extract \
  --xml data/raw/PMC1234567.xml \
  --document-id PMC1234567 \
  --source-uri https://europepmc.org/articles/PMC1234567 \
  --extractor-version v2 \
  --output-dir artifacts/PMC1234567
```

Live database validation is opt-in:

```bash
mdlit extract ... --live-validation
```

Generated outputs include:

```text
record.json
protocol_events.json
mddb_partial.json
audit.sqlite
report.html
```

## Confirmatory 60-article benchmark

The benchmark plan uses 30 development, 10 validation, and 20 locked-test articles. Articles from the initial 15-paper study are excluded before sampling. The selection is deterministic given the candidate manifest and seed, and the plan includes a SHA-256 identifier.

```bash
PYTHONPATH=src python real_study/prepare_confirmatory_60.py \
  --output-dir study/confirmatory_60/generated \
  --excluded-ids study/confirmatory_60/excluded_development_ids.txt
```

The command requires network access. The manual GitHub workflow `Prepare confirmatory corpus` runs the same process and uploads metadata manifests as an artifact. It does not commit or redistribute article full text.

Double annotation is supported by:

```bash
mdlit compare-annotations \
  --annotator-a annotations/annotator_a.jsonl \
  --annotator-b annotations/annotator_b.jsonl \
  --output results/agreement.json \
  --adjudication-template results/adjudication.json
```

The full design, agreement definition, exclusion rules, stopping rules, and reporting policy are in [`docs/confirmatory_benchmark.md`](docs/confirmatory_benchmark.md).

## Protocol-event model

A `ProtocolEvent` records:

- protocol phase and event order;
- duration in ns;
- temperature in K and pressure in bar;
- ensemble, integration time step, and replicate count;
- source fact identifiers and exact evidence spans;
- completeness and validation state.

Values are not copied across unrelated paragraphs. Context-based phase propagation is limited to the same paragraph or the same section under explicit constraints. See [`docs/protocol_event_model.md`](docs/protocol_event_model.md).

## Validation states

- `validated`: the service returned evidence supporting the extracted identifier or mapping;
- `conflict`: the service responded successfully but disagreed with the extracted relation;
- `unresolved`: the service was unavailable, returned no usable mapping, or the evidence was insufficient;
- `invalid`: a deterministic schema or range rule failed;
- `not_checked`: no validator was run.

A service failure is never recorded as a conflict. See [`docs/validation_audit.md`](docs/validation_audit.md).

## Tests and build gates

The release gate passes:

```text
Ruff                 PASS
pytest                35 passed, 1 live test deselected
branch-aware coverage 85.31%
synthetic regression  12/12 exact facts, F1=1.0
SQLite integrity      ok
wheel and sdist       PASS
```

The synthetic score is a software regression result, not a scientific accuracy estimate. Live API smoke tests are kept separate from deterministic CI.

## Data and licensing

Code is Apache-2.0. The repository does not publish full real articles, article-level predictions, exact quotations, or single-reviewer annotation files. Article XML must be fetched from its source and remains subject to the licence assigned by the publisher or repository. Aggregate evaluation files do not contain article full text.
