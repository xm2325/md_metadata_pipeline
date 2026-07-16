# EMBL-EBI JR3997 alignment and roadmap

## Scope and evidence convention

This document maps the current repository to the official
[Bioinformatician JR3997 description](https://embl.wd103.myworkdayjobs.com/en-US/EMBL/job/Bioinformatician_JR3997).
The role sits in the PDBe/Velankar team and contributes to the Horizon Europe MD4SB project. Its
core is production-quality integration of molecular-dynamics data, structural resources, protein
annotations and literature-derived metadata, with particular emphasis on MDDB, PDBe, UniProtKB,
PDBe-KB, SIFTS, FAIR data and reusable scientific software.

Status labels refer only to evidence visible in this repository:

- **Strong**: direct implementation plus tests or a dated executed run.
- **Partial**: meaningful implementation, but an important part of the criterion is absent.
- **Gap**: no repository evidence, or the criterion concerns the applicant rather than code.

Planned work is labelled explicitly below. It must not be described as implemented in a CV,
cover letter or interview.

Version 0.12 production-candidate controls are labelled separately from deployment claims. All
repository cloud gates passed for exact commit `602a9bf` on 2026-07-16, and the scale80 schema-v2
data path was exercised on CSC; this is not evidence of a governed release, GHCR publication or
production deployment. See [Production readiness](PRODUCTION_READINESS.md).

## Current evidence baseline

The repository is already a credible scientific-software prototype rather than a notebook-only
demo:

- The frozen 60-article workflow completed literature extraction, live PDBe and UniProt
  validation, SIFTS-derived residue mapping and SQLite persistence for 60/60 articles; this is an
  integration/coverage result for the original manifest, not an accuracy result
  ([run report](../study/integration_60/RUN_2026-07-10.md),
  [workflow](../.github/workflows/integrated-enrichment.yml)).
- A complete current-source audit later checked all original 60 rows and 18 ordered reserves with
  zero unresolved retrievals. A deterministic rebuild replaced two drifted rows and preserved 60
  unique positions and the provisional 30/10/20 layout; this proves source lineage, not model
  performance ([rebuild report](../study/integration_60/SOURCE_POOL_REBUILD_2026-07-15.md)).
- A public MDDB/MDposit case verified PSF, PDB and authentic XTC data, then composed 3,741
  MD-to-PDB residue mappings into 3,573 MD-to-PDB-to-UniProt mappings
  ([run report](../study/file_backed_mddb/RUN_2026-07-10.md),
  [implementation](../src/mdmeta/file_backed.py)).
- Literature facts retain exact spans and hashes; external database enrichment cannot overwrite
  them ([integration model](../src/mdmeta/integration.py),
  [validation semantics](VALIDATION_SEMANTICS.md)).
- A transactional SQLite store, an environment-configured FastAPI/Uvicorn server, bounded search,
  liveness/readiness/metadata endpoints, Python 3.11/3.12 CI, branch coverage and multiple live
  scientific workflows are implemented ([storage](../src/mdmeta/storage.py),
  [API](../src/mdmeta/api.py), [server](../src/mdmeta/server.py),
  [CI](../.github/workflows/ci.yml)).
- Version 0.12 includes public JSON Schema contracts, strict release manifests, semantic database
  verification, WAL-safe recovery, atomic release rollback, typed API/error responses, structured
  logs, Prometheus metrics, a direct PDBe-KB adapter and a backed-up v1-to-v2 migration. All ten
  repository workflows passed for exact commit `602a9bf`; the migration/import/API path also ran
  against the real scale80 snapshot on CSC. A governed release and target-server deployment remain.
- The 60-paper AI-consensus evaluation is explicitly exploratory. Human dual annotation and
  adjudication remain incomplete
  ([evaluation](../study/confirmatory_60/AI_ANNOTATED_EXPLORATORY_EVALUATION_2026-07-10.md),
  [benchmark protocol](CONFIRMATORY_BENCHMARK.md)).

## Primary-responsibility alignment

| Official responsibility | Current repository evidence | Status |
|---|---|---|
| Design pipelines connecting MDDB with PDBe, UniProt, PDBe-KB and other resources | The file-backed case connects MDDB/MDposit to PDB, UniProt and SIFTS. The literature path now connects 80 scale records and 107 mapped accessions to a typed PDBe-KB adapter, schema-v2 persistence and REST query layer. Multi-project incremental MDDB ingestion remains. See the [PDBe-KB run](../study/pdbekb_scale80/RUN_2026-07-16.md). | **Strong** |
| Develop and deploy AI/ML approaches to extract experimental and biological metadata from literature | Exact-span validation, a bound Qwen backend/revision, 80/80 scale inference, 80/80 integration and pre-gold protocol freeze are executed. Human gold annotation/evaluation and a continuously deployed ML service remain pending. See the [scale80 report](../study/independent_100/RUN_SCALE80_2026-07-16.md). | **Partial** |
| Extend and maintain SIFTS infrastructure/code to integrate MD and other resources | Real SIFTS-derived mappings are consumed and composed with MD-to-PDB alignment, including explicit ambiguity and unmapped residues. The repository does not modify, import or contribute to the official [PDBeurope/SIFTS](https://github.com/PDBeurope/SIFTS) codebase. | **Partial** |
| Develop and maintain software tools, APIs, workflows and documentation | Installable Python package, CLI scripts, typed FastAPI endpoints, schema-v2 SQLite persistence, CI/live workflows and detailed scientific/operational documentation exist. Release/recovery/observability controls passed version 0.12 cloud gates, but a governed release and real production deployment are pending. See [project configuration](../pyproject.toml), [production readiness](PRODUCTION_READINESS.md) and [.github/workflows](../.github/workflows). | **Strong** |
| Collaborate with domain experts, engineers and data-resource providers | Modular boundaries and scientific reporting are collaboration-ready, but a repository alone does not demonstrate actual co-development with those groups. | **Gap** |
| Support FAIRification, standardisation and interoperability | Source/output hashes, provenance, explicit validation states, versioned JSON Schema models, a strict dataset-release contract and machine-readable JSON/SQLite outputs are present. The release CLI requires persistent identity/licence/creator/publisher values rather than guessing them. Authorised repository/data licensing, ontology/controlled-vocabulary mappings, a published profile and durable citable release are still absent. | **Partial** |
| Collaborate with ELIXIR, Instruct-ERIC, EU-OPENSCREEN, HPC centres and industry | No direct collaboration evidence is present. | **Gap** |
| Participate in standards, technical documentation, training, outreach and dissemination | Technical documentation and reproducible run reports are substantial. There is no evidence yet of community-standard participation, external training material, talks or outreach. | **Partial** |

## Essential-criterion alignment

| Official essential criterion | Current repository evidence | Status |
|---|---|---|
| Relevant PhD | Applicant credential; cannot be established by this repository. | **Gap** |
| Familiarity with structural biology and molecular-simulation data | Real PSF/PDB/XTC consistency checks, protein-chain alignment, construct-variant handling and residue-level mapping are implemented and executed. See [file-backed report](../study/file_backed_mddb/RUN_2026-07-10.md). | **Strong** |
| NLP/LLM scientific-literature mining | Exact-span extraction, structured candidate validation, a concrete Qwen backend/revision, 80/80 scale inference and a pre-gold protocol freeze have executed on Roihu. The human gold20 reference and accuracy evaluation are still missing. | **Partial** |
| Demonstrated FAIR principles, metadata standards and scientific repositories | Provenance, hashes, source commitments, separation of evidence from enrichment and explicit missing-data states are strong foundations. Formal FAIR metadata conformance and a durable repository release are not yet demonstrated. | **Partial** |
| Understanding of protein sequence, structure and functional annotation | Sequence-to-structure and residue-level PDB/UniProt mappings are demonstrated, and the scale80 PDBe-KB run integrated 815 functional-annotation groups and explicit annotation-partner categories without hiding unresolved upstream states. | **Strong** |
| Scientific software development, preferably Python | Typed Pydantic models, modular Python, tests, packaging, CLI scripts, API and reproducible workflows are all present. | **Strong** |
| Linux, Git and CI/CD | Ubuntu-based GitHub Actions, Python-version matrices, Ruff, pytest, branch-coverage gates and separate live scientific jobs are implemented. | **Strong** |
| Relevant scientific publications | Applicant/publication evidence; not supplied by the repository. | **Gap** |
| Communication, collaboration and problem solving | Documentation records scientific boundaries and corrective actions found during real runs. Actual team collaboration and interpersonal performance require CV, references and interview evidence. | **Partial** |

## Desirable-criterion alignment

| Official desirable criterion | Current repository evidence | Status |
|---|---|---|
| Relevant postdoctoral experience | Applicant credential; cannot be established here. | **Gap** |
| Graph databases such as Neo4j | No graph schema, export or Neo4j integration. | **Gap** |
| REST APIs | Typed health, record, PDB/UniProt search and PDBe-KB enrichment endpoints, stable problem details, request IDs and bounded queries exist. Version 0.12 passed installed-wheel/container cloud gates and a production read-only CSC API query. | **Strong** |
| Containerisation | A pinned, non-root API `Dockerfile`, hardened read-only Compose service and GitHub-hosted container smoke workflow are implemented. The version 0.11 hardened container smoke passed on 2026-07-13; immutable image publication and server deployment are still pending. | **Partial** |
| Workflow systems such as Nextflow | GitHub Actions automates the project, but this is not evidence of a scientific workflow engine such as Nextflow. | **Gap** |
| Data visualisation and analysis | Metric computation and machine-readable reports exist; there is no user-facing visualisation layer. | **Partial** |
| FAIR principles and the biological-data lifecycle | Acquisition, extraction, validation, provenance and retention boundaries are documented, but publication, long-term preservation, deprecation and deletion policies are incomplete. | **Partial** |
| Reporting and presenting scientific topics | Detailed run reports are present; no presentation, tutorial session or public dissemination artifact is included. | **Partial** |
| International and interdisciplinary teamwork | Applicant/team evidence; not established by the repository. | **Gap** |

## Corrections to the two screenshots

The screenshots are useful summaries, but should not be treated as quotations from the JD:

1. Structural biology and molecular-simulation familiarity are essential, not merely “nice to
   have.” Scientific software-development experience is essential; Python is the preferred
   language rather than the whole requirement.
2. The official role says to *develop and deploy* AI/ML literature-mining approaches. “Let an LLM
   read papers” omits evaluation, evidence traceability, deployment and maintenance.
3. Trajectories and topologies are sensible MDDB inputs, but the JD does not enumerate them. AFDB
   is part of the team ecosystem, not an explicitly named integration target in the responsibility
   list.
4. PDB-to-UniProt residue mapping is an explicit SIFTS capability. A three-way
   MD-residue-to-PDB-residue-to-UniProt-residue mapping is a strong implementation interpretation,
   not wording from the JD.
5. Advanced search is part of the PDBe team context. It is not a separately listed personal
   deliverable. Conversely, maintaining the SIFTS codebase, deployment, standards, training and
   outreach are more explicit in the JD than in the first screenshot.
6. Both screenshots understate applicant evidence: relevant publications are essential;
   postdoctoral experience, biological-data lifecycle, scientific presentation and international
   interdisciplinary work are desirable. API development is a core responsibility, while prior
   REST-specific experience is listed as desirable.

## Prioritised upgrades

Items below distinguish remaining work from version 0.12 controls whose repository cloud gates and
CSC scale data-path drill passed but still await governed release or operational acceptance.

### P0 — strongest impact on JR3997 alignment

1. **Finish a defensible human benchmark.** Recover all earlier held-out IDs, complete independent
   dual annotation and adjudication, freeze code/model/configuration before test release, and report
   uncertainty and failure cases. Do not replace the current exploratory label until this is done.
2. **Evaluate the executed model-backed path.** The concrete Qwen backend now persists bound
   model/prompt/schema/decoding and request provenance. Complete gold20 dual annotation and
   adjudication, then run the already-frozen prediction/evaluation path with calibration,
   abstention and failure analysis.
3. **Broaden the integration evidence.** The direct PDBe-KB adapter and scale80 import are complete;
   next run several diverse MDDB projects, unify file-backed MD records with the literature/v2
   model, and test incremental refresh and upstream drift.
4. **Work against the official SIFTS package.** Add a reproducible local
   `PDBeurope/SIFTS` compatibility/extension experiment and regression cases for insertion codes,
   missing residues, isoforms, engineered mutations, chimeras and ambiguous chains.
5. **Complete and publish the metadata contract.** Versioned Pydantic/JSON Schema and a strict
   dataset-release manifest and cloud schema-drift tests passed in the version 0.11 candidate.
   Authorised identifiers/licences, controlled vocabularies, `LICENSE`, `CITATION.cff`, a
   compatibility policy and a citable durable example release remain.
6. **Close remaining production data-integrity gaps.** Strict validation, WAL-safe recovery,
   release bundles, rollback and an explicit backed-up v1-to-v2 migration now pass cloud tests; the
   migration/import/API path also passed on a real scale80 snapshot. Durable scheduled backup,
   unrelated-writer maintenance enforcement and target-server recovery ownership remain.

### P1 — differentiators and portfolio evidence

1. Export the integrated model to a small Neo4j graph with documented node/edge semantics and
   comparison queries against the relational API.
2. Typed response models, stable problem details, production database/build requirements and a
   whole-bundle digest passed repository cloud validation in the version 0.11 candidate. Complete a
   user tutorial and bind the bundle/build identity to the published image digest in one deployment
   manifest.
3. Add a minimal Nextflow proof of concept only after the Python pipeline interfaces and data
   contracts are stable.
4. Add residue/provenance/coverage visualisations that expose uncertainty rather than hiding it.
5. Seek an external issue, review or small contribution to SIFTS/PDBe tooling; add training or talk
   material. These provide collaboration evidence that repository architecture alone cannot.

## GitHub Actions and storage policy

GitHub Actions should remain the main reproducibility and integration environment, but not the
authoritative long-term scientific repository.

- Use `$RUNNER_TEMP` for JATS snapshots and delete them before job completion. Keep PSF/PDB/XTC
  assets on job-local runner storage and exclude them from artifacts. Both locations disappear
  with the GitHub-hosted runner.
- Upload compact reports, mappings, logs, manifests and checksums. Keep PR diagnostics short-lived;
  retain only landmark benchmark bundles longer.
- Use Actions cache only for dependencies or build layers. A cache is evictable and must not be
  presented as a scientific result store.
- A release-quality run should fail or warn unmistakably if upload fails. The upgraded workflows
  now hard-fail output-producing release jobs or write the optional-evidence upload outcome into
  the job summary.
- Publish durable, immutable bundles to a GitHub Release or an institutional/object repository,
  with the release URI and digest recorded in the served dataset metadata.
- Reduce duplicate push/PR execution with branch/path filters and concurrency cancellation; use
  deterministic offline tests on PRs and reserve current live external-service/file runs for
  `main` or manual dispatch.

## Server deployment roadmap

The current FastAPI app factory, environment-configured Uvicorn entry point, health/readiness
checks, metadata endpoint, SQLite store, container and Compose manifest are a useful server base.
Version 0.12 cloud verification passed for exact commit `602a9bf`: see
[CI 29479523392](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29479523392),
[security 29479523442](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29479523442)
and [Server readiness 29479523434](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29479523434).
The schema-v2 migration/import/API drill also passed on CSC. There is still no immutable version
0.12 GHCR publication, durable scheduled backup job, external observability stack or deployed
TLS/authentication envelope.

### Phase 1 — immutable dataset bundle

1. `records.sqlite`, database verification, strict `release-manifest.json`, explicit
   dataset/workflow provenance, `SHA256SUMS` and canonical bundle digest are implemented in the
   version 0.12 candidate; create/verify/tamper tests passed in Actions. Execute the first live
   release-quality run.
2. Strict SQLite structure, integrity, foreign-key and semantic-record gates now precede bundle
   acceptance. Bind the accepted bundle digest to the immutable image digest in a separate
   deployment manifest.
3. Obtain authorised identifier/licence/creator/publisher values, store the bundle durably, verify
   after download and deploy by digest; never promote a partial or failed bundle.

### Phase 2 — separate API and ingestion runtimes

1. The Dockerfile and workflow define a small non-root API image built from a wheel; the version
   0.11 hardened container smoke passed on 2026-07-13. Publish an immutable version 0.12 digest,
   and add a separate worker image containing MDAnalysis/file-processing dependencies only if
   deployment needs it.
2. Production mode, `/livez`, `/readyz`, `/metadata`, bounded typed search, problem details,
   request IDs, JSON logs and `/metrics` now exist and passed the repository cloud gate. Bind
   bundle/build/image identity for promotion and exercise it through the target ingress.
3. The container keeps root and dataset filesystems read-only and redacts internal paths. Deploy a
   managed reverse proxy for TLS, authentication policy, rate/request-size limits and access logs;
   keep `/metrics` internal.

### Phase 3 — data and release operations

1. At current scale, serve an immutable SQLite snapshot from local server storage with one writer
   and one or more read-only API workers. Do not serve a live database from OneDrive, NFS or another
   sync folder.
2. Digest-addressed stage/activate/rollback and SQLite Backup API recovery are implemented with
   tests that passed in the cloud gate. Schedule governed backups and execute a
   measured restore/rollback drill on the target server.
3. Move to PostgreSQL when ingestion becomes multi-writer, updates must be continuous, or multiple
   API replicas need coordinated mutable state. Add Neo4j only for a justified graph query workload,
   not as a substitute for a defined metadata model.

### Phase 4 — observability, security and maintenance

1. Structured request logs, request IDs and bounded-label application metrics are implemented.
   Deploy collectors, resource monitoring, dashboards and alerts, keep `/metrics` private, and have
   a service owner approve SLO/error-budget targets.
2. Dependency audit, automated update configuration and security workflows exist in the current
   change set; dependency audit and Bandit passed, while container publication is configured for
   SBOM/provenance but has not run successfully. Add immutable-SHA secret-history and container-CVE
   scans, target-environment service accounts, secret/certificate rotation and evidence retention.
3. Backup, restore, rollback and schema-v2 migration tests passed Actions; the migration and
   read-only query path also ran on CSC. Add approved retention, measured target-server recovery,
   RPO/RTO, incident ownership and upstream API/cache refresh policies.
4. Schedule heavy ingestion separately from the API. Consider Nextflow or a queue/HPC scheduler
   only when multi-stage retries, parallel file processing or HPC execution justify it.

## Defensible current summary

The repository currently demonstrates a well-tested version 0.12 production candidate for
evidence-linked MD literature extraction, a bound model-backed scale80 run, live PDBe/UniProt and
PDBe-KB enrichment, SIFTS-derived residue mappings, one authentic file-backed MDDB case,
schema-v2 provenance-aware storage, an executable query server, release/recovery controls,
container manifests and CI/CD. It does **not** yet demonstrate a human gold-standard NLP result,
contribution to the SIFTS codebase, formal FAIR conformance, a governed scientific release,
immutable GHCR publication, a verified production deployment or international project
collaboration.
