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

The script requests one GH200 from the 15-minute `gputest` partition and four CPU cores. It must be
submitted from `roihu-gpu.csc.fi`; software built on the x86 Roihu-CPU side is not compatible with
the aarch64 GPU nodes.

## Storage and privacy

- Store immutable source archives and small shared software assets under
  `/projappl/<project>/$USER/md-metadata-pipeline`.
- Run jobs and write logs/results under `/scratch/<project>/$USER/md-metadata-pipeline`.
- Create the user directories with mode `0700` because the GitHub repository is private.
- Transfer only `git archive` output. Never transfer `.git`, `.env`, SSH keys, GitHub credentials,
  local virtual environments or untracked files.
- Roihu scratch is temporary evidence storage, not an archive. Copy accepted compact evidence to an
  approved durable location and retain large datasets in CSC storage intended for that purpose.

## Submission contract

Create and checksum a source archive from a clean committed revision. After copying and extracting
it into the private project directory, submit with explicit paths, and export only CSC's
non-interactive environment switch rather than the caller's login environment:

```bash
sbatch --parsable \
  --account="$PROJECT" \
  --export=CSC_ENV_INIT_NON_INTERACTIVE=yes \
  --output="$RUN_DIR/logs/slurm-%j.out" \
  --error="$RUN_DIR/logs/slurm-%j.err" \
  "$SOURCE_DIR/hpc/roihu/gputest.sbatch" \
  "$RUN_DIR" "$SOURCE_DIR" "$SOURCE_ARCHIVE" "$SOURCE_COMMIT" "$SOURCE_ARCHIVE_SHA256"
```

Use `squeue` for bounded polling while the job is pending or running. Query `sacct` once after the
job reaches a terminal state, then require all of the following:

- Slurm state `COMPLETED` and exit code `0:0`;
- `result.json` status `pass` and the expected commit/archive digest;
- aarch64, one visible GH200 and CUDA runtime metadata;
- passing FP32 correctness, BF16 GEMM and CUDA attention checks;
- at least one non-zero utilisation sample in `logs/gpu-samples.csv`; and
- a valid `result.json.sha256` checksum.

## Next scientific step

After the infrastructure gate, implement a concrete local-model `StructuredBackend` adapter. A
scientific run must additionally bind the model-weight and tokenizer digests, model licence,
prompt/schema hash, decoding parameters, dtype, corpus manifest, blinded predictions, human gold
annotations and evaluation outputs. GPU execution alone is not evidence of extraction quality.
