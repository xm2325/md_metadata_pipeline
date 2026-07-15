# Production readiness status

The repository is **not yet fully production ready**. It now contains a substantially stronger
production candidate whose repository cloud gates passed for commit `c2981e2` on 2026-07-13.
Live release execution, image publication, target-server deployment and several governance and
service-management decisions remain outside that evidence.

## Evidence boundary

Three different kinds of evidence must not be conflated:

| State | What it means |
|---|---|
| Repository cloud-validated | For version 0.11 commit `c2981e2`, Python 3.11/3.12 CI, committed-contract drift, installed-wheel release/recovery/API tests, exact dependency audit, Bandit, hardened container smoke and the three deterministic domain-workflow PR paths passed on 2026-07-13. |
| GPU infrastructure validated | CSC Roihu Slurm job `184708` bound to commit `cc87d7a` passed on one GH200 on 2026-07-15, including FP32 correctness, BF16 GEMM, CUDA attention, non-zero utilisation and result checksum gates. This is infrastructure evidence, not a validated model backend. |
| Live/release validation pending | Pull-request live scientific jobs were skipped by design. No version 0.11 dataset bundle, GHCR image/SBOM/provenance or target-server deployment was published or exercised by these runs. |
| External decision or deployment required | Dataset identity and licence, publisher/creators, durable archive, image promotion, DNS/TLS, authentication policy, rate limits, monitoring ownership, SLOs, RPO/RTO and incident ownership cannot be established by repository code alone. |

The dated checks validate repository code at `c2981e2`; they do not create a promotable release.
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

## Cloud validation evidence and remaining release gates

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
successful remote Slurm execution for commit `cc87d7a`. GitHub-hosted jobs for that later head were
blocked before runner startup by the account billing/payment or Actions spending limit. They are
therefore not represented as passing repository gates, and the last fully executed GitHub evidence
remains `c2981e2` until billing is fixed and the current head is rerun.

Before describing version 0.11 as release-ready or deployed, the project still needs:

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

- The private-repository plan currently prevents branch protection/rulesets and a protected
  production environment. Required checks and promotion approval therefore cannot yet be enforced
  as repository policy.
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
- SQLite schema version 1 is checked strictly, but there is not yet a versioned v1 → v2 migration
  framework. A schema change must not be deployed until forward migration and recovery are tested.
- Digest-addressed staging verifies content before activation, but staged files are not made
  filesystem-immutable. The release root still requires restrictive ownership/permissions, and an
  external writer can invalidate the assumptions behind SQLite `immutable=1`.
- Recovery locking coordinates this project's recovery commands only; it cannot stop an unrelated
  SQLite writer. Overwrite restore must never target a database used by a running process.
- The dataset release manifest binds the database and payload files, but it does not yet bind the
  dataset bundle digest to the published container image digest in one deployment manifest.
- No durable scientific dataset release or immutable version 0.11 GHCR deployment has yet been
  demonstrated.
- A real Roihu GH200 infrastructure gate has passed, but no concrete local-model backend, bound
  model/tokenizer artefact or human-reference extraction evaluation has been executed.
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

Until then, the accurate description is **production-candidate engineering with repository cloud
gates passed for `c2981e2`, while release, deployment and operational acceptance remain pending**.
