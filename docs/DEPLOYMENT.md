# Server deployment

This project separates scientific ingestion from serving. Ingestion produces a finalized dataset
bundle; a small FastAPI container serves one verified SQLite snapshot read-only. Do not serve the
database from OneDrive, NFS or another synchronised filesystem.

The version 0.10 Python, installed-wheel and hardened-container paths passed a GitHub-hosted PR run
on 2026-07-11. Version 0.11 adds the release, recovery, contract and observability procedures below,
but those additions still require their first successful Actions run. This document is a production
deployment procedure, not evidence that a production deployment already exists.

See [Production readiness](PRODUCTION_READINESS.md) for the acceptance boundary.

## Deployment contract

A sealed dataset bundle contains at least:

- `records.sqlite`, finalized in DELETE journal mode with no WAL, SHM or rollback-journal sidecar;
- `database-manifest.json` from `mdmeta-verify-database`;
- `release-manifest.json` with explicit dataset and workflow provenance;
- `SHA256SUMS.txt` covering every payload file and the release manifest; and
- any compact records, public contract artifacts and scientific run summaries being released.

`mdmeta-release` rejects path traversal, symlinks, duplicate, missing or extra files, hash/size
drift, an invalid database, schema mismatch, placeholder governance metadata and inconsistent
database manifests. The canonical `bundle_sha256` commits the release-manifest core and every
payload file digest.

Two digests have different meanings:

- `MDMETA_DATASET_SHA256` is the SHA-256 of the finalized single-file `records.sqlite`;
- `bundle_sha256` identifies the complete sealed directory and is used as its release-directory
  name.

Do not overload one with the other. The current dataset release manifest does not yet bind its
bundle digest to the GHCR image digest in one deployment manifest. Until that is implemented, the
operator must record both immutable digests and the Git commit in the deployment record.

GitHub Actions artifacts are a short-lived staging mechanism, not an authoritative archive. A
candidate is not deployable until the bundle has been copied to a durable GitHub Release,
institutional repository or governed object store and verified again after download.

## Cloud validation boundary

[PR run 29152448584](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29152448584)
passed the version 0.10 compute gates on 2026-07-11. Optional evidence uploads failed because the
account artifact quota was full, and that failure was reported in the job summary.

The current version 0.11 commit still needs cloud evidence for:

1. strict JSON Schema drift checks and installed CLI entry points;
2. semantic database verification;
3. WAL backup, restore and failure rollback;
4. release tamper rejection and A → B → A activation/rollback;
5. production-mode API, structured logs, metrics and graceful shutdown;
6. dependency/static/container security scans; and
7. immutable GHCR publication with SBOM and build provenance.

Do not promote merely because an earlier commit was green.

## Export and check public contracts

Generate the versioned schemas during development and require check mode in release CI:

```bash
mdmeta-export-contracts --output-dir schemas
mdmeta-export-contracts --output-dir schemas --check
```

The contracts cover the integrated MD record, the file-backed MD report and the dataset release
manifest. A schema change requires a versioning/compatibility decision; the current SQLite database
schema is strictly checked at version 1 but does not yet have a v1 → v2 migration framework.

## Prepare and seal a dataset

Only the single ingestion writer may finalize a snapshot:

```bash
mdmeta-verify-database \
  --database "$BUNDLE_DIR/records.sqlite" \
  --checkpoint \
  --expected-articles "$EXPECTED_ARTICLES" \
  --output "$BUNDLE_DIR/database-manifest.json"
```

`--checkpoint` is forbidden in the serving process. It checkpoints the writer's WAL and converts
the candidate to a portable DELETE-journal snapshot.

Seal the directory using real values approved for this dataset. The CLI records its installed
package version and hashes the dependency lock and optional source manifest itself:

```bash
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

Creation requires explicit dataset identifier, version, title, licence, creator, publisher and
timestamp, plus package/Git/workflow, dependency-lock and source-manifest provenance as applicable.

Dataset identity, licence, creator and publisher are governance inputs. The repository deliberately
does not invent them. Omit `--source-manifest` only when a release genuinely has no source manifest;
do not substitute a fake file or digest.

## Publish the API image

Do not build on the server. A server-side rebuild resolves dependencies again and is not the image
that passed cloud validation. The manual/tag-triggered `Publish API container` workflow is intended
to publish an exact GHCR digest with SBOM and provenance. Its version 0.11 success is pending.

Production must use an immutable digest:

```bash
export MDMETA_IMAGE="ghcr.io/xm2325/md_metadata_pipeline@sha256:${IMAGE_DIGEST:?set IMAGE_DIGEST}"
```

Record the image digest, bundle digest, database digest and full Git commit together.

## Stage a release on the server

Copy an accepted bundle from its durable store into a temporary incoming directory on local server
storage, then verify and stage it:

```bash
mdmeta-release verify --bundle-dir "$INCOMING_BUNDLE"

mdmeta-release stage \
  --bundle-dir "$INCOMING_BUNDLE" \
  --release-root /srv/mdmeta
```

The staged layout is:

```text
/srv/mdmeta/
├── current -> releases/<bundle-sha256>
└── releases/
    └── <bundle-sha256>/
        ├── records.sqlite
        ├── database-manifest.json
        ├── release-manifest.json
        ├── SHA256SUMS.txt
        └── ...other inventoried payload files
```

Staging copies to a temporary directory, verifies it again, fsyncs the files/directories and only
then publishes the digest-addressed release directory. Existing release directories are never
silently overwritten.

## Required production environment

The Compose file supplies several fixed safe values. The operator must set the values that depend
on the deployed release and ingress:

| Variable | Production requirement |
|---|---|
| `MDMETA_ENV` | `production`; Compose sets it. |
| `MDMETA_DATA_DIR` | `/srv/mdmeta/current` or the equivalent local release pointer. |
| `MDMETA_DATABASE_PATH` | `/data/records.sqlite`; Compose sets it. |
| `MDMETA_DATABASE_READ_ONLY` | `true`; production rejects writable mode. |
| `MDMETA_DATASET_SHA256` | Exact 64-character database digest from the release manifest. |
| `MDMETA_BUILD_SHA` | Full 40-character SHA-1 or 64-character SHA-256 Git commit; abbreviated SHAs are rejected. |
| `MDMETA_IMAGE` | Exact GHCR `image@sha256:...`, never a mutable tag. |
| `MDMETA_ALLOWED_HOSTS` | Unique hostname/IP patterns without scheme, port or userinfo; include the public host plus `127.0.0.1` and `localhost` for container health checks. Production rejects `*`, malformed wildcards and duplicates. |
| `MDMETA_FORWARDED_ALLOW_IPS` | Only the trusted reverse-proxy address or CIDR, never `*`. |
| `MDMETA_PROXY_HEADERS` | `true` only behind that trusted proxy; otherwise `false`. |
| `MDMETA_WORKERS` | `1` per container; scale with immutable replicas rather than in-process workers. |
| `MDMETA_ENABLE_DOCS` | `false`; production rejects interactive docs. |
| `MDMETA_LIMIT_CONCURRENCY` | Capacity-tested request concurrency, default `100`. |
| `MDMETA_BACKLOG` | Capacity-tested listen backlog, default `128`. |
| `MDMETA_TIMEOUT_KEEP_ALIVE` | Ingress-aligned keep-alive timeout, default `5` seconds. |
| `MDMETA_TIMEOUT_GRACEFUL_SHUTDOWN` | Less than the container stop grace period, default `25` seconds. |
| `MDMETA_LOG_LEVEL` | Normally `info`; logs are structured JSON on stdout. |

Example:

```bash
export MDMETA_DATA_DIR=/srv/mdmeta/current
export MDMETA_DATASET_SHA256="${DATABASE_SHA256:?set DATABASE_SHA256}"
export MDMETA_BUILD_SHA="${GIT_COMMIT:?set GIT_COMMIT}"
export MDMETA_IMAGE="ghcr.io/xm2325/md_metadata_pipeline@sha256:${IMAGE_DIGEST:?set IMAGE_DIGEST}"
export MDMETA_ALLOWED_HOSTS=api.example.org,127.0.0.1,localhost
export MDMETA_FORWARDED_ALLOW_IPS="${TRUSTED_PROXY:?set TRUSTED_PROXY}"

docker compose pull
docker compose up --detach --no-build --force-recreate
```

The service is bound to `127.0.0.1:8000` on the host. UID 10001 needs read permission on the bundle
and traverse permission on all parent directories. The container has a read-only root filesystem
and dataset mount, drops all Linux capabilities and prevents privilege escalation.

## Activate and verify

Start a candidate on a separate localhost port first. After it passes representative queries,
activate the staged release and force-create the normal service:

```bash
RELEASE_ID="${VERIFIED_BUNDLE_SHA256:?set VERIFIED_BUNDLE_SHA256}"

mdmeta-release activate \
  --release-root /srv/mdmeta \
  --release-id "$RELEASE_ID"

docker compose up --detach --no-build --force-recreate

curl --fail http://127.0.0.1:8000/livez
curl --fail http://127.0.0.1:8000/readyz
curl --fail http://127.0.0.1:8000/metadata
curl --fail 'http://127.0.0.1:8000/search?pdb_id=6VSB'
```

Confirm that `/metadata` reports the expected database and build digests. Docker resolves a bind
source symlink when it creates the container, so changing `current` without `--force-recreate` can
leave the old release mounted.

## Metrics and ingress

`/metrics` exposes per-process Prometheus counters, latency histograms, in-flight requests,
article count and build/dataset identity. It has no application-level authentication and is omitted
from the public OpenAPI document. Scrape it only over localhost or a private monitoring network and
configure the public reverse proxy to deny that path.

A managed institutional ingress is still required for:

- TLS certificates and HTTPS redirect;
- authentication/authorisation if the API is not intentionally public;
- rate limiting, abuse controls and request-size limits;
- trusted forwarding-header handling;
- public access logging and retention; and
- maintenance/error responses during deployment.

Repository security headers and Host validation complement this boundary; they do not replace it.

## Back up a mutable ingestion database

Do not copy a live WAL database with `cp`. Use SQLite's online backup API:

```bash
BACKUP_DIR="/srv/mdmeta-backups/${BACKUP_ID:?set BACKUP_ID}"
mkdir -p "$BACKUP_DIR"

mdmeta-recovery backup \
  --source /srv/mdmeta-ingest/records.sqlite \
  --destination "$BACKUP_DIR/records.sqlite" \
  --expected-articles "$EXPECTED_ARTICLES" \
  > "$BACKUP_DIR/backup-report.json"
```

The command reads committed WAL frames without checkpointing or changing the source journal. It
finalizes and verifies a temporary destination, fsyncs it and atomically installs it. Copy the
backup and report to governed backup storage with encryption and access controls. A schedule,
retention policy, RPO and backup owner are still external operational decisions.

## Restore test

Restore into a new candidate location, never over the running database:

```bash
BACKUP_DIR="/srv/mdmeta-backups/${BACKUP_ID:?set BACKUP_ID}"

mdmeta-recovery restore \
  --snapshot "$BACKUP_DIR/records.sqlite" \
  --destination /srv/mdmeta/restore-candidate/records.sqlite \
  --expected-sha256 "$BACKUP_DATABASE_SHA256" \
  --expected-articles "$EXPECTED_ARTICLES"

mdmeta-verify-database \
  --database /srv/mdmeta/restore-candidate/records.sqlite \
  --expected-articles "$EXPECTED_ARTICLES"
```

Run representative queries against the restored snapshot. To deploy it, build a complete release
bundle, seal it, stage it and follow the normal activation procedure. `--overwrite` exists for
controlled recovery but should not be used on the live `current` target.

## Rollback

Keep the prior release through the observation window. To roll back:

```bash
PREVIOUS_RELEASE_ID="${PREVIOUS_BUNDLE_SHA256:?set PREVIOUS_BUNDLE_SHA256}"

mdmeta-release rollback \
  --release-root /srv/mdmeta \
  --release-id "$PREVIOUS_RELEASE_ID"

docker compose up --detach --no-build --force-recreate

curl --fail http://127.0.0.1:8000/readyz
curl --fail http://127.0.0.1:8000/metadata
curl --fail 'http://127.0.0.1:8000/search?pdb_id=6VSB'
```

Rollback verifies the old bundle before atomically switching `current`. If activation or
post-deployment checks fail, leave the failed release immutable for investigation and record the
bundle, database, image and build digests in the incident.

## When SQLite is no longer enough

The snapshot design supports one offline writer and one or more readers of immutable releases.
Move to PostgreSQL before adding concurrent writers, continuous ingestion, queue-driven updates or
replicas that must share mutable state. Add Neo4j only when concrete graph queries justify a second
persistence model. A versioned SQLite migration framework is also required before changing the
current database schema.
