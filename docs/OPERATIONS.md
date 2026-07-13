# Operations and data lifecycle

This is an operational contract for a future service, not evidence of an active production service.
Version 0.11 observability, recovery and release code is implemented in the current change set but
its repository cloud gates passed for commit `c2981e2` on 2026-07-13. A live release,
target-environment exercise and operational ownership remain pending.

## Workload separation

- **Ingestion:** GitHub Actions or a separately scheduled worker contacts Europe PMC, PDBe, UniProt
  and MDDB. It is the only writer and may use large ephemeral storage.
- **Validation:** deterministic pull-request tests use fixtures and mocked responses. Current live
  upstream checks run only on `main` or manual dispatch.
- **Release:** a successful ingestion result is finalized, semantically verified, sealed as a strict
  bundle and copied to durable storage.
- **Serving:** the API receives no GitHub/upstream credentials and reads one immutable SQLite
  snapshot. It has no write endpoint.
- **Monitoring and ingress:** separate infrastructure terminates TLS, applies access policy and
  scrapes internal metrics.

JATS snapshots remain in `$RUNNER_TEMP` and are deleted before upload. PSF, PDB and XTC runtime
assets remain on job-local runner storage and are excluded from result artifacts. Caches are limited
to dependency downloads and Docker layers; an evictable cache is never scientific evidence.

## Release states

Use explicit states rather than treating a green compute step as a release:

1. **computed** — ingestion finished, but outputs may not be finalized or retained;
2. **verified** — scientific gates, SQLite integrity/foreign keys, semantic records and file hashes
   pass;
3. **sealed** — `mdmeta-release create` produced a strict manifest and bundle digest;
4. **archived** — the sealed bundle exists in its durable governed destination and verifies after
   download;
5. **staged** — the archive copy was verified and copied to a digest-addressed server directory;
6. **active** — the `current` pointer and container use the expected bundle/database/image digests;
7. **retired** — no longer active, retained or deleted according to an approved policy.

Never skip from computed to active.

## GitHub Actions storage

The repository has observed `Failed to CreateArtifact: Artifact storage quota has been hit` on
otherwise successful jobs. In Server readiness run
[29217837100](https://github.com/xm2325/md_metadata_pipeline/actions/runs/29217837100), the
workflow-owned Python and container evidence uploads succeeded, but Docker's additional
build-record artifact still emitted a quota warning. A green compute step therefore does not prove
that every output was retained, and the quota must not be described as fully recovered.

| Output class | Storage | Retention |
|---|---|---:|
| dependency downloads and Docker layers | Actions cache | evictable, repository policy |
| PR test reports and failure diagnostics | Actions artifact | 3–7 days |
| successful `main` integration bundles | Actions artifact staging | 14–30 days |
| landmark benchmark or production dataset | governed release/institutional repository | durable policy required |
| JATS and MD trajectory intermediates | runner temporary disk | job lifetime |

Before deleting artifacts, identify human workpacks and landmark benchmarks and copy them to their
approved destination. Artifact deletion is irreversible. The durable destination, retention,
deprecation and deletion owner remain governance decisions.

## Release acceptance

Reject a candidate when any of these is true:

- a required cloud job did not pass on the exact commit;
- scientific acceptance checks fail or completion is partial/ambiguous;
- SQLite integrity, foreign keys, strict schema or semantic-record checks fail;
- any source, payload, database, manifest or bundle digest differs;
- the dataset identifier, version, licence, creators or publisher is absent or a placeholder;
- Git commit, package, dependency input, workflow run or source-manifest provenance is missing;
- the image is a mutable tag or lacks a successful SBOM/provenance publication;
- the exact bundle cannot be verified after download from durable storage;
- deployment has no tested previous release for rollback; or
- ingress, monitoring, ownership or incident requirements are not active.

The current release manifest binds dataset payloads but not the container digest. Until a separate
deployment manifest binds them, retain an external immutable deployment record containing the
bundle digest, database digest, image digest and full Git commit.

## Service observability

The application writes one structured JSON event per request with request ID, method, normalized
route, status, latency, version, build SHA and dataset SHA. It returns `X-Request-ID` so an ingress
request can be correlated with application logs. Uvicorn's separate access log is disabled to avoid
duplicate unstructured events.

`/metrics` exposes bounded-label per-process metrics:

- `mdmeta_http_requests_total` by method, route and status;
- `mdmeta_http_request_duration_seconds` by method and route;
- `mdmeta_http_requests_in_flight`;
- `mdmeta_build_info` with version/build/dataset identity; and
- `mdmeta_dataset_articles` captured at startup.

The endpoint has no application authentication. Keep it on localhost or a private monitoring
network and deny `/metrics` at public ingress. Never add document IDs, PDB IDs, UniProt accessions,
request IDs or raw paths as metric labels; that would create unbounded cardinality and potentially
leak query data.

At minimum, an external monitoring system must also collect:

- `/livez` and `/readyz` availability;
- container restarts, CPU, memory, file descriptors and disk space;
- release-directory and backup-store growth;
- age of the active dataset and its expected digests;
- reverse-proxy TLS, authentication, rejection, request-size and rate-limit events;
- ingestion retry, failure and unresolved-state rates; and
- Actions duration, security result, artifact-upload outcome and cache use.

Upstream timeout or malformed data is an operational failure/unresolved validation, not a
biological conflict. Alerting must preserve that distinction.

## SLI and SLO decisions

The repository provides signals but does not set service-level objectives. Before launch, an
authorised service owner must approve targets, measurement windows, exclusions and alert routes for:

| SLI | Source | Decision still required |
|---|---|---|
| availability | successful `/readyz` probes through the intended user path | target, window, planned-maintenance treatment |
| latency | request-duration histogram, separated by route | percentile and threshold per route class |
| errors | non-user 5xx rate and container failures | error-budget target and burn-rate alerts |
| data freshness | active dataset creation/publication time | maximum acceptable age |
| data correctness | digest/schema/semantic verification and scientific gates | release-blocking policy |
| recovery | successful restore and rollback exercise | RPO, RTO and exercise frequency |

Do not copy arbitrary SLO percentages into production. Capacity/load testing and stakeholder needs
must justify the values. Alert destinations need a named responder and escalation path.

## Backup policy

Use `mdmeta-recovery backup` for a mutable ingestion database. It invokes SQLite's online backup API
so committed WAL frames are included without checkpointing the source. It verifies and fsyncs a
temporary destination before atomic publication.

Operational policy must define:

- schedule and event-triggered backups before migration or ingestion changes;
- encrypted backup location and access controls;
- retention and deletion;
- expected article count and digest evidence;
- replication to a separate failure domain;
- RPO/RTO; and
- a named owner for automated restore exercises.

A backup is not verified merely because a file exists. It must pass hash, SQLite, semantic-record
and representative-query checks after restoration.

## Restore and rollback exercise

At an approved frequency and before major releases:

1. select a backup without changing the active service;
2. restore it into a new candidate path using `mdmeta-recovery restore` and its expected digest;
3. run `mdmeta-verify-database` and representative PDB/UniProt queries;
4. seal and stage the restored snapshot as a new immutable release if it is to be deployable;
5. activate release A, then B, then roll back to A using `mdmeta-release`;
6. force-recreate the container after every symlink change;
7. verify `/readyz`, `/metadata`, query results and observed recovery time; and
8. record evidence, deviations and follow-up work.

Do not use `--overwrite` against the database mounted by a running container. Never overwrite a
file beneath a process that opened SQLite with `immutable=1`.

## Incident runbook

1. Stop promotion and preserve the active and failed release directories.
2. Capture request/run IDs, timestamps, full Git SHA, image digest, bundle digest, database digest,
   active release ID and relevant JSON logs.
3. Decide whether the issue is serving, data integrity, upstream ingestion or security related.
4. If users are affected, verify and activate the prior release, then force-recreate the container.
5. Re-run readiness, metadata and representative biological queries through the intended ingress.
6. Reproduce ingestion on a fresh runner cache; do not silently relabel stale output as a live run.
7. Assess affected dataset versions and downstream users and follow the approved notification path.
8. Record root cause, corrective tests, recovery time and whether SLO/RPO/RTO were met.

If the prior release does not verify, stop rather than promoting an unknown snapshot.

## Security and privacy boundary

- Keep the container non-root with read-only root and dataset filesystems.
- Terminate TLS and enforce authentication/authorisation, rate, abuse and request-size controls at
  the managed ingress.
- Trust forwarding headers only from the named proxy; never configure `*`.
- Keep interactive docs disabled and use an explicit Host allowlist in production.
- Never publicly route `/metrics`.
- Never expose server-local asset paths; public models redact them.
- Never commit tokens, `.env` files, databases, runtime logs, backups or large results.
- Scan dependencies, source and final images; retain the SBOM and provenance for the exact digest.
- Apply approved retention/privacy rules to logs, literature excerpts and annotation workpacks.
- Rotate credentials and certificates through institutional secret management; the API container
  should not receive GitHub or upstream ingestion credentials.

## Current operational blockers

Production still requires a durable archive, approved metadata/licensing, a published image,
target-host deployment, TLS/access policy, Prometheus/log collection, dashboards/alerts, SLO and
RPO/RTO decisions, backup automation and named service/on-call ownership. The presence of code and
runbooks does not satisfy those external responsibilities.
