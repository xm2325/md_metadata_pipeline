# Operations and data lifecycle

## Workload separation

- **Ingestion:** GitHub Actions jobs triggered on `main` or by manual dispatch, depending on the
  workflow. These may contact Europe PMC, PDBe, UniProt and MDDB and may use large ephemeral runner
  storage.
- **Validation:** deterministic pull-request tests use fixtures and mocked network responses. Live
  upstream checks run on `main` or manual dispatch.
- **Serving:** the API container reads one immutable, verified SQLite snapshot. It has no write
  endpoint and receives no GitHub credentials.

JATS snapshots stay in `$RUNNER_TEMP` and are deleted before upload. File-backed PSF, PDB and XTC
assets stay only in the runner's job-local working tree and are excluded from artifacts; the
GitHub-hosted runner is discarded after the job. Caches are limited to pip downloads and Docker
layers. Scientific outputs never use caches because caches are evictable and are not an evidence
store.

## GitHub Actions storage

The repository has already observed `Failed to CreateArtifact: Artifact storage quota has been
hit` on otherwise successful scientific runs. A green compute step therefore does not prove that
its output was retained.

The server-readiness workflow includes a read-only inventory job that lists repository artifacts
and caches in `$GITHUB_STEP_SUMMARY` without creating another artifact. Apply this retention policy:

| Output class | Storage | Retention |
|---|---|---:|
| dependency downloads and Docker layers | Actions cache | evictable, repository policy |
| PR test reports and failure diagnostics | Actions artifact | 3–7 days |
| successful `main` integration bundles | Actions artifact staging | 14–30 days |
| landmark human benchmark | release/institutional repository | durable |
| JATS and MD trajectory intermediates | runner temporary disk | job lifetime |

Before deleting artifacts, identify landmark benchmarks and human annotation workpacks and copy
them to their durable destination. Artifact deletion is irreversible. Changing repository
retention affects new artifacts only; it does not shorten existing objects.

## Release acceptance

A release candidate is rejected when any of these is true:

- scientific acceptance checks fail;
- SQLite integrity is not `ok` or foreign-key violations are present;
- source or output checksums differ;
- the run is partial but lacks an explicit partial/failure state;
- the code, dependency, model/prompt, input-manifest or image version is missing;
- the result bundle could not be persisted to a durable destination.

The release manifest should record the Git commit, package version, workflow run/attempt, Python
version, container digest, dependency-lock digest, source-manifest digest, dataset digest,
completion state, timestamps and licences.

## Monitoring

At minimum, monitor:

- `/livez` and `/readyz` availability;
- request count, status, latency and rejected-input count at the reverse proxy;
- served dataset/build digests from `/metadata`;
- disk space and release-directory growth;
- age of the current dataset;
- upstream validation failure, retry and unresolved-state rates during ingestion;
- Actions minutes, artifact upload outcome and cache size.

Do not turn upstream network failure or malformed service responses into biological conflicts. The
pipeline records those outcomes as unresolved so alerting and scientific interpretation stay
separate.

When production supplies a 64-digit `MDMETA_DATASET_SHA256`, the served dataset digest is verified
against the finalized `records.sqlite` file at startup. Production must not use the `unversioned`
development placeholder. The build SHA remains image metadata and should be bound to the GHCR
image digest in the release manifest.

## Incident and recovery runbook

1. Stop promotion; do not mutate the current release.
2. Capture the build SHA, dataset SHA, failing request/run ID and relevant logs.
3. If serving is affected, repoint `current` to the previous verified release and restart.
4. Re-run readiness and representative PDB/UniProt queries.
5. Reproduce ingestion on a fresh runner cache; do not silently reuse a result labelled as live.
6. Record root cause, affected dataset versions, corrective tests and whether downstream users need
   notification.

Test restore and rollback periodically. A backup that has never passed checksum, integrity and
query smoke tests is not a verified backup.

## Security boundary

- Run the API as the non-root image user with a read-only root filesystem and dataset mount.
- Keep TLS, authentication, rate limiting and request-size controls at the ingress/reverse proxy.
- Never expose server-local asset paths; API responses redact `local_path`.
- Never place tokens, `.env` files, databases, runtime logs or large results in Git.
- Scan Python dependencies and the final image, generate an SBOM, and pin/update base images and
  Actions through automated dependency PRs.
- Treat literature excerpts and annotation workpacks according to their licences and access rules.
