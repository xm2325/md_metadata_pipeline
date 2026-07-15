# CSC Roihu GPU execution

This repository keeps the production API runtime independent of PyTorch. GPU validation and future
local-model inference use CSC's maintained `python-pytorch/2.10` module on Roihu-GPU instead of
adding CUDA packages to the API dependency lock.

## Scope of the first gate

`hpc/roihu/gputest.sbatch` is a bounded infrastructure smoke test. It verifies that an immutable
source archive can run on one aarch64 GH200 allocation, that CUDA BF16 matrix multiplication and
scaled dot-product attention execute successfully, and that the run emits provenance, Slurm,
environment, GPU-utilisation and checksum evidence. Passing this gate does **not** demonstrate a
working literature-extraction model or acceptable scientific accuracy.

The first accepted execution is documented in
[the 2026-07-15 GH200 run report](../study/roihu_gpu_smoke/RUN_2026-07-15.md). Slurm job `184708`
completed in 17 seconds with exit code `0:0`; its source archive, result JSON and checksums are bound
in the report.

The script requests one GH200 from the 15-minute `gputest` partition and four CPU cores. It must be
submitted through the SSH alias `roihu_gpu` to `roihu-gpu.csc.fi`; software built on the x86
Roihu-CPU side is not compatible with the aarch64 GPU nodes. Submit CPU staging and integration
jobs through `roihu_cpu`, and submit GPU inference jobs through `roihu_gpu`. Results must be checked
between clusters rather than chained with a cross-cluster Slurm dependency.

## Storage and privacy

- Store immutable source archives and small shared software assets under
  `/projappl/<project>/$USER/md-metadata-pipeline`.
- Run jobs and write logs/results under `/scratch/<project>/$USER/md-metadata-pipeline`.
- Create the user directories with mode `0700` because the GitHub repository is private.
- Transfer only a validated `git archive` whose root includes `.mdmeta-source-commit` containing
  the exact full source commit. Never transfer `.git`, `.env`, SSH keys, GitHub credentials, local
  virtual environments or untracked files.
- Roihu scratch is temporary evidence storage, not an archive. Copy accepted compact evidence to an
  approved durable location and retain large datasets in CSC storage intended for that purpose.

## Submission contract

Create and checksum a source archive from a clean committed revision. Add a virtual root member
whose value binds the archive to that revision:

```bash
SOURCE_COMMIT="$(git rev-parse HEAD)"
git archive --format=tar \
  --add-virtual-file=".mdmeta-source-commit:$SOURCE_COMMIT" \
  --output="$SOURCE_ARCHIVE" \
  "$SOURCE_COMMIT"
```

Before submission, require a clean worktree, validate the archive member inventory, extract and
compare `.mdmeta-source-commit` with `SOURCE_COMMIT`, and verify the archive SHA-256 before and
after transfer. A missing/malformed marker, a marker mismatch, an unexpected archive member or a
digest mismatch is a hard stop. Every new CPU or GPU job in this workflow may run only after that
preflight; the model staging, extraction and integration scripts repeat the marker check after
extraction.

Submit CPU batch scripts through `roihu_cpu` and GPU batch scripts through `roihu_gpu`. After
copying and extracting the verified archive into the private project directory, submit with
explicit paths, and export only CSC's non-interactive environment switch rather than the caller's
login environment. For the GPU smoke/inference path:

```bash
sbatch --parsable \
  --account="$PROJECT" \
  --export=CSC_ENV_INIT_NON_INTERACTIVE=yes \
  --output="$RUN_DIR/logs/slurm-%j.out" \
  --error="$RUN_DIR/logs/slurm-%j.err" \
  "$SOURCE_DIR/hpc/roihu/gputest.sbatch" \
  "$RUN_DIR" "$SOURCE_DIR" "$SOURCE_ARCHIVE" "$SOURCE_COMMIT" "$SOURCE_ARCHIVE_SHA256"
```

The batch script sets `SLURM_EXPORT_ENV=ALL` only after the clean login shell loads CSC's PyTorch
module. This is required for `srun` to see the module wrapper `PATH`, container image and NVIDIA
settings; it does not reintroduce the submitting shell's omitted environment.

Use `squeue` for bounded polling while the job is pending or running. Query `sacct` once after the
job reaches a terminal state, then require all of the following:

- Slurm state `COMPLETED` and exit code `0:0`;
- `result.json` status `pass` and the expected commit/archive digest;
- aarch64, one visible GH200 and CUDA runtime metadata;
- passing FP32 correctness, BF16 GEMM and CUDA attention checks;
- at least one non-zero utilisation sample in `logs/gpu-samples.csv`; and
- a valid `result.json.sha256` checksum.

## Next scientific step

The staged local-model experiment, promotion gates and evidence boundaries are defined in
[the Roihu model-backed literature protocol](ROIHU_LLM_EXPERIMENT.md). A scientific run must bind
the model-weight and tokenizer digests, model licence, prompt/schema hash, decoding parameters,
dtype, corpus manifest, blinded predictions, human gold annotations and evaluation outputs. GPU
execution alone is not evidence of extraction quality.
