#!/bin/bash -l
#SBATCH --job-name=mdmeta-llm-extract
#SBATCH --partition=gputest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --gres=gpu:gh200:1
#SBATCH --time=00:15:00

umask 077

if ! module load python-vllm/0.19.1; then
    printf 'failed to load python-vllm/0.19.1\n' >&2
    exit 69
fi
export SLURM_EXPORT_ENV=ALL
set -Eeuo pipefail

RUN_DIR_INPUT=${1:?run directory required}
SOURCE_ARCHIVE_INPUT=${2:?source archive required}
SOURCE_COMMIT=${3:?source commit required}
SOURCE_ARCHIVE_SHA256=${4:?source archive SHA-256 required}
MODEL_ROOT_INPUT=${5:?model root required}
SOURCE_MANIFEST_SPEC=${6:?source manifest path required}
JATS_CACHE_DIR_INPUT=${7:?JATS cache directory required}
ARTICLE_LIMIT=${8:?article limit required}
SOURCE_MANIFEST_FILE_SHA256=${9:-}

if [[ -L "$RUN_DIR_INPUT" || -L "$SOURCE_ARCHIVE_INPUT" \
    || -L "$MODEL_ROOT_INPUT" || -L "$JATS_CACHE_DIR_INPUT" \
    || ( "$SOURCE_MANIFEST_SPEC" = /* && -L "$SOURCE_MANIFEST_SPEC" ) ]]; then
    printf 'path arguments must not be symbolic links\n' >&2
    exit 64
fi
RUN_DIR=$(realpath -m -- "$RUN_DIR_INPUT")
SOURCE_ARCHIVE=$(realpath -e -- "$SOURCE_ARCHIVE_INPUT")
MODEL_ROOT=$(realpath -e -- "$MODEL_ROOT_INPUT")
JATS_CACHE_DIR=$(realpath -e -- "$JATS_CACHE_DIR_INPUT")
EXTERNAL_SOURCE_MANIFEST=''
if [[ "$SOURCE_MANIFEST_SPEC" = /* ]]; then
    if ! EXTERNAL_SOURCE_MANIFEST=$(realpath -e -- "$SOURCE_MANIFEST_SPEC"); then
        printf 'external source manifest does not exist\n' >&2
        exit 66
    fi
elif [[ "$SOURCE_MANIFEST_SPEC" == *".."* ]]; then
    printf 'source manifest must be a safe archive-relative or absolute project path\n' >&2
    exit 64
fi
if [[ "$RUN_DIR" != /scratch/project_*/* ]]; then
    printf 'run directory must be inside /scratch/project_*\n' >&2
    exit 64
fi
if [[ "$MODEL_ROOT" != /scratch/project_*/* ]]; then
    printf 'model root must be inside /scratch/project_*\n' >&2
    exit 64
fi
if [[ "$JATS_CACHE_DIR" != /scratch/project_*/* ]]; then
    printf 'JATS cache must be inside /scratch/project_*\n' >&2
    exit 64
fi
if [[ "$SOURCE_ARCHIVE" != /projappl/project_*/* || ! -f "$SOURCE_ARCHIVE" ]]; then
    printf 'source archive must be inside /projappl/project_*\n' >&2
    exit 64
fi
if [[ ! "$SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]]; then
    printf 'source commit must be a full lowercase Git SHA-1\n' >&2
    exit 64
fi
if [[ ! "$SOURCE_ARCHIVE_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
    printf 'source archive digest must be a lowercase SHA-256\n' >&2
    exit 64
fi
if [[ -n "$EXTERNAL_SOURCE_MANIFEST" \
    && ! "$SOURCE_MANIFEST_FILE_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
    printf 'external source manifest requires its lowercase file SHA-256\n' >&2
    exit 64
fi
if [[ ! "$ARTICLE_LIMIT" =~ ^[1-9][0-9]*$ ]]; then
    printf 'article limit must be a positive integer\n' >&2
    exit 64
fi

RUN_PROJECT=${RUN_DIR#/scratch/}
RUN_PROJECT=${RUN_PROJECT%%/*}
MODEL_PROJECT=${MODEL_ROOT#/scratch/}
MODEL_PROJECT=${MODEL_PROJECT%%/*}
JATS_PROJECT=${JATS_CACHE_DIR#/scratch/}
JATS_PROJECT=${JATS_PROJECT%%/*}
ARCHIVE_PROJECT=${SOURCE_ARCHIVE#/projappl/}
ARCHIVE_PROJECT=${ARCHIVE_PROJECT%%/*}
MANIFEST_PROJECT=''
if [[ -n "$EXTERNAL_SOURCE_MANIFEST" ]]; then
    MANIFEST_PROJECT=${EXTERNAL_SOURCE_MANIFEST#/projappl/}
    MANIFEST_PROJECT=${MANIFEST_PROJECT%%/*}
fi
if [[ ! "$RUN_PROJECT" =~ ^project_[0-9]+$ || ! "$USER" =~ ^[A-Za-z0-9._-]+$ ]]; then
    printf 'project or user identity has an unsafe form\n' >&2
    exit 64
fi
if [[ "$RUN_PROJECT" != "$MODEL_PROJECT" || "$RUN_PROJECT" != "$JATS_PROJECT" \
    || "$RUN_PROJECT" != "$ARCHIVE_PROJECT" ]]; then
    printf 'run, model, JATS and source archive paths must belong to the same project\n' >&2
    exit 64
fi
if [[ -n "$EXTERNAL_SOURCE_MANIFEST" \
    && ( "$EXTERNAL_SOURCE_MANIFEST" != /projappl/project_*/* \
        || ! -f "$EXTERNAL_SOURCE_MANIFEST" \
        || "$MANIFEST_PROJECT" != "$RUN_PROJECT" ) ]]; then
    printf 'external source manifest must be a regular file in the matching project\n' >&2
    exit 64
fi
if [[ "$RUN_DIR" != "/scratch/$RUN_PROJECT/$USER/"* \
    || "$MODEL_ROOT" != "/scratch/$RUN_PROJECT/$USER/"* \
    || "$JATS_CACHE_DIR" != "/scratch/$RUN_PROJECT/$USER/"* \
    || "$SOURCE_ARCHIVE" != "/projappl/$RUN_PROJECT/$USER/"* \
    || ( -n "$EXTERNAL_SOURCE_MANIFEST" \
        && "$EXTERNAL_SOURCE_MANIFEST" != "/projappl/$RUN_PROJECT/$USER/"* ) ]]; then
    printf 'all paths must be below the submitting user private project paths\n' >&2
    exit 64
fi
if [[ "${SLURM_JOB_ACCOUNT:-}" != "$RUN_PROJECT" ]]; then
    printf 'Slurm account does not match the storage project\n' >&2
    exit 64
fi
if [[ "${SLURM_JOB_PARTITION:-}" != gputest \
    && "${SLURM_JOB_PARTITION:-}" != gpumedium ]]; then
    printf 'model inference must run in gputest or gpumedium\n' >&2
    exit 64
fi
if [[ "$(uname -m)" != aarch64 ]]; then
    printf 'model inference requires an aarch64 Roihu GPU node\n' >&2
    exit 69
fi

MODEL_SNAPSHOT_DIR="$MODEL_ROOT/snapshot"
MODEL_MANIFEST="$MODEL_ROOT/model-manifest.json"
if [[ ! -d "$MODEL_SNAPSHOT_DIR" || ! -f "$MODEL_MANIFEST" ]]; then
    printf 'verified model snapshot inputs are missing\n' >&2
    exit 66
fi

mkdir -p "$RUN_DIR/home" "$RUN_DIR/logs" "$RUN_DIR/hf-home"
chmod 700 "$RUN_DIR" "$RUN_DIR/home" "$RUN_DIR/logs" "$RUN_DIR/hf-home"
export HOME="$RUN_DIR/home"
export HF_HOME="$RUN_DIR/hf-home"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false

ACTUAL_ARCHIVE_SHA256=$(sha256sum "$SOURCE_ARCHIVE" | awk '{print $1}')
if [[ "$ACTUAL_ARCHIVE_SHA256" != "$SOURCE_ARCHIVE_SHA256" ]]; then
    printf 'source archive digest mismatch\n' >&2
    exit 65
fi

SOURCE_DIR="$RUN_DIR/source"
if [[ -e "$SOURCE_DIR" ]]; then
    printf 'run source snapshot already exists; use a new run directory\n' >&2
    exit 66
fi
if tar -tf "$SOURCE_ARCHIVE" | grep -E '(^/|(^|/)\.\.(/|$))' >/dev/null; then
    printf 'source archive contains an unsafe path\n' >&2
    exit 65
fi
mkdir "$SOURCE_DIR"
tar --extract --file "$SOURCE_ARCHIVE" --directory "$SOURCE_DIR" \
    --no-same-owner --no-same-permissions
if [[ -n "$(find "$SOURCE_DIR" -type l -print -quit)" ]]; then
    printf 'source archive contains a symbolic link\n' >&2
    exit 65
fi
if [[ ! -f "$SOURCE_DIR/.mdmeta-source-commit" ]]; then
    printf 'source archive does not contain its commit identity\n' >&2
    exit 65
fi
ARCHIVE_COMMIT=$(tr -d '\r\n' < "$SOURCE_DIR/.mdmeta-source-commit")
if [[ "$ARCHIVE_COMMIT" != "$SOURCE_COMMIT" ]]; then
    printf 'source archive commit identity mismatch\n' >&2
    exit 65
fi
chmod -R u=rwX,go= "$SOURCE_DIR"
if [[ -n "$EXTERNAL_SOURCE_MANIFEST" ]]; then
    SOURCE_MANIFEST="$EXTERNAL_SOURCE_MANIFEST"
else
    SOURCE_MANIFEST="$SOURCE_DIR/$SOURCE_MANIFEST_SPEC"
fi
if [[ ! -f "$SOURCE_MANIFEST" ]]; then
    printf 'source manifest is missing from the verified source archive\n' >&2
    exit 66
fi
ACTUAL_SOURCE_MANIFEST_FILE_SHA256=$(sha256sum "$SOURCE_MANIFEST" | awk '{print $1}')
if [[ -n "$SOURCE_MANIFEST_FILE_SHA256" \
    && "$ACTUAL_SOURCE_MANIFEST_FILE_SHA256" != "$SOURCE_MANIFEST_FILE_SHA256" ]]; then
    printf 'source manifest file digest mismatch\n' >&2
    exit 65
fi
export PYTHONPATH="$SOURCE_DIR/src"

ENVIRONMENT_TEMP="$RUN_DIR/.environment.txt.tmp"
{
    date --utc --iso-8601=seconds
    hostname
    uname -a
    printf 'source_commit=%s\n' "$SOURCE_COMMIT"
    printf 'source_archive_sha256=%s\n' "$SOURCE_ARCHIVE_SHA256"
    printf 'source_manifest_file_sha256=%s\n' "$ACTUAL_SOURCE_MANIFEST_FILE_SHA256"
    printf 'source_manifest_external=%s\n' "$([[ -n "$EXTERNAL_SOURCE_MANIFEST" ]] && printf true || printf false)"
    printf 'model_manifest_sha256=%s\n' "$(sha256sum "$MODEL_MANIFEST" | awk '{print $1}')"
    module list 2>&1
    module show python-vllm/0.19.1 2>&1
    python3 -c 'import httpx,pydantic,torch,transformers,vllm; print("vllm=" + vllm.__version__); print("torch=" + torch.__version__); print("transformers=" + transformers.__version__); print("pydantic=" + pydantic.__version__); print("httpx=" + httpx.__version__)'
    nvidia-smi -L
    nvidia-smi \
        --query-gpu=name,uuid,driver_version,memory.total \
        --format=csv,noheader
} > "$ENVIRONMENT_TEMP"
mv "$ENVIRONMENT_TEMP" "$RUN_DIR/environment.txt"

MONITOR_PID=''
cleanup_monitor() {
    if [[ -n "$MONITOR_PID" ]]; then
        kill "$MONITOR_PID" 2>/dev/null || true
        wait "$MONITOR_PID" 2>/dev/null || true
    fi
}
record_exit() {
    local exit_code=$?
    cleanup_monitor
    trap - EXIT
    printf '%s\n' "$exit_code" > "$RUN_DIR/.exit-code.tmp"
    mv "$RUN_DIR/.exit-code.tmp" "$RUN_DIR/exit-code.txt"
    exit "$exit_code"
}
trap record_exit EXIT

nvidia-smi \
    --query-gpu=timestamp,index,uuid,utilization.gpu,utilization.memory,memory.used,memory.total,power.draw,temperature.gpu \
    --format=csv \
    --loop=1 \
    > "$RUN_DIR/logs/gpu-samples.csv" 2>&1 &
MONITOR_PID=$!

srun --kill-on-bad-exit=1 --ntasks=1 \
    python3 "$SOURCE_DIR/scripts/run_llm_protocol_batch.py" \
    --source-manifest "$SOURCE_MANIFEST" \
    --jats-cache-dir "$JATS_CACHE_DIR" \
    --model-snapshot-dir "$MODEL_SNAPSHOT_DIR" \
    --model-manifest "$MODEL_MANIFEST" \
    --output "$RUN_DIR/result.json" \
    --summary-output "$RUN_DIR/summary.json" \
    --checkpoint-output "$RUN_DIR/checkpoint.json" \
    --source-commit "$SOURCE_COMMIT" \
    --source-archive-sha256 "$SOURCE_ARCHIVE_SHA256" \
    --article-limit "$ARTICLE_LIMIT" \
    --batch-size 32 \
    --max-tokens 4096 \
    --max-model-len 16384 \
    --gpu-memory-utilization 0.8 \
    --seed 3997 \
    --require-cached-jats \
    --minimum-event-count 1

cleanup_monitor
MONITOR_PID=''
srun --kill-on-bad-exit=1 --ntasks=1 \
    python3 "$SOURCE_DIR/hpc/roihu/summarize_gpu_samples.py" \
    --input "$RUN_DIR/logs/gpu-samples.csv" \
    --output "$RUN_DIR/gpu-summary.json"
(
    cd "$RUN_DIR"
    sha256sum environment.txt gpu-summary.json result.json summary.json > SHA256SUMS
    sha256sum --check SHA256SUMS
)
