# Roihu GPU benchmark

## Goal

Run the repository's real evidence-checked LLM path on GPU and produce an auditable comparison of:

1. deterministic extraction;
2. LLM-only accepted events;
3. validated hybrid union.

A successful job produces model output, operational metadata, scientific metrics and SHA-256
commitments. It does not create human reference labels.

## 1. Prepare the environment once

From the repository root:

```bash
bash hpc/roihu/bootstrap_vllm_env.sh \
  /projappl/project_2012997/bl/envs/mdmeta_vllm
```

The bootstrap uses the Roihu AIDA aarch64 PyTorch module observed in this project and installs a
vLLM 0.19 series environment. If no compatible aarch64 wheel is available, it fails explicitly;
use a CSC-supported vLLM container or wheel rather than silently switching to CPU inference.

## 2. Freeze paragraph input

Create a local manifest such as:

```json
{
  "articles": [
    {"document_id": "WOO2020", "xml_path": "../../examples/woo_2020/article_fixture.xml"}
  ]
}
```

Then run:

```bash
source /projappl/project_2012997/bl/envs/mdmeta_vllm/bin/activate
python -m pip install --no-deps -e .

python scripts/prepare_llm_paragraphs.py \
  --input-manifest results/frozen/articles.json \
  --output results/frozen/paragraphs.jsonl \
  --manifest-output results/frozen/paragraphs-manifest.json
```

The generated manifest records every source XML hash, the selection method, paragraph counts and the
JSONL hash. The Slurm job refuses to continue if the JSONL no longer matches that manifest.

## 3. Resolve an immutable model revision

```bash
MODEL_ID=Qwen/Qwen3.6-27B
MODEL_REVISION=$(python - <<'PY'
from huggingface_hub import HfApi
import os

print(HfApi().model_info(os.environ["MODEL_ID"]).sha)
PY
)
export MODEL_ID MODEL_REVISION
printf '%s %s\n' "$MODEL_ID" "$MODEL_REVISION"
```

Do not replace `MODEL_REVISION` with `main`. A named model without a frozen revision is not a
reproducible scientific run.

## 4. Submit a bounded smoke run first

Use a small model to verify the environment, endpoint, schema and output paths before spending a
large GPU allocation:

```bash
export MODEL_ID=Qwen/Qwen3.5-0.8B
export MODEL_REVISION=$(python - <<'PY'
from huggingface_hub import HfApi
print(HfApi().model_info("Qwen/Qwen3.5-0.8B").sha)
PY
)

sbatch \
  --gres=gpu:1 \
  --export=ALL,MDMETA_ENV=/projappl/project_2012997/bl/envs/mdmeta_vllm,INPUT_JSONL=$PWD/results/frozen/paragraphs.jsonl,INPUT_MANIFEST=$PWD/results/frozen/paragraphs-manifest.json,MODEL_ID=$MODEL_ID,MODEL_REVISION=$MODEL_REVISION,TENSOR_PARALLEL_SIZE=1,MAX_MODEL_LEN=8192 \
  hpc/roihu/run_qwen_extraction.sbatch
```

## 5. Submit the full Qwen3.6-27B run

The model card describes Qwen3.6-27B as a dense BF16 model and illustrates tensor parallel serving.
The exact GPU count required on Roihu depends on GPU memory, context length and vLLM overhead. Start
with a short context and request enough aggregate GPU memory; do not assume one GPU will fit.

Example with four visible GPUs:

```bash
export MODEL_ID=Qwen/Qwen3.6-27B
export MODEL_REVISION=$(python - <<'PY'
from huggingface_hub import HfApi
print(HfApi().model_info("Qwen/Qwen3.6-27B").sha)
PY
)

sbatch \
  --gres=gpu:4 \
  --cpus-per-task=32 \
  --mem=256G \
  --time=12:00:00 \
  --export=ALL,MDMETA_ENV=/projappl/project_2012997/bl/envs/mdmeta_vllm,INPUT_JSONL=$PWD/results/frozen/paragraphs.jsonl,INPUT_MANIFEST=$PWD/results/frozen/paragraphs-manifest.json,MODEL_ID=$MODEL_ID,MODEL_REVISION=$MODEL_REVISION,TENSOR_PARALLEL_SIZE=4,MAX_MODEL_LEN=16384,RESULT_ROOT=/scratch/project_2012997/mdmeta_gpu_runs \
  hpc/roihu/run_qwen_extraction.sbatch
```

If the server fails during model loading, inspect `vllm-server.log`. Increase tensor parallelism or
reduce `MAX_MODEL_LEN`; never reduce scientific input silently. If the installed vLLM version does
not recognise a model-specific option, set `VLLM_EXTRA_ARGS` explicitly and record it in the run
notes.

## 6. Include scientific comparison

When independently adjudicated reference events and deterministic predictions are available, add:

```bash
export REFERENCE_EVENTS=$PWD/results/reference/events.json
export DETERMINISTIC_EVENTS=$PWD/results/deterministic/events.json
export BOOTSTRAP_ITERATIONS=2000
export BOOTSTRAP_SEED=3997
```

The same Slurm job will then write `comparison.json` and `comparison.md` for deterministic, LLM and
validated hybrid systems.

## Outputs

Each run directory contains:

- `llm-events.json`: accepted ProtocolEvents only; invalid evidence candidates are rejected;
- `run-manifest.json`: model revision, Git commit, input/output hashes, Slurm and inference settings;
- `gpu-inventory.csv`: GPU names, UUIDs, memory and driver;
- `python-environment.txt`: exact installed packages;
- `models.json` and `health.json`: endpoint evidence;
- `vllm-server.log`: server diagnostics;
- `comparison.json` / `comparison.md`: optional scientific and operational comparison;
- `SHA256SUMS`: digest inventory for the compact run evidence.

Large model weights and source JATS XML are not copied into the result bundle.

## Acceptance gates

A run is technically successful when:

- the frozen input hash matches;
- the exact model revision loads;
- the endpoint becomes healthy;
- extraction completes without hidden document failures;
- every accepted event passes exact-span and deterministic unit validation;
- the run manifest and digest inventory are complete.

A model is scientifically useful only after comparison against independent human dual annotation and
adjudication. A hybrid improvement should be reported with its paired article-bootstrap interval,
not merely a higher point estimate.
