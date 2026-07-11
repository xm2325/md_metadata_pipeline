# Server deployment

This project separates scientific ingestion from serving. GitHub Actions workflows are configured
to build and validate a versioned SQLite snapshot; a small FastAPI container serves that snapshot
read-only. The upgraded Python, installed-wheel and hardened container paths passed their first
GitHub-hosted PR run on 2026-07-11. Do not run the live database from OneDrive, NFS, or another
synchronised filesystem.

## Deployment contract

A deployable dataset bundle contains at least:

- `records.sqlite`;
- `database-manifest.json` from `mdmeta-verify-database`;
- compact JSON records and scientific run summaries;
- `SHA256SUMS.txt` covering every bundled file;
- the source-manifest digest, Git commit SHA, workflow run URL and package version.

The bundle is accepted only when the scientific workflow passes, SQLite reports `integrity=ok`,
there are no foreign-key violations, and every checksum matches. GitHub Actions artifacts are a
short-lived staging area, not the authoritative archive. Promote accepted bundles to a GitHub
Release or an institutional object store before production deployment.

`MDMETA_DATASET_SHA256` specifically means the SHA-256 of the finalized single-file
`records.sqlite`, as recorded in `database-manifest.json`. When this variable contains a 64-digit
hexadecimal digest, read-only startup hashes the mounted database and fails closed if it differs.
The development placeholder `unversioned` skips that comparison and is forbidden for production.
A future whole-bundle digest should use a separate field rather than overloading this value.

## Cloud validation

`.github/workflows/server-readiness.yml` is configured to run entirely on GitHub-hosted Ubuntu
runners. [PR run 29152448584](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29152448584)
passed on 2026-07-11. The workflow:

1. run Ruff, pytest, branch coverage, wheel construction and `pip check`;
2. emit JUnit, coverage and dependency-audit reports;
3. build the API image with GitHub Actions Docker-layer cache;
4. initialise a temporary snapshot, then serve it from a read-only volume in a non-root,
   capability-free, read-only container;
5. check `/readyz`, `/metadata`, `/openapi.json` and the container user;
6. report artifact/cache consumption in the job summary without consuming artifact quota.

Artifact uploads are deliberately short-lived. If quota prevents persistence, the workflow writes
an explicit warning to the job summary rather than presenting the missing evidence as stored.

## Prepare a snapshot

After an ingestion workflow has produced a database, checkpoint, verify and hash it before moving
it:

```bash
mdmeta-verify-database \
  --database results/integrated_60/records.sqlite \
  --checkpoint \
  --output results/integrated_60/database-manifest.json

cd results/integrated_60
sha256sum --check SHA256SUMS.txt
```

`--checkpoint` is for the single writer before packaging. The production API must use
`MDMETA_DATABASE_READ_ONLY=true` and must never checkpoint or ingest.

## Build for local acceptance only

`docker compose up --build` is useful for local acceptance testing, but it resolves dependencies
again. A local rebuild is not the exact version 0.10 image that passed the GitHub-hosted container
smoke test. Do not use a server-side rebuild as a production release.

The manual/tag-triggered `Publish API container` workflow is configured to publish the image, SBOM
and provenance to GHCR. Its first publication is pending. Production must use an immutable image
digest reported by a successful publication run:

```bash
export MDMETA_IMAGE=ghcr.io/xm2325/md_metadata_pipeline@sha256:<image-digest>
```

## Start with Docker Compose

On the server, place the verified snapshot on local disk:

```text
/srv/mdmeta/
├── current -> releases/<dataset-sha256>
└── releases/
    └── <dataset-sha256>/
        ├── records.sqlite
        ├── database-manifest.json
        └── SHA256SUMS.txt
```

Set the deployment environment:

```bash
export MDMETA_DATA_DIR=/srv/mdmeta/current
export MDMETA_DATASET_SHA256=<dataset-sha256>
export MDMETA_BUILD_SHA=<git-commit-sha>
export MDMETA_IMAGE=ghcr.io/xm2325/md_metadata_pipeline@sha256:<image-digest>
docker compose pull
docker compose up --detach --no-build --force-recreate
```

The supplied Compose configuration binds the service only to `127.0.0.1:8000`, mounts the dataset
read-only, drops all Linux capabilities, prevents privilege escalation, and keeps the container
root filesystem read-only. The host release directory must already exist (`create_host_path` is
disabled) and UID 10001 needs read permission plus execute/traverse permission on its parent
directories. Verify it:

```bash
curl --fail http://127.0.0.1:8000/livez
curl --fail http://127.0.0.1:8000/readyz
curl --fail http://127.0.0.1:8000/metadata
```

Put a managed TLS reverse proxy or institutional ingress in front of the localhost listener. Apply
authentication, rate limits, request-size limits and access logging there when the service is not
intentionally public.

## Atomic update and rollback

1. Download a new bundle into a new `/srv/mdmeta/releases/<digest>` directory.
2. Verify checksums and run `mdmeta-verify-database` against it without `--checkpoint`.
3. Start a candidate container on a different localhost port and run readiness/query smoke tests.
4. Atomically repoint `/srv/mdmeta/current` to the new release, then run
   `docker compose up --detach --no-build --force-recreate`. Docker resolves bind-source symlinks
   when creating a container, so a simple restart may keep the old target.
5. Confirm `/metadata` reports the expected database and build digests. Keep the previous release
   until the observation window passes; rollback by restoring the old symlink and force-recreating
   the container again.

Never overwrite the database file underneath a running process. Do not copy a mutable WAL database
as a backup; checkpoint it while ingestion is stopped or use SQLite's backup API.

## When SQLite is no longer enough

The snapshot design is appropriate for one offline writer and one or more readers of an immutable
release. Migrate to PostgreSQL before introducing concurrent writers, continuous ingestion,
queue-driven updates, or multiple API replicas that must observe mutable shared state. Add Neo4j
only when concrete graph queries justify a second persistence model.
