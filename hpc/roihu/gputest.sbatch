#!/usr/bin/env bash
#SBATCH --job-name=mdmeta-gh200-smoke
#SBATCH --partition=gputest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --gres=gpu:gh200:1
#SBATCH --time=00:15:00

set -Eeuo pipefail
umask 077

RUN_DIR=${1:?run directory required}
SOURCE_DIR=${2:?source directory required}
SOURCE_ARCHIVE=${3:?source archive required}
SOURCE_COMMIT=${4:?source commit required}
SOURCE_ARCHIVE_SHA256=${5:?source archive SHA-256 required}

if [[ "$RUN_DIR" != /scratch/project_*/* ]]; then
    printf 'run directory must be inside /scratch/project_*\n' >&2
    exit 64
fi
if [[ "$SOURCE_DIR" != /projappl/project_*/* ]]; then
    printf 'source directory must be inside /projappl/project_*\n' >&2
    exit 64
fi
if [[ "$SOURCE_ARCHIVE" != /projappl/project_*/* ]]; then
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

mkdir -p "$RUN_DIR/logs"

export CSC_ENV_INIT_NON_INTERACTIVE=yes
# shellcheck source=/etc/profile
source /etc/profile
module load python-pytorch/2.10

ACTUAL_ARCHIVE_SHA256=$(sha256sum "$SOURCE_ARCHIVE" | awk '{print $1}')
if [[ "$ACTUAL_ARCHIVE_SHA256" != "$SOURCE_ARCHIVE_SHA256" ]]; then
    printf 'source archive digest mismatch\n' >&2
    exit 65
fi

ENVIRONMENT_TEMP="$RUN_DIR/.environment.txt.tmp"
{
    date --utc --iso-8601=seconds
    hostname
    uname -a
    printf 'source_commit=%s\n' "$SOURCE_COMMIT"
    printf 'source_archive_sha256=%s\n' "$SOURCE_ARCHIVE_SHA256"
    module list 2>&1
    module show python-pytorch/2.10 2>&1
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
    python3 "$SOURCE_DIR/hpc/roihu/gpu_smoke.py" \
    --output "$RUN_DIR/result.json" \
    --source-commit "$SOURCE_COMMIT" \
    --source-archive-sha256 "$SOURCE_ARCHIVE_SHA256"

cleanup_monitor
MONITOR_PID=''
(
    cd "$RUN_DIR"
    sha256sum result.json > result.json.sha256
    sha256sum --check result.json.sha256
)
