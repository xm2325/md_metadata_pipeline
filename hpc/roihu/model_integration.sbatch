#!/bin/bash -l
#SBATCH --job-name=mdmeta-model-integrate
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
SOURCE_MANIFEST_RELATIVE=${5:?source manifest relative path required}
JATS_CACHE_DIR_INPUT=${6:?JATS cache directory required}
MODEL_RESULT_INPUT=${7:?model result required}

if [[ -L "$RUN_DIR_INPUT" || -L "$SOURCE_ARCHIVE_INPUT" \
    || -L "$JATS_CACHE_DIR_INPUT" || -L "$MODEL_RESULT_INPUT" ]]; then
    printf 'path arguments must not be symbolic links\n' >&2
    exit 64
fi
RUN_DIR=$(realpath -m -- "$RUN_DIR_INPUT")
SOURCE_ARCHIVE=$(realpath -e -- "$SOURCE_ARCHIVE_INPUT")
JATS_CACHE_DIR=$(realpath -e -- "$JATS_CACHE_DIR_INPUT")
MODEL_RESULT=$(realpath -e -- "$MODEL_RESULT_INPUT")
if [[ "$RUN_DIR" != /scratch/project_*/* ]]; then
    printf 'run directory must be inside /scratch/project_*\n' >&2
    exit 64
fi
if [[ "$JATS_CACHE_DIR" != /scratch/project_*/* ]]; then
    printf 'JATS cache must be inside /scratch/project_*\n' >&2
    exit 64
fi
if [[ "$MODEL_RESULT" != /scratch/project_*/* ]]; then
    printf 'model result must be inside /scratch/project_*\n' >&2
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

RUN_PROJECT=${RUN_DIR#/scratch/}
RUN_PROJECT=${RUN_PROJECT%%/*}
JATS_PROJECT=${JATS_CACHE_DIR#/scratch/}
JATS_PROJECT=${JATS_PROJECT%%/*}
RESULT_PROJECT=${MODEL_RESULT#/scratch/}
RESULT_PROJECT=${RESULT_PROJECT%%/*}
ARCHIVE_PROJECT=${SOURCE_ARCHIVE#/projappl/}
ARCHIVE_PROJECT=${ARCHIVE_PROJECT%%/*}
if [[ ! "$RUN_PROJECT" =~ ^project_[0-9]+$ || ! "$USER" =~ ^[A-Za-z0-9._-]+$ ]]; then
    printf 'project or user identity has an unsafe form\n' >&2
    exit 64
fi
if [[ "$RUN_PROJECT" != "$JATS_PROJECT" || "$RUN_PROJECT" != "$RESULT_PROJECT" \
    || "$RUN_PROJECT" != "$ARCHIVE_PROJECT" ]]; then
    printf 'run, JATS, model result and source archive paths must belong to the same project\n' >&2
    exit 64
fi
if [[ "$RUN_DIR" != "/scratch/$RUN_PROJECT/$USER/"* \
    || "$JATS_CACHE_DIR" != "/scratch/$RUN_PROJECT/$USER/"* \
    || "$MODEL_RESULT" != "/scratch/$RUN_PROJECT/$USER/"* \
    || "$SOURCE_ARCHIVE" != "/projappl/$RUN_PROJECT/$USER/"* ]]; then
    printf 'all paths must be below the submitting user private project paths\n' >&2
    exit 64
fi
if [[ "${SLURM_JOB_ACCOUNT:-}" != "$RUN_PROJECT" ]]; then
    printf 'Slurm account does not match the storage project\n' >&2
    exit 64
fi
if [[ "${SLURM_JOB_PARTITION:-}" != small ]]; then
    printf 'model integration must run in the small CPU partition\n' >&2
    exit 64
fi

mkdir -p "$RUN_DIR/home" "$RUN_DIR/logs" "$RUN_DIR/validation-cache" "$RUN_DIR/integrated"
chmod 700 "$RUN_DIR" "$RUN_DIR/home" "$RUN_DIR/logs" "$RUN_DIR/validation-cache" "$RUN_DIR/integrated"
export HOME="$RUN_DIR/home"
export XDG_CACHE_HOME="$RUN_DIR/cache"
export XDG_DATA_HOME="$RUN_DIR/data"

if ! module load python-data; then
    printf 'failed to load python-data\n' >&2
    exit 69
fi
if [[ "$(uname -m)" != x86_64 ]]; then
    printf 'model integration requires an x86_64 Roihu CPU node\n' >&2
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
export PYTHONPATH="$SOURCE_DIR/src"

ENVIRONMENT_TEMP="$RUN_DIR/.environment.txt.tmp"
{
    date --utc --iso-8601=seconds
    hostname
    uname -a
    printf 'source_commit=%s\n' "$SOURCE_COMMIT"
    printf 'source_archive_sha256=%s\n' "$SOURCE_ARCHIVE_SHA256"
    printf 'model_result_file_sha256=%s\n' "$(sha256sum "$MODEL_RESULT" | awk '{print $1}')"
    module list 2>&1
    module show python-data 2>&1
    python3 -c 'import defusedxml,httpx,pydantic; print("httpx=" + httpx.__version__); print("pydantic=" + pydantic.__version__)'
} > "$ENVIRONMENT_TEMP"
mv "$ENVIRONMENT_TEMP" "$RUN_DIR/environment.txt"

srun --kill-on-bad-exit=1 --ntasks=1 \
    python3 "$SOURCE_DIR/scripts/run_model_backed_integration.py" \
    --source-manifest "$SOURCE_MANIFEST" \
    --jats-cache-dir "$JATS_CACHE_DIR" \
    --model-result "$MODEL_RESULT" \
    --output-dir "$RUN_DIR/integrated" \
    --database "$RUN_DIR/integrated/records.sqlite" \
    --validation-cache-dir "$RUN_DIR/validation-cache" \
    --source-commit "$SOURCE_COMMIT" \
    --source-archive-sha256 "$SOURCE_ARCHIVE_SHA256" \
    --require-validated-pdb \
    --require-residue-mapping

(
    cd "$RUN_DIR"
    sha256sum environment.txt integrated/summary.json integrated/records.sqlite > SHA256SUMS
    sha256sum --check SHA256SUMS
)
