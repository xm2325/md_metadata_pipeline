# MD Metadata Pipeline

Evidence-linked extraction and validation for molecular-dynamics literature, designed for the EMBL-EBI JR3997 problem setting.

## Current research evidence

The frozen-v2 independent held-out result is an externally reported baseline: 15 articles, 165 reference facts, precision 0.844, recall 0.695, and F1 0.763. Its original report/artifact is not committed in this repository, so it is not reproducible from the current tree. The same limitation applies to the externally reported 120-article unlabelled audit (1,204 evidence-linked facts and no reported execution failure); it does not provide an accuracy estimate.

On 2026-07-15, a complete current-source audit checked the original 60 selected articles and all
18 ordered reserves: 58 selected payloads still matched, two had drifted, 17 reserves were valid
and zero rows were unresolved. A deterministic one-generation rebuild replaced only those two
positions and preserved 60 unique rows and the provisional 30/10/20 layout. This is source-integrity
evidence, not annotation or accuracy evidence. See
[`study/integration_60/SOURCE_POOL_REBUILD_2026-07-15.md`](study/integration_60/SOURCE_POOL_REBUILD_2026-07-15.md).

The subsequent bounded response-v3 Roihu experiment completed its 1 → 5 → 60 GPU/CPU chain. The
full batch classified 740/740 paragraph tasks with zero generation rejection and produced 66
evidence-gated model events; CPU integration wrote 60/60 records with zero failures, 62 unique PDB
identifiers, 69 unique UniProt accessions and 274 residue-mapping segments. These are operational
coverage and throughput results, not accuracy. Cross-job temperature-zero inference was not
bitwise deterministic. See
[`study/roihu_llm_60/RUN_2026-07-15.md`](study/roihu_llm_60/RUN_2026-07-15.md).

The next-study infrastructure is now explicit: the independent-100 Actions workflow builds a
conservative prior-article exclusion registry, rule-screens an oversampled source pool, freezes an
80-article scale split plus a software-stratified sealed gold20 before inference, and emits separate
metadata, eligibility and prediction-free gold workpacks. The protocol and leakage boundary are in
[`study/independent_100/README.md`](study/independent_100/README.md). The audited cloud run has now
completed corpus construction 100/100 with zero prior-article overlap: 80 scale articles plus a
sealed gold20. The accepted Roihu run subsequently completed model inference for 80/80 scale
articles and CPU integration for 80/80 records. It classified 1,216 protocol-paragraph tasks,
produced 98 evidence-gated events, validated 99 PDB identifiers and 107 UniProt accessions, and
stored 352 residue-mapping segments. The model/protocol freeze was executed before any gold
prediction. Human eligibility is still 0/100, gold dual annotation/adjudication 0/20 and gold
prediction/evaluation 0/20; no new accuracy result exists. See
[`study/independent_100/RUN_SCALE80_2026-07-16.md`](study/independent_100/RUN_SCALE80_2026-07-16.md).
The repository now has a strict gold-reference gate for two independent, source-bound 20-article
submissions, explicit reviewed-zero states, item-level adjudication and a label-free public freeze
receipt. Actions validates only synthetic labels; this infrastructure does not change the 0/20
human-annotation progress.
The model-batch contract records a source-independent prompt commitment. The executed scale80
freeze binds the model snapshot, prompt, response schema, decoding configuration, normalisation
and evaluation code. Only that freeze plus the still-missing label-free human-reference receipt
can authorize a private gold20 inference manifest; no gold20 model result has been generated.

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

Version 0.8 adds a six-stage integration path for a real MD case and the frozen 60-article set:

- exact-span article/system metadata extraction;
- live PDBe identifier validation;
- UniProt discovery and validation through PDBe mappings;
- SIFTS-derived PDB-chain to UniProt residue segments;
- explicit MD-asset and workflow provenance, including unavailable-file states;
- transactional SQLite storage and a FastAPI query layer.

The golden Woo et al. case requires `6VSB` and `6VXX` to validate and map to `P0DTC2`. It deliberately reports only PDB-to-UniProt residue mapping because no prepared topology/trajectory correspondence is supplied. The 60-article run is a coverage and integration audit, not an accuracy result. See [`docs/JD_END_TO_END_INTEGRATION.md`](docs/JD_END_TO_END_INTEGRATION.md).

Version 0.9 adds a real file-backed MDDB/MDposit case for public project `MCV1900193.2`:

- streamed and SHA-256-verified `topology.psf`, `structure.pdb`, and authentic XTC frames;
- PSF/PDB/trajectory atom, residue, frame, residue-partition, and per-residue atom-count checks;
- independent XTC loading with both topology formats;
- exact and normalized atom-identity diagnostics that distinguish protein identity from glycan numbering conventions;
- sequence-aligned MD-residue to PDB-residue correspondence;
- composition with length-consistent SIFTS segments to UniProt `P0DTC2`;
- software, version, force field, conditions, retrieval commands, audit command, and file hashes;
- explicit reporting that the original NAMD `.conf` and execution command are not public.

The verified run mapped 3,741 prepared-system residues to PDB `6VXX` and 3,573 residues through to UniProt, while retaining construct variants and trimer-chain ambiguity. See [`study/file_backed_mddb/RUN_2026-07-10.md`](study/file_backed_mddb/RUN_2026-07-10.md).

Version 0.10 adds the first server-readiness layer:

- SQLite foreign keys are enforced on every connection, repeated record writes are regression-tested, and snapshots can be checkpointed, integrity-checked and hashed with `mdmeta-verify-database`;
- malformed successful upstream responses remain `unresolved` rather than being misreported as biological conflicts;
- package, API and external-service user-agent versions share one source of truth;
- the FastAPI service has environment configuration, bounded search, liveness, readiness and build/dataset metadata endpoints, and redacts server-local asset paths;
- a pinned Python 3.12, non-root Docker image and hardened Compose configuration serve a read-only SQLite snapshot;
- the GitHub-hosted server-readiness workflow tests Python, wheel and container paths, uses
  pip/Docker caches, attempts to upload short-lived evidence, and reports artifact/cache
  consumption without hiding quota failures. Its first complete PR compute run passed on
  2026-07-11
  ([Actions run 29152448584](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29152448584));
  GitHub rejected the optional evidence artifacts because the account storage quota remained full,
  and the job summary recorded that failure.

Version 0.11 added the first production-candidate change set. It includes strict JSON Schema and API
contracts, semantic SQLite verification, WAL-safe backup/restore, digest-addressed release bundles,
atomic release activation/rollback, production environment guards, request IDs, JSON request logs,
Prometheus metrics and additional supply-chain/security controls. The repository gates for exact
commit `c5f3018` passed on 2026-07-15: the
[main CI](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29447212786),
[Python security gates](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29447212706),
[Server readiness](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29447212735) and all
three deterministic domain workflows passed. This is
cloud validation of the production-candidate code, not a live scientific release, GHCR publication
or server deployment.

Version 0.12 adds a direct PDBe-KB adapter and compact batch contract, explicit no-data versus
upstream-failure semantics, bounded public-API concurrency, schema-v2 persistence, an explicit
backed-up v1-to-v2 migration CLI and `/pdbekb/{accession}`. The real scale80 enrichment processed
107 accessions, persisted 94 validated, three not-applicable and ten unresolved states, then passed
a production read-only API and database-integrity drill on CSC. The repository gates for exact
commit `602a9bf` all passed, including
[CI](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29479523392),
[Server readiness](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29479523434) and
[security](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29479523442). See the
[PDBe-KB run report](study/pdbekb_scale80/RUN_2026-07-16.md). This still is not a governed public
release, published GHCR image or externally reachable production service.

Version 0.13 adds a deterministic, content-bound human-review queue. Production records are
risk-routed to automatic provisional acceptance, one reviewer, or blinded independent double
review. Every routed record states the uncertainty, source/evidence locator, concrete review
question and second-review escalation conditions. The independent gold/reference path still
requires double review for every item because confidence-based selection would bias accuracy
measurement. See [`docs/HUMAN_REVIEW_POLICY.md`](docs/HUMAN_REVIEW_POLICY.md).
The first real scale80 production-triage run bound the schema-v2/PDBe-KB database and original
model summary: two records were provisionally auto-accepted, 78 received targeted single-review
prompts and none met the calibrated critical double-review rules. This is a conservative workload
assessment, not completed review or accuracy evidence. See the
[`scale80 human-review run`](study/human_review_scale80/RUN_2026-07-16.md).

The same immutable scale80 snapshot now passes a resumable Nextflow DSL2 workflow that gates the
database, creates the review queue, exports the Neo4j projection and re-verifies both outputs. The
workflow is pinned and checksum-tested on GitHub-hosted Ubuntu and ran through the CSC Slurm
executor as four `small` CPU jobs; a second run was 4/4 cached. See the
[`Nextflow workflow`](workflows/nextflow/README.md) and
[`scale80 Nextflow run`](study/nextflow_scale80/RUN_2026-07-16.md). Official PDBe-SIFTS `v1.0.4`
compatibility is also checked against its pinned readers and fixtures; see
[`docs/OFFICIAL_SIFTS_COMPATIBILITY.md`](docs/OFFICIAL_SIFTS_COMPATIBILITY.md). These are technical
integration results, not completed human review, gold accuracy or a deployed production release.

See [`docs/PRODUCTION_READINESS.md`](docs/PRODUCTION_READINESS.md),
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md), [`docs/OPERATIONS.md`](docs/OPERATIONS.md), and
[`docs/JR3997_ALIGNMENT_AND_ROADMAP.md`](docs/JR3997_ALIGNMENT_AND_ROADMAP.md).

Current `main` extends the provisional workflow with deterministic oversampling before the 30/10/20 split. It screens a larger full-text pool, selects only machine-eligible records, keeps rejected and reserve records, and creates a metadata-only dual-review workpack. The executed 2026-07-10 run screened 90 JATS articles with no download or parse failure, found 78 machine-eligible records, and produced a 60-record provisional review queue. See [`study/confirmatory_60/RUN_2026-07-10.md`](study/confirmatory_60/RUN_2026-07-10.md).

The same workflow now freezes deterministic protocol-event predictions before human annotation. Screening and prediction use the same ephemeral JATS snapshots; the snapshots are deleted before artifact upload. The verified run completed 60/60 articles with zero failure and produced 281 machine-generated event candidates in an artifact that is separate from the human workpack. These counts are not accuracy results. See [`study/confirmatory_60/PREDICTION_FREEZE_2026-07-10.md`](study/confirmatory_60/PREDICTION_FREEZE_2026-07-10.md).

External databases do not fill reference labels and never overwrite extracted literature values. Network failure is not treated as biological conflict. Model output is not a final record until evidence checks pass.

## Run tests

```bash
python -m pip install -e '.[dev]'
ruff check .
pytest --cov=mdmeta --cov-branch --cov-report=term-missing --cov-fail-under=75
```

GitHub Actions is the authoritative validation environment and runs Python 3.11 and 3.12
independently. Exact commit `c5f3018` passed the full six-workflow PR set on 2026-07-15. The
commands above remain developer instructions rather than substitutes for that dated cloud evidence.
The same head passed the deterministic offline jobs for
[integrated enrichment](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29447212682),
[file-backed mapping](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29447212692) and
[provisional-corpus construction](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29447212680).
Their live external-service/file jobs are intentionally skipped on pull requests, so these green
PR runs do not constitute a new live corpus, integration or file-backed execution.

## Run the read-only query service

The deployment image expects a verified `records.sqlite` snapshot on local server storage. It does
not run ingestion inside the API process.

The GHCR command below is a production deployment template. It becomes usable only after the
manual/tag-triggered `Publish API container` workflow succeeds for the exact candidate commit and
reports an immutable image digest; no version 0.12 production deployment has been demonstrated.

```bash
export MDMETA_DATA_DIR=/srv/mdmeta/current
export MDMETA_DATASET_SHA256="${DATABASE_SHA256:?set DATABASE_SHA256}"
export MDMETA_BUILD_SHA="${GIT_COMMIT:?set GIT_COMMIT}"
export MDMETA_IMAGE="ghcr.io/xm2325/md_metadata_pipeline@sha256:${IMAGE_DIGEST:?set IMAGE_DIGEST}"
export MDMETA_ALLOWED_HOSTS=api.example.org,127.0.0.1,localhost
export MDMETA_FORWARDED_ALLOW_IPS="${TRUSTED_PROXY:?set TRUSTED_PROXY}"
docker compose pull
docker compose up --detach --no-build --force-recreate

curl --fail http://127.0.0.1:8000/readyz
curl --fail http://127.0.0.1:8000/metadata
```

Compose enables production mode, a read-only database, one worker, explicit Host checking and
disabled interactive docs. TLS, authentication, rate limiting, request-size controls and public
access logging still belong at the institutional ingress. `/metrics` is intentionally absent from
the public OpenAPI document and must remain reachable only by an internal Prometheus scraper; do
not route it through the public ingress.

GitHub Actions is the authoritative test/build environment for this repository. The
`Server readiness` workflow runs lint, tests, coverage, wheel construction and a hardened
container smoke test on GitHub-hosted Ubuntu runners. For exact commit `c5f3018`, the workflow
passed on 2026-07-15 in
[run 29447212735](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29447212735).
Workflow-owned Python and container evidence uploads succeeded, but the extra Docker build-record
artifact still emitted a storage-quota warning. Actions artifacts are short-lived evidence and the
quota is not considered fully recovered; durable scientific bundles must be promoted to a release
or institutional repository.

## Production data contracts, release and recovery

Export or verify the public contract artifacts with:

```bash
mdmeta-export-contracts --output-dir schemas
mdmeta-export-contracts --output-dir schemas --check
```

After ingestion, finalize and verify `records.sqlite`, then use `mdmeta-release create` with real,
authorised dataset identity, licence, creator, publisher and workflow provenance values. The command
rejects placeholders; the repository does not choose those governance values for the operator.

```bash
mdmeta-verify-database \
  --database "$BUNDLE_DIR/records.sqlite" \
  --checkpoint \
  --expected-articles "$EXPECTED_ARTICLES" \
  --output "$BUNDLE_DIR/database-manifest.json"

mdmeta-release create \
  --bundle-dir "$BUNDLE_DIR" \
  --dataset-id "$DATASET_ID" \
  --dataset-version "$DATASET_VERSION" \
  --title "$DATASET_TITLE" \
  --license "$DATASET_LICENSE" \
  --creator "$DATASET_CREATOR" \
  --publisher "$DATASET_PUBLISHER" \
  --created-at "$RELEASE_CREATED_AT" \
  --git-commit "$GIT_COMMIT" \
  --workflow-run-url "$WORKFLOW_RUN_URL" \
  --workflow-run-id "$WORKFLOW_RUN_ID" \
  --workflow-run-attempt "$WORKFLOW_RUN_ATTEMPT" \
  --dependency-lock constraints/runtime.txt \
  --source-manifest "$SOURCE_MANIFEST"

mdmeta-release verify --bundle-dir "$BUNDLE_DIR"
```

The CLI records the installed package version and hashes the dependency lock and optional source
manifest itself; it does not trust hand-entered digests. Omit `--source-manifest` only when that
release genuinely has no source manifest.

`mdmeta-recovery backup` uses SQLite's online backup API and includes committed WAL frames without
checkpointing the live source. Restore into a new candidate path, verify it, and promote it as a new
immutable release; do not overwrite the database underneath a running API. Exact server procedures
are in [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Run the end-to-end integration

```bash
python scripts/run_integrated_case.py \
  --xml examples/woo_2020/article_fixture.xml \
  --document-id WOO2020 \
  --source-uri https://doi.org/10.1021/acs.jpcb.0c04553 \
  --manifest examples/woo_2020/provenance_manifest.json \
  --output results/golden/woo_2020.json \
  --database results/golden/records.sqlite \
  --cache-dir results/golden/cache \
  --expect-pdb 6VSB --expect-pdb 6VXX \
  --expect-uniprot P0DTC2

python scripts/run_integrated_60.py \
  --source-manifest study/integration_60/source_manifest.json \
  --output-dir results/integrated_60 \
  --database results/integrated_60/records.sqlite \
  --cache-dir results/integrated_60/cache
```

The integration workflow uploads compact records, the SQLite database and hashed public-service response caches. It does not upload full JATS XML.

## Run the file-backed MDDB case

```bash
python -m pip install -e '.[dev,files]'

python scripts/run_file_backed_mddb_case.py \
  --manifest examples/mddb_mcv1900193_2/project_manifest.json \
  --work-dir results/file_backed/assets \
  --output results/file_backed/report.json \
  --mapping-output results/file_backed/residue_mapping.jsonl \
  --cache-dir results/file_backed/cache
```

The workflow downloads public MDDB runtime assets but does not commit the large files. It produces a compact report, a residue-level JSONL mapping, atom-identity diagnostics, and an execution log. The acceptance gate requires topology–trajectory consistency and variant-aware MD→PDB→UniProt mapping coverage.

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

Offline validation tests use mocked service responses. Live PDBe, UniProt and mapping results are produced only by the separate integrated-enrichment and file-backed workflows and remain dated run artifacts rather than timeless repository claims.

See `docs/CONFIRMATORY_BENCHMARK.md`, `docs/ANNOTATION_GUIDE.md`,
`docs/VALIDATION_SEMANTICS.md`, `docs/LLM_ADAPTER.md`, `docs/TEMPORAL_ISOLATION.md`,
`docs/JD_END_TO_END_INTEGRATION.md`, `docs/FILE_BACKED_MDDB_PLAN.md`, and
`docs/CSC_ROIHU.md`.
