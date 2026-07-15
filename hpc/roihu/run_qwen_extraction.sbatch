#!/usr/bin/env bash
#SBATCH --job-name=mdmeta_qwen
#SBATCH --account=project_2012997
#SBATCH --partition=gpumedium
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --gres=gpu:1
#SBATCH --mem=128G
#SBATCH --time=08:00:00
#SBATCH --output=logs/%x-%j.out
#SBATCH --error=logs/%x-%j.err

set -euo pipefail
umask 027

# Required inputs. MODEL_REVISION must be an immutable Hugging Face commit SHA, not "main".
: "${MDMETA_ENV:?Set MDMETA_ENV to the prepared virtual environment}"
: "${INPUT_JSONL:?Set INPUT_JSONL to the frozen paragraph JSONL}"
: "${INPUT_MANIFEST:?Set INPUT_MANIFEST to its generated manifest JSON}"
: "${MODEL_REVISION:?Set MODEL_REVISION to the exact model commit SHA}"
if [[ ! "${MODEL_REVISION}" =~ ^[0-9a-fA-F]{40}$ ]]; then
  echo "MODEL_REVISION must be a 40-character immutable Git commit SHA" >&2
  exit 2
fi

MODEL_ID="${MODEL_ID:-Qwen/Qwen3.6-27B}"
TENSOR_PARALLEL_SIZE="${TENSOR_PARALLEL_SIZE:-1}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-16384}"
MAX_PARAGRAPHS_PER_REQUEST="${MAX_PARAGRAPHS_PER_REQUEST:-1}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.90}"
PORT="${PORT:-$((18000 + SLURM_JOB_ID % 1000))}"
RESULT_ROOT="${RESULT_ROOT:-${SCRATCH:-/scratch/project_2012997}/mdmeta_gpu_runs}"
RUN_ID="${RUN_ID:-${SLURM_JOB_ID}-${MODEL_ID//\//_}}"
RUN_DIR="${RESULT_ROOT}/${RUN_ID}"
SERVER_LOG="${RUN_DIR}/vllm-server.log"
OUTPUT_JSON="${RUN_DIR}/llm-events.json"
RUN_MANIFEST="${RUN_DIR}/run-manifest.json"
COMPARISON_JSON="${RUN_DIR}/comparison.json"
COMPARISON_MD="${RUN_DIR}/comparison.md"

mkdir -p logs "${RUN_DIR}"

module purge
module use /appl/modulefiles/manual/aida/aarch64
module load python-pytorch/2.10
export CW_FORCE_CONDA_ACTIVATE=1
# shellcheck disable=SC1090
source "${MDMETA_ENV}/bin/activate"

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "${REPO_ROOT}"
python -m pip install --no-deps -e .

python - <<'PY'
import importlib.metadata
import torch

print("python environment preflight")
print("torch", torch.__version__)
print("cuda_available", torch.cuda.is_available())
print("cuda_device_count", torch.cuda.device_count())
print("vllm", importlib.metadata.version("vllm"))
if not torch.cuda.is_available():
    raise SystemExit("CUDA is unavailable inside the allocated job")
PY

AVAILABLE_GPUS="$(python - <<'PY'
import torch
print(torch.cuda.device_count())
PY
)"
if (( TENSOR_PARALLEL_SIZE < 1 || TENSOR_PARALLEL_SIZE > AVAILABLE_GPUS )); then
  echo "TENSOR_PARALLEL_SIZE=${TENSOR_PARALLEL_SIZE} but ${AVAILABLE_GPUS} GPU(s) are visible" >&2
  exit 2
fi

python - "${INPUT_JSONL}" "${INPUT_MANIFEST}" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

input_path = Path(sys.argv[1])
manifest_path = Path(sys.argv[2])
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
observed = hashlib.sha256(input_path.read_bytes()).hexdigest()
expected = manifest.get("output_sha256")
if expected != observed:
    raise SystemExit(f"frozen input SHA-256 mismatch: expected {expected}, observed {observed}")
print(json.dumps({"input_sha256": observed, "paragraph_count": manifest.get("paragraph_count")}))
PY

export HF_HOME="${HF_HOME:-${SCRATCH:-/scratch/project_2012997}/huggingface}"
export HUGGINGFACE_HUB_CACHE="${HUGGINGFACE_HUB_CACHE:-${HF_HOME}/hub}"
export TOKENIZERS_PARALLELISM=false
mkdir -p "${HF_HOME}"

nvidia-smi --query-gpu=index,name,uuid,memory.total,driver_version \
  --format=csv,noheader > "${RUN_DIR}/gpu-inventory.csv"
python -m pip freeze --all | sort > "${RUN_DIR}/python-environment.txt"
git status --short > "${RUN_DIR}/git-status.txt"
git rev-parse HEAD > "${RUN_DIR}/git-commit.txt"

VLLM_EXTRA_ARGS_TEXT="${VLLM_EXTRA_ARGS:---language-model-only --enable-prefix-caching --reasoning-parser qwen3}"
read -r -a VLLM_EXTRA_ARGS_ARRAY <<< "${VLLM_EXTRA_ARGS_TEXT}"

vllm serve "${MODEL_ID}" \
  --revision "${MODEL_REVISION}" \
  --host 127.0.0.1 \
  --port "${PORT}" \
  --tensor-parallel-size "${TENSOR_PARALLEL_SIZE}" \
  --max-model-len "${MAX_MODEL_LEN}" \
  --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION}" \
  --dtype auto \
  "${VLLM_EXTRA_ARGS_ARRAY[@]}" \
  > "${SERVER_LOG}" 2>&1 &
SERVER_PID=$!

cleanup() {
  if kill -0 "${SERVER_PID}" 2>/dev/null; then
    kill "${SERVER_PID}" || true
    wait "${SERVER_PID}" || true
  fi
}
trap cleanup EXIT

ready=false
for _ in $(seq 1 180); do
  if curl --silent --fail "http://127.0.0.1:${PORT}/health" > "${RUN_DIR}/health.json"; then
    ready=true
    break
  fi
  if ! kill -0 "${SERVER_PID}" 2>/dev/null; then
    echo "vLLM exited before becoming ready" >&2
    tail -n 200 "${SERVER_LOG}" >&2 || true
    exit 3
  fi
  sleep 10
done
if [[ "${ready}" != true ]]; then
  echo "vLLM did not become ready" >&2
  tail -n 200 "${SERVER_LOG}" >&2 || true
  exit 4
fi
curl --silent --fail "http://127.0.0.1:${PORT}/v1/models" > "${RUN_DIR}/models.json"

export MDMETA_LLM_BASE_URL="http://127.0.0.1:${PORT}/v1"
export MDMETA_LLM_MODEL="${MODEL_ID}"
export MDMETA_LLM_TIMEOUT_SECONDS="${MDMETA_LLM_TIMEOUT_SECONDS:-900}"
export MDMETA_LLM_MAX_OUTPUT_TOKENS="${MDMETA_LLM_MAX_OUTPUT_TOKENS:-1200}"
export MDMETA_LLM_MAX_RETRIES="${MDMETA_LLM_MAX_RETRIES:-1}"
export MDMETA_LLM_RETRY_BACKOFF_SECONDS="${MDMETA_LLM_RETRY_BACKOFF_SECONDS:-2}"
export MDMETA_LLM_DISABLE_THINKING="${MDMETA_LLM_DISABLE_THINKING:-true}"
export MDMETA_LLM_SEED="${MDMETA_LLM_SEED:-3997}"

mdmeta-extract-llm \
  --input "${INPUT_JSONL}" \
  --output "${OUTPUT_JSON}" \
  --max-paragraphs-per-request "${MAX_PARAGRAPHS_PER_REQUEST}"

if [[ -n "${REFERENCE_EVENTS:-}" || -n "${DETERMINISTIC_EVENTS:-}" ]]; then
  : "${REFERENCE_EVENTS:?Set both REFERENCE_EVENTS and DETERMINISTIC_EVENTS, or neither}"
  : "${DETERMINISTIC_EVENTS:?Set both REFERENCE_EVENTS and DETERMINISTIC_EVENTS, or neither}"
  python scripts/compare_extraction_systems.py \
    --reference "${REFERENCE_EVENTS}" \
    --system "deterministic=${DETERMINISTIC_EVENTS}" \
    --system "llm=${OUTPUT_JSON}" \
    --hybrid hybrid deterministic llm \
    --baseline deterministic \
    --bootstrap-iterations "${BOOTSTRAP_ITERATIONS:-2000}" \
    --seed "${BOOTSTRAP_SEED:-3997}" \
    --output "${COMPARISON_JSON}" \
    --markdown "${COMPARISON_MD}"
fi

# Stop the service before hashing its log so the evidence digest cannot change after publication.
cleanup
trap - EXIT

export MODEL_ID MODEL_REVISION TENSOR_PARALLEL_SIZE MAX_MODEL_LEN
export MAX_PARAGRAPHS_PER_REQUEST GPU_MEMORY_UTILIZATION INPUT_JSONL INPUT_MANIFEST
export OUTPUT_JSON RUN_MANIFEST RUN_DIR SERVER_LOG VLLM_EXTRA_ARGS_TEXT
python - <<'PY'
import hashlib
import importlib.metadata
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def digest(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def optional_digest(path: Path) -> str | None:
    return digest(path) if path.is_file() else None

run_dir = Path(os.environ["RUN_DIR"])
output = Path(os.environ["OUTPUT_JSON"])
manifest = {
    "schema_version": "roihu-vllm-run-manifest-v1",
    "created_at": datetime.now(timezone.utc).isoformat(),
    "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "git_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()),
    "model_id": os.environ["MODEL_ID"],
    "model_revision": os.environ["MODEL_REVISION"],
    "vllm_version": importlib.metadata.version("vllm"),
    "input_jsonl": os.environ["INPUT_JSONL"],
    "input_sha256": digest(os.environ["INPUT_JSONL"]),
    "input_manifest": os.environ["INPUT_MANIFEST"],
    "input_manifest_sha256": digest(os.environ["INPUT_MANIFEST"]),
    "output_json": str(output),
    "output_sha256": digest(output),
    "comparison_sha256": optional_digest(run_dir / "comparison.json"),
    "server_log_sha256": digest(os.environ["SERVER_LOG"]),
    "slurm": {
        "job_id": os.environ.get("SLURM_JOB_ID"),
        "job_name": os.environ.get("SLURM_JOB_NAME"),
        "partition": os.environ.get("SLURM_JOB_PARTITION"),
        "node_list": os.environ.get("SLURM_JOB_NODELIST"),
        "cpus_per_task": os.environ.get("SLURM_CPUS_PER_TASK"),
    },
    "inference": {
        "tensor_parallel_size": int(os.environ["TENSOR_PARALLEL_SIZE"]),
        "max_model_len": int(os.environ["MAX_MODEL_LEN"]),
        "max_paragraphs_per_request": int(os.environ["MAX_PARAGRAPHS_PER_REQUEST"]),
        "gpu_memory_utilization": float(os.environ["GPU_MEMORY_UTILIZATION"]),
        "vllm_extra_args": os.environ["VLLM_EXTRA_ARGS_TEXT"],
        "disable_thinking": os.environ.get("MDMETA_LLM_DISABLE_THINKING"),
        "seed": int(os.environ.get("MDMETA_LLM_SEED", "3997")),
    },
    "gpu_inventory_file": str(run_dir / "gpu-inventory.csv"),
    "environment_file": str(run_dir / "python-environment.txt"),
}
Path(os.environ["RUN_MANIFEST"]).write_text(
    json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
PY

(
  cd "${RUN_DIR}"
  sha256sum ./* > SHA256SUMS
)

printf 'Completed Roihu run: %s\n' "${RUN_DIR}"
printf 'Events: %s\n' "${OUTPUT_JSON}"
printf 'Manifest: %s\n' "${RUN_MANIFEST}"
if [[ -f "${COMPARISON_MD}" ]]; then
  printf 'Comparison: %s\n' "${COMPARISON_MD}"
fi
