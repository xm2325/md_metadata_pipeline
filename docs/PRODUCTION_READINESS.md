# Production readiness status

The repository is **not yet fully production ready**. It now contains a substantially stronger
production candidate, but code in the current version 0.11 change set must still pass its first
GitHub Actions run and several deployment, governance and service-management decisions remain
outside the repository.

## Evidence boundary

Three different kinds of evidence must not be conflated:

| State | What it means |
|---|---|
| Previously cloud-validated | The version 0.10 Python, installed-wheel and hardened-container paths passed PR #30 on 2026-07-11. |
| Implemented, cloud validation pending | Version 0.11 adds stricter data contracts, recovery/release tooling, typed API contracts, production configuration checks, structured request logging, Prometheus metrics and additional security controls. These claims describe code, not a successful current Actions run. |
| External decision or deployment required | Dataset identity and licence, publisher/creators, durable archive, image promotion, DNS/TLS, authentication policy, rate limits, monitoring ownership, SLOs, RPO/RTO and incident ownership cannot be established by repository code alone. |

The previous version 0.10 Actions result does not validate the new version 0.11 paths. A current
commit is promotable only after all required Actions jobs pass and their exact commit and image
digests are recorded.

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

## Still awaiting cloud validation

Before describing version 0.11 as release-ready, GitHub Actions must demonstrate on the exact
candidate commit that:

1. Python 3.11 and 3.12 lint, tests and coverage pass;
2. committed JSON Schema artifacts match their Pydantic models;
3. strict SQLite schema and semantic-record checks pass;
4. WAL backup, restore, failure cleanup and overwrite rollback tests pass;
5. release tamper tests and A → B → A activation/rollback tests pass;
6. the installed wheel exposes every documented CLI;
7. the non-root/read-only container passes production-mode API, metrics and shutdown checks;
8. blocking dependency and Bandit gates pass, and approved immutable-SHA secret-history and
   container-CVE scanners are added and pass;
9. the exact image digest, SBOM and provenance are published successfully; and
10. required evidence is retained somewhere durable rather than being lost to the current Actions
    artifact quota.

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
- The account artifact quota is full. Test execution can still be observed in job logs, but durable
  evidence and scientific releases require a separate approved store.
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

Until then, the accurate description is **production-candidate engineering with cloud and
operational acceptance pending**.
