# Production readiness status

The repository is **not yet fully production ready**. Version 0.13 adds content-bound, risk-based
human triage to the version 0.12 production candidate. All ten repository workflows passed for
exact implementation commit `8636020` on 2026-07-16. A real scale80 database copy completed a
backed-up v1-to-v2 migration, PDBe-KB import, semantic verification, production read-only API query
and deterministic review-queue build/verification on CSC. Governed release execution, image
publication, externally reachable deployment and several ownership decisions remain outside that
evidence.

## Evidence boundary

Three different kinds of evidence must not be conflated:

| State | What it means |
|---|---|
| Repository cloud-validated | For exact commit `8636020`, all ten workflows passed on 2026-07-16, including Python 3.11/3.12 CI, security, server-readiness and the deterministic domain paths. This verifies repository code, not human-reference accuracy. |
| GPU infrastructure validated | CSC Roihu Slurm job `184708` bound to commit `cc87d7a` passed on one GH200 on 2026-07-15, including FP32 correctness, BF16 GEMM, CUDA attention, non-zero utilisation and result checksum gates. This is infrastructure evidence, not a validated model backend. |
| Scale integration, migration and triage exercised | Scale inference/integration completed 80/80; the schema-v2 drill migrated a content-addressed copy, imported 107 PDBe-KB records and passed database/API checks. Risk triage produced 2 auto-accept and 78 single-review records, with 0 critical double-review triggers. This is not completed human review, accuracy or a governed release. |
| Live/release validation pending | No governed dataset bundle, GHCR image/SBOM/provenance or externally reachable target deployment has been published. |
| External decision or deployment required | Dataset identity and licence, publisher/creators, durable archive, image promotion, DNS/TLS, authentication policy, rate limits, monitoring ownership, SLOs, RPO/RTO and incident ownership cannot be established by repository code alone. |

The dated checks validate repository code at `8636020`; they do not create a promotable release.
A candidate is promotable only after the live release workflow succeeds and its exact commit,
dataset bundle and image digests are recorded and accepted.

## Implemented production-candidate controls

- The serving process is separated from ingestion and opens one immutable SQLite snapshot
  read-only.
- Production mode fails closed when the database is writable, dataset/build digests are absent,
  unrestricted Host headers are allowed, interactive API docs are enabled, or more than one worker
  is configured in a container.
- Startup verifies the finalized database digest, SQLite integrity, foreign keys, schema and stored
  record contracts.
- The API has typed responses, stable problem-detail errors, bounded search, request IDs, security
  headers, JSON request logs and bounded-label Prometheus metrics.
- The container runs as a non-root user with a read-only root filesystem and dataset mount, no Linux
  capabilities and no-new-privileges.
- `mdmeta-export-contracts` exports or checks versioned JSON Schema artifacts.
- `mdmeta-release` creates and strictly verifies a digest-addressed dataset bundle. Its release
  manifest requires an explicit dataset identifier, version, title, licence, creators, publisher,
  timestamp, package/Git/workflow provenance and dependency-lock digest. Placeholders are rejected.
- `mdmeta-recovery` uses SQLite's backup API so committed WAL frames are included without
  checkpointing the live source. Backup and restore use a verified temporary file, fsync and an
  atomic installation path.
- Release staging rejects path traversal, symlinks, duplicate/missing/extra files, checksum drift,
  SQLite sidecars and database/record-schema mismatch. Activation and rollback switch a verified
  digest-addressed `current` symlink under a deployment lock.
- Runtime/build/security dependency inputs are separated into constraints files; security and
  container-release workflows are present in the current change set.
- `mdmeta-migrate-database` performs an explicit, locked and backed-up v1-to-v2 migration, records
  migration/source/backup hashes, validates the schema transactionally and imports a content-bound
  PDBe-KB report only when its article/accession lineage matches.
- `mdmeta-human-review` binds a checkpointed database, optional model summary, software/Git version
  and versioned policy into a deterministic review queue. It exposes uncertainty-specific prompts,
  minimal evidence locators, audit sampling and explicit second-review escalation conditions.

## Version 0.13 cloud and CSC evidence

For exact implementation commit `86360203ab3c40e1431a7f02b98eb060bdc7268e`,
[CI](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29484007623),
[security](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29484007663),
[server readiness](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29484007631) and all
seven domain workflows passed. CSC job `192664` built and verified the real scale80 review queue in
seven seconds. It routed 2/80 to provisional automatic acceptance and 78/80 to one reviewer; no
record met a calibrated critical double-review rule. See the
[scale80 review run](../study/human_review_scale80/RUN_2026-07-16.md). Human review remains undone.

### Version 0.12 PDBe-KB baseline

For exact commit `602a9bf09b981a849a3d54c74043cbbc799b6b13`, the
[CI](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29479523392),
[security](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29479523442),
[server-readiness](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29479523434),
integrated, file-backed, corpus, gold-gate and model-freeze workflows all passed. The CSC execution
evidence, including explicit upstream failures and final database hashes, is in the
[PDBe-KB scale80 report](../study/pdbekb_scale80/RUN_2026-07-16.md).

## Cloud validation evidence and remaining release gates

The following GitHub-hosted PR runs all passed for exact head
`c5f3018f686c0adf8ed212b7c71b3a3decf87ec5` on 2026-07-15:

- [CI 29447212786](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29447212786),
  including the Python 3.11 and 3.12 matrix;
- [Python security gates 29447212706](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29447212706);
- [Server readiness 29447212735](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29447212735);
- [Integrated MD metadata enrichment 29447212682](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29447212682);
- [File-backed MDDB mapping 29447212692](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29447212692); and
- [Build provisional temporal corpus 29447212680](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29447212680).

These runs include the hardened complete-pool audit/rebuild implementation. They do not execute
the accepted 60-row model-backed experiment, publish a release or deploy a service.

### Earlier version 0.11 baseline

The following GitHub-hosted PR runs passed for exact head `c2981e2120649fe6cdbe14ace402d60f7ac00a57`
on 2026-07-13:

- [CI 29217837097](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29217837097):
  Ruff and 145 tests passed independently on Python 3.11 and 3.12 with 77.90% branch coverage.
- [Python security gates 29217837131](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29217837131):
  exact production constraints, blocking `pip-audit` and blocking Bandit passed.
- [Server readiness 29217837100](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29217837100):
  wheel/CLI inspection, committed JSON Schema drift, 98 installed-wheel contract, database,
  recovery, release, API and validation tests, dependency audit and hardened container smoke passed.
- [Integrated 29217837135](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29217837135),
  [file-backed 29217837098](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29217837098)
  and [provisional 29217837108](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29217837108):
  their deterministic offline PR jobs passed on supported Python versions. Live jobs were skipped
  by PR policy and are not represented as executed evidence.

The later [Roihu GH200 infrastructure report](../study/roihu_gpu_smoke/RUN_2026-07-15.md) records a
successful remote Slurm execution for commit `cc87d7a`. An intervening Actions billing/spending
block was subsequently cleared; it is historical incident evidence, not the current cloud status.

Before describing the production candidate as release-ready or deployed, the project still needs:

1. an accepted live release-quality scientific run and sealed dataset bundle;
2. approved immutable-SHA secret-history and container-CVE scanning;
3. successful immutable GHCR publication with image digest, SBOM and build provenance;
4. a deployment record binding commit, bundle, database and image digests;
5. durable evidence storage despite the remaining Docker build-record artifact quota warning; and
6. a target-server deployment, recovery drill and operational acceptance.

## External governance and infrastructure blockers

The following values must be supplied by an authorised owner; the code deliberately does not guess
them:

- a persistent dataset identifier and versioning policy;
- the metadata/data licence, creators and publisher;
- a durable release destination and retention/deletion policy;
- a public-service owner, support route and incident commander;
- DNS, certificates and TLS termination;
- whether the API is public, institutional-only or authenticated, and which identity provider or
  gateway enforces that decision;
- rate, request-size and abuse limits;
- approved log retention and any privacy/data-protection review;
- SLO targets, alert thresholds, maintenance windows, RPO and RTO; and
- backup storage, encryption, access controls and periodic restore-test ownership.

The application exposes `/metrics` without application-level authentication. The supplied Compose
service binds only to localhost; production ingress must keep `/metrics` on an internal scrape path
and must not route it to the public API.

## Known technical gaps

- The repository is public, but required branch checks, rulesets and a protected production
  environment still need to be configured and evidenced before promotion approval can be treated
  as enforced repository policy.
- Native code scanning, secret scanning and Dependabot alerts are disabled. The current workflow
  blocks known Python dependency findings with `pip-audit` and selected Bandit findings, but an
  immutable-SHA secret-history scanner and container CVE scanner have not yet been added. Third-party
  action tags must not be guessed or trusted as immutable references.
- Repository Actions currently allow all action sources and do not enforce full-SHA pinning as a
  platform rule; the committed workflows pin the actions they use, but the repository setting is
  still a governance gap.
- Production Python versions and the offline image wheelhouse are checked exactly, but the
  constraints do not yet carry reviewed package hashes and installs do not use `--require-hashes`.
  A lock refresh therefore still needs a controlled hash-generation and review procedure.
- Artifact storage remains constrained. Workflow-owned Python and container evidence uploads for
  run 29217837100 succeeded, but Docker's additional build-record artifact still reported a quota
  warning. Durable evidence and scientific releases still require a separate approved store.
- Schema v2 and the explicit v1-to-v2 migration have been tested on the scale80 snapshot. Durable
  scheduled backups, maintenance-mode enforcement against unrelated writers and periodic restore
  ownership remain deployment requirements.
- Digest-addressed staging verifies content before activation, but staged files are not made
  filesystem-immutable. The release root still requires restrictive ownership/permissions, and an
  external writer can invalidate the assumptions behind SQLite `immutable=1`.
- Recovery locking coordinates this project's recovery commands only; it cannot stop an unrelated
  SQLite writer. Overwrite restore must never target a database used by a running process.
- The dataset release manifest binds the database and payload files, but it does not yet bind the
  dataset bundle digest to the published container image digest in one deployment manifest.
- No durable scientific dataset release or immutable version 0.12 GHCR deployment has yet been
  demonstrated.
- A bound Qwen model/backend completed scale80 inference and protocol freeze, but no human-reference
  extraction evaluation has been executed.
- The repository does not contain an authorised project/data `LICENSE` or `CITATION.cff`.
- Metrics and logs exist, but no external collector, dashboard, alert route or approved SLO has been
  deployed.
- TLS, authentication, rate limiting, request-size enforcement and public access logging remain
  ingress responsibilities.
- PostgreSQL migration remains necessary before concurrent writers, continuous ingestion or shared
  mutable state across replicas are introduced.

## Production acceptance decision

A production owner should approve promotion only when all of the following are true:

- the exact commit and immutable image digest passed every required cloud gate;
- a complete release bundle passes `mdmeta-release verify` after download from its durable store;
- the server starts with the required production environment and reports the expected database and
  build digests;
- a candidate deployment passes readiness and representative biological queries;
- backup, restore and rollback have been exercised in the target environment;
- ingress and monitoring controls are active; and
- governance metadata, SLO/RPO/RTO, on-call ownership and incident procedures are approved.

Until then, the accurate description is **version 0.12 production-candidate engineering with
repository and CSC data-path gates passed, while governed release, public deployment and
operational acceptance remain pending**.
