# Nextflow proof of concept

This workflow demonstrates a small scientific-workflow layer without moving domain logic out of the
installable Python package.

- Slurm allocates the GPU job.
- vLLM or SGLang serves the frozen model behind an OpenAI-compatible endpoint.
- `mdmeta-extract-llm` performs schema-constrained extraction and exact-evidence validation.
- Nextflow records the dependency between extraction and optional system comparison.
- `compare_extraction_systems.py` computes strict, phase-aware and paired-bootstrap results.

The workflow does **not** start a public service, download an unspecified model revision or convert a
machine output into a reference annotation.

## Run inside an existing Roihu allocation

Start the model server and export the same variables used by the Python CLI:

```bash
export MDMETA_LLM_BASE_URL=http://127.0.0.1:8000/v1
export MDMETA_LLM_MODEL=Qwen/Qwen3.6-27B
export MDMETA_LLM_DISABLE_THINKING=true

nextflow run workflow/nextflow/main.nf \
  -profile standard \
  --paragraphs results/frozen/paragraphs.jsonl \
  --reference results/reference/events.json \
  --deterministic results/deterministic/events.json \
  --outdir results/nextflow
```

When no independent human reference exists, omit `--reference` and `--deterministic`; the workflow
will produce the audited LLM run only. Do not report F1 against AI-consensus data as confirmatory
performance.

## Why local execution is the default

The vLLM endpoint is normally started inside one GPU allocation. Running the lightweight client
processes locally inside that allocation avoids scheduling a second GPU job. The `slurm_client`
profile is available when the endpoint is reachable from separately scheduled CPU jobs, but network
policy and endpoint exposure must be checked with the HPC operator first.
