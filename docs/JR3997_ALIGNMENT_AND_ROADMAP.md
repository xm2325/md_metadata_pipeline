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

## Current evidence baseline

The repository is already a credible scientific-software prototype rather than a notebook-only
demo:

- The frozen 60-article workflow completed literature extraction, live PDBe and UniProt
  validation, SIFTS-derived residue mapping and SQLite persistence for 60/60 articles; this is an
  integration/coverage result, not an accuracy result
  ([run report](../study/integration_60/RUN_2026-07-10.md),
  [workflow](../.github/workflows/integrated-enrichment.yml)).
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
- The 60-paper AI-consensus evaluation is explicitly exploratory. Human dual annotation and
  adjudication remain incomplete
  ([evaluation](../study/confirmatory_60/AI_ANNOTATED_EXPLORATORY_EVALUATION_2026-07-10.md),
  [benchmark protocol](CONFIRMATORY_BENCHMARK.md)).

## Primary-responsibility alignment

| Official responsibility | Current repository evidence | Status |
|---|---|---|
| Design pipelines connecting MDDB with PDBe, UniProt, PDBe-KB and other resources | The file-backed case connects one MDDB project to PDB/PDBe, UniProt and SIFTS; the 60-paper path integrates literature, PDBe and UniProt. There is no direct PDBe-KB adapter and the two paths are not yet a multi-project production ingestion service. See [file-backed runner](../scripts/run_file_backed_mddb_case.py) and [integration runner](../scripts/run_integrated_60.py). | **Partial** |
| Develop and deploy AI/ML approaches to extract experimental and biological metadata from literature | Exact-span deterministic extraction, a provider-independent schema-constrained model adapter, blinded prediction freezing and evaluation code exist. There is no concrete production model backend, human gold standard or deployed ML service. See [LLM adapter](../src/mdmeta/llm_adapter.py), [protocol extractor](../src/mdmeta/protocol_events.py) and [event evaluation](../src/mdmeta/event_evaluation.py). | **Partial** |
| Extend and maintain SIFTS infrastructure/code to integrate MD and other resources | Real SIFTS-derived mappings are consumed and composed with MD-to-PDB alignment, including explicit ambiguity and unmapped residues. The repository does not modify, import or contribute to the official [PDBeurope/SIFTS](https://github.com/PDBeurope/SIFTS) codebase. | **Partial** |
| Develop and maintain software tools, APIs, workflows and documentation | Installable Python package, CLI scripts, tested FastAPI endpoints, SQLite persistence, CI/live workflows and detailed scientific documentation exist. Production deployment and operations are still planned. See [project configuration](../pyproject.toml), [API tests](../tests/test_integration.py) and [.github/workflows](../.github/workflows). | **Strong** |
| Collaborate with domain experts, engineers and data-resource providers | Modular boundaries and scientific reporting are collaboration-ready, but a repository alone does not demonstrate actual co-development with those groups. | **Gap** |
| Support FAIRification, standardisation and interoperability | Source/output hashes, provenance, explicit validation states, fixed schemas, licences captured for corpus sources and machine-readable JSON/SQLite outputs are present. Persistent dataset identifiers, formal ontology/controlled-vocabulary mappings, a published metadata profile, repository licence and durable releases are absent. | **Partial** |
| Collaborate with ELIXIR, Instruct-ERIC, EU-OPENSCREEN, HPC centres and industry | No direct collaboration evidence is present. | **Gap** |
| Participate in standards, technical documentation, training, outreach and dissemination | Technical documentation and reproducible run reports are substantial. There is no evidence yet of community-standard participation, external training material, talks or outreach. | **Partial** |

## Essential-criterion alignment

| Official essential criterion | Current repository evidence | Status |
|---|---|---|
| Relevant PhD | Applicant credential; cannot be established by this repository. | **Gap** |
| Familiarity with structural biology and molecular-simulation data | Real PSF/PDB/XTC consistency checks, protein-chain alignment, construct-variant handling and residue-level mapping are implemented and executed. See [file-backed report](../study/file_backed_mddb/RUN_2026-07-10.md). | **Strong** |
| NLP/LLM scientific-literature mining | Exact-span extraction, structured candidate validation, corpus construction and evaluation exist, but the current strongest 60-paper reference is AI consensus and the generic LLM interface has no concrete backend. | **Partial** |
| Demonstrated FAIR principles, metadata standards and scientific repositories | Provenance, hashes, source commitments, separation of evidence from enrichment and explicit missing-data states are strong foundations. Formal FAIR metadata conformance and a durable repository release are not yet demonstrated. | **Partial** |
| Understanding of protein sequence, structure and functional annotation | Sequence-to-structure and residue-level PDB/UniProt mapping are demonstrated. Functional annotations beyond UniProt identity/ranges and direct PDBe-KB annotation integration are not. | **Partial** |
| Scientific software development, preferably Python | Typed Pydantic models, modular Python, tests, packaging, CLI scripts, API and reproducible workflows are all present. | **Strong** |
| Linux, Git and CI/CD | Ubuntu-based GitHub Actions, Python-version matrices, Ruff, pytest, branch-coverage gates and separate live scientific jobs are implemented. | **Strong** |
| Relevant scientific publications | Applicant/publication evidence; not supplied by the repository. | **Gap** |
| Communication, collaboration and problem solving | Documentation records scientific boundaries and corrective actions found during real runs. Actual team collaboration and interpersonal performance require CV, references and interview evidence. | **Partial** |

## Desirable-criterion alignment

| Official desirable criterion | Current repository evidence | Status |
|---|---|---|
| Relevant postdoctoral experience | Applicant credential; cannot be established here. | **Gap** |
| Graph databases such as Neo4j | No graph schema, export or Neo4j integration. | **Gap** |
| REST APIs | Tested FastAPI health, record and PDB/UniProt search endpoints exist. See [API](../src/mdmeta/api.py). | **Strong** |
| Containerisation | A pinned, non-root API `Dockerfile`, hardened read-only Compose service and GitHub-hosted container smoke workflow are implemented. The Python, wheel and container PR gate passed on 2026-07-11; immutable image publication and server deployment are still pending. | **Partial** |
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

All items in this section are **planned**, not current capability claims.

### P0 — strongest impact on JR3997 alignment

1. **Finish a defensible human benchmark.** Recover all earlier held-out IDs, complete independent
   dual annotation and adjudication, freeze code/model/configuration before test release, and report
   uncertainty and failure cases. Do not replace the current exploratory label until this is done.
2. **Add a real model-backed extraction path.** Implement at least one concrete
   `StructuredBackend`, persist model/prompt/schema versions and token/request provenance, and
   benchmark it against the human reference with calibration and abstention.
3. **Broaden the integration evidence.** Run several diverse MDDB projects, unify file-backed MD
   records with the literature/SQLite model, add a direct PDBe-KB adapter, and test incremental
   refresh and upstream drift.
4. **Work against the official SIFTS package.** Add a reproducible local
   `PDBeurope/SIFTS` compatibility/extension experiment and regression cases for insertion codes,
   missing residues, isoforms, engineered mutations, chimeras and ambiguous chains.
5. **Publish a formal metadata contract.** Version JSON Schema, define identifiers and controlled
   vocabularies, record source/data licences, add `LICENSE` and `CITATION.cff`, document provenance
   and compatibility policy, and create a citable immutable example release.
6. **Close remaining production data-integrity gaps.** Foreign-key enforcement, bounded SQLite
   waiting, portable snapshot finalisation and idempotent-upsert integrity tests now exist. A
   cloud wheel-build and installed-wheel test passed on 2026-07-11. Add schema migrations,
   dependency locking, release manifests and end-to-end restore tests.

### P1 — differentiators and portfolio evidence

1. Export the integrated model to a small Neo4j graph with documented node/edge semantics and
   comparison queries against the relational API.
2. Extend the current bounded search and software/schema metadata with typed response models,
   stable error contracts and a concise user tutorial; require the database digest in production,
   add a whole-bundle digest, and bind the reported build SHA to the published image digest.
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
Cloud verification of the Python, installed-wheel and hardened container paths passed in
[PR run 29152448584](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29152448584).
There is not yet an immutable GHCR publication, database migration system, automated backup/restore
test, production observability stack or deployed security envelope.

### Phase 1 — immutable dataset bundle

1. Actions is configured to produce `records.sqlite`, compact JSON records, a database integrity
   manifest and `SHA256SUMS`. Offline integration and snapshot-verification tests passed in PR #30;
   the first upgraded live `main`/manual bundle run remains pending. Finish the bundle with an
   explicit dataset version and source/provenance manifest.
2. SQLite integrity/foreign-key checks and scientific acceptance gates are configured before
   artifact upload. Their offline and container paths passed in PR #30; confirm the live bundle
   gate and bind the declared database digest to a separately identified complete bundle.
3. Store the accepted bundle durably and deploy by digest; never promote a partial or failed bundle.

### Phase 2 — separate API and ingestion runtimes

1. The Dockerfile and workflow define a small non-root API image built from a wheel; cloud
   verification passed on 2026-07-11. Add a separate worker image containing MDAnalysis and
   file-processing dependencies; immutable GHCR publication remains pending.
2. Environment settings, `/livez`, `/readyz`, `/metadata`, bounded search and build/dataset metadata
   now exist. A supplied database digest is verified against the mounted snapshot; require it in
   production, add whole-bundle/build-to-image binding, typed response models and structured
   logging.
3. The supplied container keeps its root filesystem and dataset mount read-only and API responses
   redact internal `local_path` values; add TLS, request limits and any required authentication at
   a reverse proxy.

### Phase 3 — data and release operations

1. At current scale, serve an immutable SQLite snapshot from local server storage with one writer
   and one or more read-only API workers. Do not serve a live database from OneDrive, NFS or another
   sync folder.
2. Deploy a new verified snapshot beside the old one and switch atomically; keep the prior digest
   for rollback. Back up active mutable SQLite through its backup API rather than copying a WAL
   database blindly.
3. Move to PostgreSQL when ingestion becomes multi-writer, updates must be continuous, or multiple
   API replicas need coordinated mutable state. Add Neo4j only for a justified graph query workload,
   not as a substitute for a defined metadata model.

### Phase 4 — observability, security and maintenance

1. Add structured logs, request IDs, latency/error metrics, resource monitoring and alerts for
   upstream-service failures and stale datasets.
2. Dependency audit and Dependabot configuration now exist, and the release workflow is configured
   to generate SBOM/provenance metadata. Its first publication is pending; add secret scanning,
   CodeQL, container scanning, least-privilege service accounts and documented secret rotation.
3. Test backup, restore, rollback, migration and disaster-recovery procedures; document retention,
   incident response and upstream API/cache refresh policies.
4. Schedule heavy ingestion separately from the API. Consider Nextflow or a queue/HPC scheduler
   only when multi-stage retries, parallel file processing or HPC execution justify it.

## Defensible current summary

The repository currently demonstrates a well-tested Python prototype for evidence-linked MD
literature extraction, live PDBe/UniProt enrichment, SIFTS-derived residue mappings, one authentic
file-backed MDDB case, provenance-aware storage, an executable query server, container manifests
and CI/CD. It does
**not** yet demonstrate a human gold-standard NLP result, direct PDBe-KB integration, contribution
to the SIFTS codebase, formal FAIR conformance, a verified production deployment or international
project collaboration.
