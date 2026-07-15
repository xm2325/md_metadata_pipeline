#!/usr/bin/env bash
set -euo pipefail
umask 027

ENV_PATH="${1:-/projappl/project_2012997/bl/envs/mdmeta_vllm}"
VLLM_SPEC="${VLLM_SPEC:-vllm>=0.19,<0.20}"

module purge
module use /appl/modulefiles/manual/aida/aarch64
module load python-pytorch/2.10
export CW_FORCE_CONDA_ACTIVATE=1

python -m venv --system-site-packages "${ENV_PATH}"
# shellcheck disable=SC1090
source "${ENV_PATH}/bin/activate"
python -m pip install --upgrade pip uv

# Qwen3.6's model card recommends vLLM 0.19 or newer. uv's torch-backend resolver avoids
# accidentally selecting a CPU-only PyTorch build. On Roihu/aarch64, installation may need a
# CSC-provided compatible wheel or container if the public wheel is unavailable; the script fails
# rather than silently falling back to CPU inference.
uv pip install "${VLLM_SPEC}" --torch-backend=auto
uv pip install "huggingface-hub>=0.34,<1" "httpx>=0.27,<1"

python - <<'PY'
import importlib.metadata
import torch

print("environment created")
print("torch", torch.__version__)
print("torch_cuda_build", torch.version.cuda)
print("vllm", importlib.metadata.version("vllm"))
print("huggingface_hub", importlib.metadata.version("huggingface-hub"))
PY

printf 'Activate with:\n  source %q/bin/activate\n' "${ENV_PATH}"
