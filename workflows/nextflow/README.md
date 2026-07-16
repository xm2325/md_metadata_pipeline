# Resumable production post-processing

This DSL2 workflow turns one immutable schema-v2 SQLite snapshot and its exact
model-audit summary into independently verifiable production deliverables:

1. verify SQLite structure, records, sidecars, journal mode, and article count;
2. build the risk-based human-review queue with evidence locators and prompts;
3. export deterministic Neo4j nodes and relationships;
4. re-verify both exports against the source snapshot and emit checksums.

It deliberately starts after network ingestion and GPU inference. Those stages
have different failure, caching, and security boundaries. The workflow never
modifies its input database and every process uses deep content hashing, so an
interrupted run can be restarted with `-resume`. Inputs are staged as independent
regular-file copies rather than symlinks, preserving the validators' path-safety
boundary and preventing a task from writing through to the source snapshot.

## Pinned runtime

The manifest accepts Nextflow `26.04.4` or later. CI installs the official
`26.04.6` distribution and checks its published SHA-256 before execution; CSC
uses its supported `nextflow/26.04.4.12445` module. Python package and model
dependencies must already be installed in the launching environment or supplied
through a digest-pinned container profile.

## Local or GitHub runner

```bash
nextflow run workflows/nextflow/main.nf \
  -profile local \
  --database /read-only/input/records.sqlite \
  --model_summary /read-only/input/model-summary.json \
  --expected_articles 80 \
  --git_commit 0123456789abcdef0123456789abcdef01234567 \
  --outdir /durable/results/mdmeta-scale80 \
  -work-dir /durable/work/mdmeta-scale80 \
  -with-report /durable/results/mdmeta-scale80/execution-report.html \
  -with-trace /durable/results/mdmeta-scale80/trace.tsv
```

Repeat the same command with `-resume`. Keep the work directory until the
release is accepted; deleting it removes the restart cache.

## CSC Roihu Slurm

Run Nextflow from an activated, locked project environment on the login node.
The workflow submits four bounded CPU jobs to `small`; it does not request a
GPU. Always give the account explicitly:

```bash
nextflow run workflows/nextflow/main.nf \
  -profile csc \
  --slurm_account project_2012997 \
  --slurm_queue small \
  --database /scratch/project_2012997/xiaomei/input/records.sqlite \
  --model_summary /scratch/project_2012997/xiaomei/input/model-summary.json \
  --expected_articles 80 \
  --git_commit 0123456789abcdef0123456789abcdef01234567 \
  --outdir /scratch/project_2012997/xiaomei/results/mdmeta-scale80 \
  -work-dir /scratch/project_2012997/xiaomei/work/mdmeta-scale80 \
  -resume
```

The account must match `project_[0-9]+`. Queue names are constrained to safe
identifier characters; `small` is the intended profile for this workflow.

## Digest-pinned containers

Append `docker` or `apptainer` to the profile and supply an immutable image:

```bash
-profile local,docker \
--container_image ghcr.io/OWNER/IMAGE@sha256:64_HEX_DIGEST
```

Tag-only container references are rejected. Container registry credentials are
operator-managed and must not be stored in the repository or Nextflow reports.

## Release boundary

`WORKFLOW_COMPLETE` means that deterministic technical checks passed. It does
not mean that human review is finished. The review queue is the release gate:
auto-accepted items remain subject to the policy's deterministic audit sample;
uncertain items require one reviewer; critical/escalated or benchmark-reference
items require blinded independent double review and adjudication.
