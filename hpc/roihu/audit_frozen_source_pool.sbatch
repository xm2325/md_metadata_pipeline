#!/bin/bash -l
#SBATCH --job-name=mdmeta-source-pool-audit
#SBATCH --partition=small
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=04:00:00

umask 077

# Positional interface:
#   1  private run directory below /scratch/<project>/$USER
#   2  immutable source archive below /projappl/<project>/$USER
#   3  full lowercase source commit
#   4  source archive SHA-256
#   5  original source-manifest file SHA-256
#   6  provisional plan component below /projappl/<project>/$USER
#   7  provisional plan file SHA-256
#   8  full-text screen component below /projappl/<project>/$USER
#   9  full-text screen file SHA-256
RUN_DIR_INPUT=${1:?run directory required}
SOURCE_ARCHIVE_INPUT=${2:?source archive required}
SOURCE_COMMIT=${3:?source commit required}
SOURCE_ARCHIVE_SHA256=${4:?source archive SHA-256 required}
PARENT_MANIFEST_FILE_SHA256=${5:?original source manifest file SHA-256 required}
PLAN_INPUT=${6:?provisional plan artifact required}
PLAN_FILE_SHA256=${7:?provisional plan file SHA-256 required}
SCREEN_INPUT=${8:?full-text screen artifact required}
SCREEN_FILE_SHA256=${9:?full-text screen file SHA-256 required}

PARENT_MANIFEST_RELATIVE=study/integration_60/source_manifest_original.json

for candidate in "$RUN_DIR_INPUT" "$SOURCE_ARCHIVE_INPUT" "$PLAN_INPUT" "$SCREEN_INPUT"; do
    if [[ -L "$candidate" ]]; then
        printf 'path arguments must not be symbolic links\n' >&2
        exit 64
    fi
done

if ! RUN_DIR=$(realpath -m -- "$RUN_DIR_INPUT"); then
    printf 'could not canonicalize run directory\n' >&2
    exit 64
fi
if ! SOURCE_ARCHIVE=$(realpath -e -- "$SOURCE_ARCHIVE_INPUT"); then
    printf 'source archive does not exist\n' >&2
    exit 66
fi
if ! PLAN=$(realpath -e -- "$PLAN_INPUT"); then
    printf 'provisional plan does not exist\n' >&2
    exit 66
fi
if ! SCREEN=$(realpath -e -- "$SCREEN_INPUT"); then
    printf 'full-text screen does not exist\n' >&2
    exit 66
fi

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
    printf 'audit components must be regular files inside /projappl/project_*\n' >&2
    exit 64
fi
if [[ ! "$SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]]; then
    printf 'source commit must be a full lowercase Git SHA-1\n' >&2
    exit 64
fi
for digest in \
    "$SOURCE_ARCHIVE_SHA256" "$PARENT_MANIFEST_FILE_SHA256" \
    "$PLAN_FILE_SHA256" "$SCREEN_FILE_SHA256"; do
    if [[ ! "$digest" =~ ^[0-9a-f]{64}$ ]]; then
        printf 'all requested digests must be lowercase SHA-256 values\n' >&2
        exit 64
    fi
done
if [[ ! "${SLURM_JOB_ID:-}" =~ ^[1-9][0-9]*$ ]]; then
    printf 'source-pool audit requires a numeric Slurm job identifier\n' >&2
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
if [[ ! "$RUN_PROJECT" =~ ^project_[0-9]+$ || ! "$USER" =~ ^[A-Za-z0-9._-]+$ ]]; then
    printf 'project or user identity has an unsafe form\n' >&2
    exit 64
fi
if [[ "$RUN_PROJECT" != "$ARCHIVE_PROJECT" || "$RUN_PROJECT" != "$PLAN_PROJECT" \
    || "$RUN_PROJECT" != "$SCREEN_PROJECT" ]]; then
    printf 'all source-pool audit paths must belong to the same project\n' >&2
    exit 64
fi
if [[ "$RUN_DIR" != "/scratch/$RUN_PROJECT/$USER/"* \
    || "$SOURCE_ARCHIVE" != "/projappl/$RUN_PROJECT/$USER/"* \
    || "$PLAN" != "/projappl/$RUN_PROJECT/$USER/"* \
    || "$SCREEN" != "/projappl/$RUN_PROJECT/$USER/"* ]]; then
    printf 'all paths must be below the submitting user private project paths\n' >&2
    exit 64
fi
if [[ "${SLURM_JOB_ACCOUNT:-}" != "$RUN_PROJECT" \
    || "${SLURM_JOB_PARTITION:-}" != small ]]; then
    printf 'source-pool audit must use the matching account and small CPU partition\n' >&2
    exit 64
fi

SOURCE_DIR="$RUN_DIR/source"
ARCHIVE_COPY="$RUN_DIR/source-archive.tar"
OUTPUT_DIR="$RUN_DIR/output"
REPORT="$OUTPUT_DIR/source_pool_audit.json"
MATCHING_CACHE="$RUN_DIR/matching-cache"
DIAGNOSTIC_DIR="$RUN_DIR/diagnostic"

for artifact in \
    "$SOURCE_DIR" "$ARCHIVE_COPY" "$OUTPUT_DIR" "$MATCHING_CACHE" \
    "$DIAGNOSTIC_DIR" "$RUN_DIR/environment.txt" "$RUN_DIR/SHA256SUMS" \
    "$RUN_DIR/exit-code.txt"; do
    if [[ -e "$artifact" ]]; then
        printf 'run artifacts already exist; use a new run directory\n' >&2
        exit 66
    fi
done

mkdir -p \
    "$RUN_DIR/home" "$RUN_DIR/logs" "$RUN_DIR/tmp" "$OUTPUT_DIR" \
    "$MATCHING_CACHE" "$DIAGNOSTIC_DIR"
chmod 700 \
    "$RUN_DIR" "$RUN_DIR/home" "$RUN_DIR/logs" "$RUN_DIR/tmp" "$OUTPUT_DIR" \
    "$MATCHING_CACHE" "$DIAGNOSTIC_DIR"

if ! module load python-data; then
    printf 'failed to load python-data\n' >&2
    exit 69
fi
if [[ "$(uname -m)" != x86_64 ]]; then
    printf 'source-pool audit requires an x86_64 Roihu CPU node\n' >&2
    exit 69
fi
export SLURM_EXPORT_ENV=ALL
set -Eeuo pipefail

export HOME="$RUN_DIR/home"
export XDG_CACHE_HOME="$RUN_DIR/cache"
export XDG_DATA_HOME="$RUN_DIR/data"
export TMPDIR="$RUN_DIR/tmp"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export PYTHONHASHSEED=3997

record_exit() {
    local exit_code=$?
    local checksum_exit=0
    trap - EXIT
    set +e

    chmod 700 "$OUTPUT_DIR" "$MATCHING_CACHE" "$DIAGNOSTIC_DIR" 2>/dev/null
    find "$MATCHING_CACHE" "$DIAGNOSTIC_DIR" -type f -exec chmod 600 {} + 2>/dev/null

    if [[ -f "$RUN_DIR/environment.txt" && -f "$REPORT" ]]; then
        (
            cd "$RUN_DIR" || exit 1
            sha256sum environment.txt output/source_pool_audit.json \
                > .SHA256SUMS.tmp || exit 1
            mv .SHA256SUMS.tmp SHA256SUMS || exit 1
            sha256sum --check SHA256SUMS
        )
        checksum_exit=$?
        if [[ "$checksum_exit" -ne 0 && "$exit_code" -eq 0 ]]; then
            exit_code=74
        fi
    fi

    printf '%s\n' "$exit_code" > "$RUN_DIR/.exit-code.tmp"
    mv "$RUN_DIR/.exit-code.tmp" "$RUN_DIR/exit-code.txt"
    exit "$exit_code"
}
trap record_exit EXIT

cp -- "$SOURCE_ARCHIVE" "$ARCHIVE_COPY"
chmod 600 "$ARCHIVE_COPY"
ACTUAL_ARCHIVE_SHA256=$(sha256sum "$ARCHIVE_COPY" | awk '{print $1}')
if [[ "$ACTUAL_ARCHIVE_SHA256" != "$SOURCE_ARCHIVE_SHA256" ]]; then
    printf 'source archive digest mismatch\n' >&2
    exit 65
fi

python3 -c '
import posixpath
import sys
import tarfile

archive_name, expected_commit = sys.argv[1:]
seen = set()
commit_payload = None
with tarfile.open(archive_name, "r:*") as archive:
    for member in archive:
        name = member.name
        stripped = name.rstrip("/")
        normalized = posixpath.normpath(name)
        if (
            not name
            or name.startswith("/")
            or normalized in {"", ".", ".."}
            or normalized.startswith("../")
            or normalized != stripped
        ):
            raise SystemExit(f"unsafe archive member path: {name!r}")
        if normalized in seen:
            raise SystemExit(f"duplicate archive member path: {normalized!r}")
        seen.add(normalized)
        if member.issym() or member.islnk():
            raise SystemExit(f"archive link members are forbidden: {normalized!r}")
        if not (member.isfile() or member.isdir()):
            raise SystemExit(f"archive special members are forbidden: {normalized!r}")
        if normalized == ".mdmeta-source-commit":
            if not member.isfile():
                raise SystemExit("source commit marker must be a regular file")
            handle = archive.extractfile(member)
            if handle is None:
                raise SystemExit("source commit marker could not be read")
            commit_payload = handle.read(128)

if commit_payload is None:
    raise SystemExit("source archive does not contain .mdmeta-source-commit")
try:
    observed_commit = commit_payload.decode("ascii").rstrip("\r\n")
except UnicodeDecodeError as error:
    raise SystemExit("source commit marker is not ASCII") from error
if observed_commit != expected_commit:
    raise SystemExit("source archive commit identity mismatch")
' "$ARCHIVE_COPY" "$SOURCE_COMMIT"

mkdir "$SOURCE_DIR"
tar --extract --file "$ARCHIVE_COPY" --directory "$SOURCE_DIR" \
    --no-same-owner --no-same-permissions
if [[ -n "$(find "$SOURCE_DIR" -type l -print -quit)" ]]; then
    printf 'extracted source snapshot contains a symbolic link\n' >&2
    exit 65
fi
if [[ ! -f "$SOURCE_DIR/.mdmeta-source-commit" ]]; then
    printf 'extracted source snapshot lost its commit identity\n' >&2
    exit 65
fi
EXTRACTED_COMMIT=$(tr -d '\r\n' < "$SOURCE_DIR/.mdmeta-source-commit")
if [[ "$EXTRACTED_COMMIT" != "$SOURCE_COMMIT" ]]; then
    printf 'extracted source commit identity mismatch\n' >&2
    exit 65
fi
PARENT_MANIFEST="$SOURCE_DIR/$PARENT_MANIFEST_RELATIVE"
if [[ ! -f "$PARENT_MANIFEST" || -L "$PARENT_MANIFEST" ]]; then
    printf 'original source manifest is absent from the verified source archive\n' >&2
    exit 66
fi
chmod -R u=rX,go= "$SOURCE_DIR"

ACTUAL_PARENT_SHA256=$(sha256sum "$PARENT_MANIFEST" | awk '{print $1}')
ACTUAL_PLAN_SHA256=$(sha256sum "$PLAN" | awk '{print $1}')
ACTUAL_SCREEN_SHA256=$(sha256sum "$SCREEN" | awk '{print $1}')
if [[ "$ACTUAL_PARENT_SHA256" != "$PARENT_MANIFEST_FILE_SHA256" ]]; then
    printf 'original source manifest digest mismatch\n' >&2
    exit 65
fi
if [[ "$ACTUAL_PLAN_SHA256" != "$PLAN_FILE_SHA256" ]]; then
    printf 'provisional plan digest mismatch\n' >&2
    exit 65
fi
if [[ "$ACTUAL_SCREEN_SHA256" != "$SCREEN_FILE_SHA256" ]]; then
    printf 'full-text screen digest mismatch\n' >&2
    exit 65
fi

export PYTHONPATH="$SOURCE_DIR:$SOURCE_DIR/src"
ENVIRONMENT_TEMP="$RUN_DIR/.environment.txt.tmp"
{
    date --utc --iso-8601=seconds
    hostname
    uname -a
    printf 'source_commit=%s\n' "$SOURCE_COMMIT"
    printf 'source_archive_sha256=%s\n' "$SOURCE_ARCHIVE_SHA256"
    printf 'original_source_manifest_file_sha256=%s\n' "$PARENT_MANIFEST_FILE_SHA256"
    printf 'provisional_plan_file_sha256=%s\n' "$PLAN_FILE_SHA256"
    printf 'fulltext_screen_file_sha256=%s\n' "$SCREEN_FILE_SHA256"
    printf 'audit_job_id=%s\n' "$SLURM_JOB_ID"
    printf 'slurm_account=%s\n' "$SLURM_JOB_ACCOUNT"
    printf 'slurm_partition=%s\n' "$SLURM_JOB_PARTITION"
    printf 'slurm_node=%s\n' "${SLURMD_NODENAME:-unknown}"
    module list 2>&1
    module show python-data 2>&1
    python3 -c 'import defusedxml,httpx,pydantic; print("httpx=" + httpx.__version__); print("pydantic=" + pydantic.__version__); print("defusedxml=" + defusedxml.__version__)'
} > "$ENVIRONMENT_TEMP"
mv "$ENVIRONMENT_TEMP" "$RUN_DIR/environment.txt"
chmod 600 "$RUN_DIR/environment.txt"

srun --kill-on-bad-exit=1 --ntasks=1 \
    python3 "$SOURCE_DIR/scripts/audit_frozen_source_pool.py" \
    --parent-source-manifest "$PARENT_MANIFEST" \
    --parent-source-manifest-sha256 "$PARENT_MANIFEST_FILE_SHA256" \
    --provisional-plan "$PLAN" \
    --provisional-plan-sha256 "$PLAN_FILE_SHA256" \
    --fulltext-screen "$SCREEN" \
    --fulltext-screen-sha256 "$SCREEN_FILE_SHA256" \
    --source-commit "$SOURCE_COMMIT" \
    --source-archive-sha256 "$SOURCE_ARCHIVE_SHA256" \
    --audit-job-id "$SLURM_JOB_ID" \
    --matching-cache-dir "$MATCHING_CACHE" \
    --diagnostic-dir "$DIAGNOSTIC_DIR" \
    --output-report "$REPORT" \
    --timeout 20 \
    --retries 2

python3 -c '
import json
import sys
from pathlib import Path

from scripts.audit_frozen_source_pool import validate_audit_cache

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
validate_audit_cache(
    payload,
    matching_cache_dir=Path(sys.argv[2]),
    diagnostic_dir=Path(sys.argv[3]),
    require_complete=True,
)
' "$REPORT" "$MATCHING_CACHE" "$DIAGNOSTIC_DIR"
