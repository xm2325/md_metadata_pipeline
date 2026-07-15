#!/bin/bash -l
#SBATCH --job-name=mdmeta-stage-inputs
#SBATCH --partition=small
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=01:00:00

umask 077

RUN_DIR_INPUT=${1:?run directory required}
SOURCE_ARCHIVE_INPUT=${2:?source archive required}
SOURCE_COMMIT=${3:?source commit required}
SOURCE_ARCHIVE_SHA256=${4:?source archive SHA-256 required}
MODEL_ROOT_INPUT=${5:?model root required}
SOURCE_MANIFEST_RELATIVE=${6:?source manifest relative path required}
ARTICLE_LIMIT=${7:?article limit required}
MODEL_REPO_ID=${8:?model repository identifier required}
MODEL_REVISION=${9:?model revision required}
MODEL_LICENSE=${10:?model licence required}
MODEL_MODE=${11:-create}

if [[ -L "$RUN_DIR_INPUT" || -L "$SOURCE_ARCHIVE_INPUT" || -L "$MODEL_ROOT_INPUT" ]]; then
    printf 'path arguments must not be symbolic links\n' >&2
    exit 64
fi
RUN_DIR=$(realpath -m -- "$RUN_DIR_INPUT")
SOURCE_ARCHIVE=$(realpath -e -- "$SOURCE_ARCHIVE_INPUT")
MODEL_ROOT=$(realpath -m -- "$MODEL_ROOT_INPUT")
if [[ "$RUN_DIR" != /scratch/project_*/* ]]; then
    printf 'run directory must be inside /scratch/project_*\n' >&2
    exit 64
fi
if [[ "$MODEL_ROOT" != /scratch/project_*/* ]]; then
    printf 'model root must be inside /scratch/project_*\n' >&2
    exit 64
fi
if [[ "$SOURCE_ARCHIVE" != /projappl/project_*/* || ! -f "$SOURCE_ARCHIVE" ]]; then
    printf 'source archive must be inside /projappl/project_*\n' >&2
    exit 64
fi
if [[ "$SOURCE_MANIFEST_RELATIVE" = /* || "$SOURCE_MANIFEST_RELATIVE" == *".."* ]]; then
    printf 'source manifest must be a safe archive-relative path\n' >&2
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
if [[ ! "$ARTICLE_LIMIT" =~ ^[1-9][0-9]*$ ]]; then
    printf 'article limit must be a positive integer\n' >&2
    exit 64
fi
if [[ "$MODEL_MODE" != create && "$MODEL_MODE" != verify-existing ]]; then
    printf 'model mode must be create or verify-existing\n' >&2
    exit 64
fi

RUN_PROJECT=${RUN_DIR#/scratch/}
RUN_PROJECT=${RUN_PROJECT%%/*}
MODEL_PROJECT=${MODEL_ROOT#/scratch/}
MODEL_PROJECT=${MODEL_PROJECT%%/*}
ARCHIVE_PROJECT=${SOURCE_ARCHIVE#/projappl/}
ARCHIVE_PROJECT=${ARCHIVE_PROJECT%%/*}
if [[ ! "$RUN_PROJECT" =~ ^project_[0-9]+$ || ! "$USER" =~ ^[A-Za-z0-9._-]+$ ]]; then
    printf 'project or user identity has an unsafe form\n' >&2
    exit 64
fi
if [[ "$RUN_PROJECT" != "$MODEL_PROJECT" || "$RUN_PROJECT" != "$ARCHIVE_PROJECT" ]]; then
    printf 'run, model and source archive paths must belong to the same project\n' >&2
    exit 64
fi
if [[ "$RUN_DIR" != "/scratch/$RUN_PROJECT/$USER/"* \
    || "$MODEL_ROOT" != "/scratch/$RUN_PROJECT/$USER/"* \
    || "$SOURCE_ARCHIVE" != "/projappl/$RUN_PROJECT/$USER/"* ]]; then
    printf 'all paths must be below the submitting user private project paths\n' >&2
    exit 64
fi
if [[ "${SLURM_JOB_ACCOUNT:-}" != "$RUN_PROJECT" ]]; then
    printf 'Slurm account does not match the storage project\n' >&2
    exit 64
fi
if [[ "${SLURM_JOB_PARTITION:-}" != small ]]; then
    printf 'input staging must run in the small CPU partition\n' >&2
    exit 64
fi

mkdir -p "$RUN_DIR/home" "$RUN_DIR/logs" "$RUN_DIR/python" "$MODEL_ROOT"
chmod 700 "$RUN_DIR" "$RUN_DIR/home" "$RUN_DIR/logs" "$RUN_DIR/python" "$MODEL_ROOT"
export HOME="$RUN_DIR/home"
export XDG_CACHE_HOME="$RUN_DIR/cache"
export XDG_DATA_HOME="$RUN_DIR/data"
export PIP_CACHE_DIR="$RUN_DIR/pip-cache"

if ! module load python-data; then
    printf 'failed to load python-data\n' >&2
    exit 69
fi
if [[ "$(uname -m)" != x86_64 ]]; then
    printf 'input staging requires an x86_64 Roihu CPU node\n' >&2
    exit 69
fi
export SLURM_EXPORT_ENV=ALL
set -Eeuo pipefail

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
SOURCE_MANIFEST="$SOURCE_DIR/$SOURCE_MANIFEST_RELATIVE"
if [[ ! -f "$SOURCE_MANIFEST" ]]; then
    printf 'source manifest is missing from the verified source archive\n' >&2
    exit 66
fi

PYTHON_LAYER="$RUN_DIR/python"
export PYTHONPATH="$SOURCE_DIR/src:$PYTHON_LAYER"
if [[ "$MODEL_MODE" == create ]] \
    && ! python3 -c 'import huggingface_hub; assert huggingface_hub.__version__ == "1.14.0"' 2>/dev/null; then
    python3 -m pip install \
        --disable-pip-version-check \
        --no-cache-dir \
        --target "$PYTHON_LAYER" \
        --requirement "$SOURCE_DIR/constraints/hpc-stage.txt"
fi

ENVIRONMENT_TEMP="$RUN_DIR/.environment.txt.tmp"
{
    date --utc --iso-8601=seconds
    hostname
    uname -a
    printf 'source_commit=%s\n' "$SOURCE_COMMIT"
    printf 'source_archive_sha256=%s\n' "$SOURCE_ARCHIVE_SHA256"
    printf 'model_mode=%s\n' "$MODEL_MODE"
    module list 2>&1
    module show python-data 2>&1
    python3 -c 'import httpx,pydantic; print("httpx=" + httpx.__version__); print("pydantic=" + pydantic.__version__)'
    if [[ "$MODEL_MODE" == create ]]; then
        python3 -c 'import huggingface_hub; print("huggingface_hub=" + huggingface_hub.__version__)'
    else
        printf 'huggingface_hub=not_required_for_offline_verification\n'
    fi
} > "$ENVIRONMENT_TEMP"
mv "$ENVIRONMENT_TEMP" "$RUN_DIR/environment.txt"

MODEL_MANIFEST="$MODEL_ROOT/model-manifest.json"
MODEL_MODE_ARGUMENTS=()
if [[ "$MODEL_MODE" == verify-existing ]]; then
    MODEL_MODE_ARGUMENTS+=(--verify-existing)
fi
srun --kill-on-bad-exit=1 --ntasks=1 \
    python3 "$SOURCE_DIR/hpc/roihu/stage_model.py" \
    --repo-id "$MODEL_REPO_ID" \
    --revision "$MODEL_REVISION" \
    --expected-license "$MODEL_LICENSE" \
    --snapshot-dir "$MODEL_ROOT/snapshot" \
    --manifest "$MODEL_MANIFEST" \
    "${MODEL_MODE_ARGUMENTS[@]}"

srun --kill-on-bad-exit=1 --ntasks=1 \
    python3 "$SOURCE_DIR/scripts/stage_frozen_jats.py" \
    --source-manifest "$SOURCE_MANIFEST" \
    --cache-dir "$RUN_DIR/jats" \
    --output "$RUN_DIR/jats-manifest.json" \
    --article-limit "$ARTICLE_LIMIT"

(
    cd "$RUN_DIR"
    sha256sum environment.txt jats-manifest.json > SHA256SUMS
    sha256sum --check SHA256SUMS
)
(
    cd "$MODEL_ROOT"
    sha256sum model-manifest.json > model-manifest.json.sha256
    sha256sum --check model-manifest.json.sha256
)
