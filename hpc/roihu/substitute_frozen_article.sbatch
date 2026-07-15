#!/bin/bash -l
#SBATCH --job-name=mdmeta-source-substitute
#SBATCH --partition=small
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:20:00

umask 077

RUN_DIR_INPUT=${1:?run directory required}
SOURCE_ARCHIVE_INPUT=${2:?source archive required}
SOURCE_COMMIT=${3:?source commit required}
SOURCE_ARCHIVE_SHA256=${4:?source archive SHA-256 required}
PARENT_MANIFEST_RELATIVE=${5:?parent manifest archive-relative path required}
PARENT_MANIFEST_FILE_SHA256=${6:?parent manifest file SHA-256 required}
PLAN_INPUT=${7:?provisional plan artifact required}
PLAN_FILE_SHA256=${8:?provisional plan file SHA-256 required}
SCREEN_INPUT=${9:?full-text screen artifact required}
SCREEN_FILE_SHA256=${10:?full-text screen file SHA-256 required}
OLD_JATS_INPUT=${11:?currently available drifted JATS required}
REPLACEMENT_JATS_INPUT=${12:?replacement JATS required}
OLD_DOCUMENT_ID=${13:?replaced document identifier required}
REPLACEMENT_DOCUMENT_ID=${14:?replacement document identifier required}
FAILED_STAGE_JOB_ID=${15:?failed staging job identifier required}
EXPECTED_OLD_JATS_SHA256=${16:?observed drifted JATS SHA-256 required}
EXPECTED_OLD_JATS_SIZE_BYTES=${17:?observed drifted JATS size required}

for candidate in \
    "$RUN_DIR_INPUT" "$SOURCE_ARCHIVE_INPUT" "$PLAN_INPUT" "$SCREEN_INPUT" \
    "$OLD_JATS_INPUT" "$REPLACEMENT_JATS_INPUT"; do
    if [[ -L "$candidate" ]]; then
        printf 'path arguments must not be symbolic links\n' >&2
        exit 64
    fi
done

RUN_DIR=$(realpath -m -- "$RUN_DIR_INPUT")
SOURCE_ARCHIVE=$(realpath -e -- "$SOURCE_ARCHIVE_INPUT")
PLAN=$(realpath -e -- "$PLAN_INPUT")
SCREEN=$(realpath -e -- "$SCREEN_INPUT")
OLD_JATS=$(realpath -e -- "$OLD_JATS_INPUT")
REPLACEMENT_JATS=$(realpath -e -- "$REPLACEMENT_JATS_INPUT")

if [[ "$RUN_DIR" != /scratch/project_*/* ]]; then
    printf 'run directory must be inside /scratch/project_*\n' >&2
    exit 64
fi
if [[ "$SOURCE_ARCHIVE" != /projappl/project_*/* || ! -f "$SOURCE_ARCHIVE" ]]; then
    printf 'source archive must be a regular file inside /projappl/project_*\n' >&2
    exit 64
fi
if [[ "$PLAN" != /projappl/project_*/* || ! -f "$PLAN" \
    || "$SCREEN" != /projappl/project_*/* || ! -f "$SCREEN" ]]; then
    printf 'artifact metadata inputs must be regular files inside /projappl/project_*\n' >&2
    exit 64
fi
if [[ "$OLD_JATS" != /scratch/project_*/* || ! -f "$OLD_JATS" \
    || "$REPLACEMENT_JATS" != /scratch/project_*/* || ! -f "$REPLACEMENT_JATS" ]]; then
    printf 'private JATS inputs must be regular files inside /scratch/project_*\n' >&2
    exit 64
fi
if [[ "$PARENT_MANIFEST_RELATIVE" = /* \
    || "$PARENT_MANIFEST_RELATIVE" == *".."* ]]; then
    printf 'parent manifest must be a safe archive-relative path\n' >&2
    exit 64
fi
if [[ ! "$SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]]; then
    printf 'source commit must be a full lowercase Git SHA-1\n' >&2
    exit 64
fi
for digest in \
    "$SOURCE_ARCHIVE_SHA256" "$PARENT_MANIFEST_FILE_SHA256" \
    "$PLAN_FILE_SHA256" "$SCREEN_FILE_SHA256" "$EXPECTED_OLD_JATS_SHA256"; do
    if [[ ! "$digest" =~ ^[0-9a-f]{64}$ ]]; then
        printf 'all requested digests must be lowercase SHA-256 values\n' >&2
        exit 64
    fi
done
if [[ ! "$OLD_DOCUMENT_ID" =~ ^PMC[0-9]+$ \
    || ! "$REPLACEMENT_DOCUMENT_ID" =~ ^PMC[0-9]+$ ]]; then
    printf 'document identifiers must be uppercase PMC identifiers\n' >&2
    exit 64
fi
if [[ ! "$FAILED_STAGE_JOB_ID" =~ ^[1-9][0-9]*$ \
    || ! "$EXPECTED_OLD_JATS_SIZE_BYTES" =~ ^[1-9][0-9]*$ ]]; then
    printf 'failed job identifier and observed JATS size must be positive integers\n' >&2
    exit 64
fi

RUN_PROJECT=${RUN_DIR#/scratch/}
RUN_PROJECT=${RUN_PROJECT%%/*}
ARCHIVE_PROJECT=${SOURCE_ARCHIVE#/projappl/}
ARCHIVE_PROJECT=${ARCHIVE_PROJECT%%/*}
PLAN_PROJECT=${PLAN#/projappl/}
PLAN_PROJECT=${PLAN_PROJECT%%/*}
SCREEN_PROJECT=${SCREEN#/projappl/}
SCREEN_PROJECT=${SCREEN_PROJECT%%/*}
OLD_JATS_PROJECT=${OLD_JATS#/scratch/}
OLD_JATS_PROJECT=${OLD_JATS_PROJECT%%/*}
REPLACEMENT_JATS_PROJECT=${REPLACEMENT_JATS#/scratch/}
REPLACEMENT_JATS_PROJECT=${REPLACEMENT_JATS_PROJECT%%/*}
if [[ ! "$RUN_PROJECT" =~ ^project_[0-9]+$ || ! "$USER" =~ ^[A-Za-z0-9._-]+$ ]]; then
    printf 'project or user identity has an unsafe form\n' >&2
    exit 64
fi
if [[ "$RUN_PROJECT" != "$ARCHIVE_PROJECT" || "$RUN_PROJECT" != "$PLAN_PROJECT" \
    || "$RUN_PROJECT" != "$SCREEN_PROJECT" || "$RUN_PROJECT" != "$OLD_JATS_PROJECT" \
    || "$RUN_PROJECT" != "$REPLACEMENT_JATS_PROJECT" ]]; then
    printf 'all source substitution paths must belong to the same project\n' >&2
    exit 64
fi
if [[ "$RUN_DIR" != "/scratch/$RUN_PROJECT/$USER/"* \
    || "$SOURCE_ARCHIVE" != "/projappl/$RUN_PROJECT/$USER/"* \
    || "$PLAN" != "/projappl/$RUN_PROJECT/$USER/"* \
    || "$SCREEN" != "/projappl/$RUN_PROJECT/$USER/"* \
    || "$OLD_JATS" != "/scratch/$RUN_PROJECT/$USER/"* \
    || "$REPLACEMENT_JATS" != "/scratch/$RUN_PROJECT/$USER/"* ]]; then
    printf 'all paths must be below the submitting user private project paths\n' >&2
    exit 64
fi
if [[ "${SLURM_JOB_ACCOUNT:-}" != "$RUN_PROJECT" \
    || "${SLURM_JOB_PARTITION:-}" != small ]]; then
    printf 'source substitution must use the matching account and small CPU partition\n' >&2
    exit 64
fi

if [[ -e "$RUN_DIR/source" || -e "$RUN_DIR/output" ]]; then
    printf 'run artifacts already exist; use a new run directory\n' >&2
    exit 66
fi
mkdir -p "$RUN_DIR/home" "$RUN_DIR/logs" "$RUN_DIR/jats" "$RUN_DIR/output"
chmod 700 "$RUN_DIR" "$RUN_DIR/home" "$RUN_DIR/logs" "$RUN_DIR/jats" "$RUN_DIR/output"

if ! module load python-data; then
    printf 'failed to load python-data\n' >&2
    exit 69
fi
if [[ "$(uname -m)" != x86_64 ]]; then
    printf 'source substitution requires an x86_64 Roihu CPU node\n' >&2
    exit 69
fi
export SLURM_EXPORT_ENV=ALL
set -Eeuo pipefail

export HOME="$RUN_DIR/home"
export XDG_CACHE_HOME="$RUN_DIR/cache"
export XDG_DATA_HOME="$RUN_DIR/data"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1

record_exit() {
    local exit_code=$?
    trap - EXIT
    printf '%s\n' "$exit_code" > "$RUN_DIR/.exit-code.tmp"
    mv "$RUN_DIR/.exit-code.tmp" "$RUN_DIR/exit-code.txt"
    exit "$exit_code"
}
trap record_exit EXIT

ACTUAL_ARCHIVE_SHA256=$(sha256sum "$SOURCE_ARCHIVE" | awk '{print $1}')
if [[ "$ACTUAL_ARCHIVE_SHA256" != "$SOURCE_ARCHIVE_SHA256" ]]; then
    printf 'source archive digest mismatch\n' >&2
    exit 65
fi
SOURCE_DIR="$RUN_DIR/source"
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
    printf 'source archive has no commit identity\n' >&2
    exit 65
fi
ARCHIVE_COMMIT=$(tr -d '\r\n' < "$SOURCE_DIR/.mdmeta-source-commit")
if [[ "$ARCHIVE_COMMIT" != "$SOURCE_COMMIT" ]]; then
    printf 'source archive commit identity mismatch\n' >&2
    exit 65
fi
chmod -R u=rX,go= "$SOURCE_DIR"
PARENT_MANIFEST="$SOURCE_DIR/$PARENT_MANIFEST_RELATIVE"
if [[ ! -f "$PARENT_MANIFEST" ]]; then
    printf 'parent manifest is absent from the verified source archive\n' >&2
    exit 66
fi

cp -- "$OLD_JATS" "$RUN_DIR/jats/$OLD_DOCUMENT_ID.xml"
cp -- "$REPLACEMENT_JATS" "$RUN_DIR/jats/$REPLACEMENT_DOCUMENT_ID.xml"
chmod 600 "$RUN_DIR/jats/$OLD_DOCUMENT_ID.xml" \
    "$RUN_DIR/jats/$REPLACEMENT_DOCUMENT_ID.xml"

export PYTHONPATH="$SOURCE_DIR/src"
ENVIRONMENT_TEMP="$RUN_DIR/.environment.txt.tmp"
{
    date --utc --iso-8601=seconds
    hostname
    uname -a
    printf 'source_commit=%s\n' "$SOURCE_COMMIT"
    printf 'source_archive_sha256=%s\n' "$SOURCE_ARCHIVE_SHA256"
    printf 'failed_stage_job_id=%s\n' "$FAILED_STAGE_JOB_ID"
    printf 'substitution_job_id=%s\n' "$SLURM_JOB_ID"
    module list 2>&1
    module show python-data 2>&1
    python3 -c 'import httpx,pydantic; print("httpx=" + httpx.__version__); print("pydantic=" + pydantic.__version__)'
} > "$ENVIRONMENT_TEMP"
mv "$ENVIRONMENT_TEMP" "$RUN_DIR/environment.txt"
chmod 600 "$RUN_DIR/environment.txt"

srun --kill-on-bad-exit=1 --ntasks=1 \
    python3 "$SOURCE_DIR/scripts/substitute_frozen_article.py" \
    --parent-source-manifest "$PARENT_MANIFEST" \
    --parent-source-manifest-sha256 "$PARENT_MANIFEST_FILE_SHA256" \
    --provisional-plan "$PLAN" \
    --provisional-plan-sha256 "$PLAN_FILE_SHA256" \
    --fulltext-screen "$SCREEN" \
    --fulltext-screen-sha256 "$SCREEN_FILE_SHA256" \
    --jats-cache-dir "$RUN_DIR/jats" \
    --replace-document-id "$OLD_DOCUMENT_ID" \
    --replacement-document-id "$REPLACEMENT_DOCUMENT_ID" \
    --failed-stage-job-id "$FAILED_STAGE_JOB_ID" \
    --substitution-job-id "$SLURM_JOB_ID" \
    --expected-observed-old-sha256 "$EXPECTED_OLD_JATS_SHA256" \
    --expected-observed-old-size "$EXPECTED_OLD_JATS_SIZE_BYTES" \
    --output-manifest "$RUN_DIR/output/source_manifest.json" \
    --output-report "$RUN_DIR/output/substitution_report.json"

(
    cd "$RUN_DIR"
    sha256sum environment.txt output/source_manifest.json \
        output/substitution_report.json > SHA256SUMS
    sha256sum --check SHA256SUMS
)
