#!/bin/bash -l
#SBATCH --job-name=mdmeta-source-pool-rebuild
#SBATCH --partition=small
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:30:00

umask 077

# Positional interface:
#   1  private run directory below /scratch/<project>/$USER
#   2  immutable source archive below /projappl/<project>/$USER
#   3  full lowercase source commit
#   4  source archive SHA-256
#   5  original source-manifest file SHA-256
#   6  superseded one-row source-manifest file SHA-256
#   7  superseded one-row substitution-report file SHA-256
#   8  provisional plan component below /projappl/<project>/$USER
#   9  provisional plan file SHA-256
#   10 full-text screen component below /projappl/<project>/$USER
#   11 full-text screen file SHA-256
#   12 accepted audit report below /scratch/<project>/$USER
#   13 accepted audit report file SHA-256
#   14 accepted audit matching-cache below /scratch/<project>/$USER
#   15 accepted audit diagnostic directory below /scratch/<project>/$USER
#   16 ordered comma-separated failed staging job IDs (185329,185656)
RUN_DIR_INPUT=${1:?run directory required}
SOURCE_ARCHIVE_INPUT=${2:?source archive required}
SOURCE_COMMIT=${3:?source commit required}
SOURCE_ARCHIVE_SHA256=${4:?source archive SHA-256 required}
ORIGINAL_MANIFEST_FILE_SHA256=${5:?original source manifest file SHA-256 required}
SUPERSEDED_MANIFEST_FILE_SHA256=${6:?superseded source manifest file SHA-256 required}
SUPERSEDED_REPORT_FILE_SHA256=${7:?superseded substitution report file SHA-256 required}
PLAN_INPUT=${8:?provisional plan artifact required}
PLAN_FILE_SHA256=${9:?provisional plan file SHA-256 required}
SCREEN_INPUT=${10:?full-text screen artifact required}
SCREEN_FILE_SHA256=${11:?full-text screen file SHA-256 required}
AUDIT_REPORT_INPUT=${12:?accepted source-pool audit report required}
AUDIT_REPORT_FILE_SHA256=${13:?accepted audit report file SHA-256 required}
MATCHING_CACHE_INPUT=${14:?accepted audit matching-cache required}
DIAGNOSTIC_DIR_INPUT=${15:?accepted audit diagnostic directory required}
FAILED_STAGE_JOB_IDS=${16:?ordered failed staging job IDs required}

ORIGINAL_MANIFEST_RELATIVE=study/integration_60/source_manifest_original.json
SUPERSEDED_MANIFEST_RELATIVE=study/integration_60/source_manifest.json
SUPERSEDED_REPORT_RELATIVE=study/integration_60/source_substitution_report.json

for candidate in \
    "$RUN_DIR_INPUT" "$SOURCE_ARCHIVE_INPUT" "$PLAN_INPUT" "$SCREEN_INPUT" \
    "$AUDIT_REPORT_INPUT" "$MATCHING_CACHE_INPUT" "$DIAGNOSTIC_DIR_INPUT"; do
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
if ! AUDIT_REPORT=$(realpath -e -- "$AUDIT_REPORT_INPUT"); then
    printf 'accepted audit report does not exist\n' >&2
    exit 66
fi
if ! MATCHING_CACHE=$(realpath -e -- "$MATCHING_CACHE_INPUT"); then
    printf 'accepted audit matching-cache does not exist\n' >&2
    exit 66
fi
if ! DIAGNOSTIC_DIR=$(realpath -e -- "$DIAGNOSTIC_DIR_INPUT"); then
    printf 'accepted audit diagnostic directory does not exist\n' >&2
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
    printf 'rebuild metadata inputs must be regular files inside /projappl/project_*\n' >&2
    exit 64
fi
if [[ "$AUDIT_REPORT" != /scratch/project_*/* || ! -f "$AUDIT_REPORT" ]]; then
    printf 'accepted audit report must be a regular file inside /scratch/project_*\n' >&2
    exit 64
fi
if [[ "$MATCHING_CACHE" != /scratch/project_*/* || ! -d "$MATCHING_CACHE" \
    || "$DIAGNOSTIC_DIR" != /scratch/project_*/* || ! -d "$DIAGNOSTIC_DIR" ]]; then
    printf 'accepted audit cache directories must be inside /scratch/project_*\n' >&2
    exit 64
fi
if [[ "$MATCHING_CACHE" == "$DIAGNOSTIC_DIR" \
    || "$MATCHING_CACHE" == "$DIAGNOSTIC_DIR/"* \
    || "$DIAGNOSTIC_DIR" == "$MATCHING_CACHE/"* ]]; then
    printf 'accepted matching and diagnostic cache directories must not overlap\n' >&2
    exit 64
fi
if [[ "$AUDIT_REPORT" == "$RUN_DIR/"* \
    || "$MATCHING_CACHE" == "$RUN_DIR" || "$MATCHING_CACHE" == "$RUN_DIR/"* \
    || "$DIAGNOSTIC_DIR" == "$RUN_DIR" || "$DIAGNOSTIC_DIR" == "$RUN_DIR/"* \
    || "$RUN_DIR" == "$MATCHING_CACHE/"* || "$RUN_DIR" == "$DIAGNOSTIC_DIR/"* ]]; then
    printf 'accepted audit inputs must be outside the new rebuild run directory\n' >&2
    exit 64
fi
if [[ ! "$SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]]; then
    printf 'source commit must be a full lowercase Git SHA-1\n' >&2
    exit 64
fi
for digest in \
    "$SOURCE_ARCHIVE_SHA256" "$ORIGINAL_MANIFEST_FILE_SHA256" \
    "$SUPERSEDED_MANIFEST_FILE_SHA256" "$SUPERSEDED_REPORT_FILE_SHA256" \
    "$PLAN_FILE_SHA256" "$SCREEN_FILE_SHA256" "$AUDIT_REPORT_FILE_SHA256"; do
    if [[ ! "$digest" =~ ^[0-9a-f]{64}$ ]]; then
        printf 'all requested digests must be lowercase SHA-256 values\n' >&2
        exit 64
    fi
done
if [[ "$FAILED_STAGE_JOB_IDS" != 185329,185656 ]]; then
    printf 'failed staging job IDs must be the ordered evidence pair 185329,185656\n' >&2
    exit 64
fi
if [[ ! "${SLURM_JOB_ID:-}" =~ ^[1-9][0-9]*$ ]]; then
    printf 'source-pool rebuild requires a numeric Slurm job identifier\n' >&2
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
AUDIT_PROJECT=${AUDIT_REPORT#/scratch/}
AUDIT_PROJECT=${AUDIT_PROJECT%%/*}
MATCHING_PROJECT=${MATCHING_CACHE#/scratch/}
MATCHING_PROJECT=${MATCHING_PROJECT%%/*}
DIAGNOSTIC_PROJECT=${DIAGNOSTIC_DIR#/scratch/}
DIAGNOSTIC_PROJECT=${DIAGNOSTIC_PROJECT%%/*}
if [[ ! "$RUN_PROJECT" =~ ^project_[0-9]+$ || ! "$USER" =~ ^[A-Za-z0-9._-]+$ ]]; then
    printf 'project or user identity has an unsafe form\n' >&2
    exit 64
fi
if [[ "$RUN_PROJECT" != "$ARCHIVE_PROJECT" || "$RUN_PROJECT" != "$PLAN_PROJECT" \
    || "$RUN_PROJECT" != "$SCREEN_PROJECT" || "$RUN_PROJECT" != "$AUDIT_PROJECT" \
    || "$RUN_PROJECT" != "$MATCHING_PROJECT" \
    || "$RUN_PROJECT" != "$DIAGNOSTIC_PROJECT" ]]; then
    printf 'all source-pool rebuild paths must belong to the same project\n' >&2
    exit 64
fi
if [[ "$RUN_DIR" != "/scratch/$RUN_PROJECT/$USER/"* \
    || "$SOURCE_ARCHIVE" != "/projappl/$RUN_PROJECT/$USER/"* \
    || "$PLAN" != "/projappl/$RUN_PROJECT/$USER/"* \
    || "$SCREEN" != "/projappl/$RUN_PROJECT/$USER/"* \
    || "$AUDIT_REPORT" != "/scratch/$RUN_PROJECT/$USER/"* \
    || "$MATCHING_CACHE" != "/scratch/$RUN_PROJECT/$USER/"* \
    || "$DIAGNOSTIC_DIR" != "/scratch/$RUN_PROJECT/$USER/"* ]]; then
    printf 'all paths must be below the submitting user private project paths\n' >&2
    exit 64
fi
if [[ "${SLURM_JOB_ACCOUNT:-}" != "$RUN_PROJECT" \
    || "${SLURM_JOB_PARTITION:-}" != small ]]; then
    printf 'source-pool rebuild must use the matching account and small CPU partition\n' >&2
    exit 64
fi

SOURCE_DIR="$RUN_DIR/source"
ARCHIVE_COPY="$RUN_DIR/source-archive.tar"
OUTPUT_DIR="$RUN_DIR/output"
OUTPUT_MANIFEST="$OUTPUT_DIR/source_manifest.json"
OUTPUT_REPORT="$OUTPUT_DIR/rebuild_report.json"

for artifact in \
    "$SOURCE_DIR" "$ARCHIVE_COPY" "$OUTPUT_DIR" "$RUN_DIR/home" \
    "$RUN_DIR/tmp" "$RUN_DIR/cache" "$RUN_DIR/data" \
    "$RUN_DIR/environment.txt" "$RUN_DIR/SHA256SUMS" "$RUN_DIR/exit-code.txt"; do
    if [[ -e "$artifact" || -L "$artifact" ]]; then
        printf 'run artifacts already exist; use a new run directory\n' >&2
        exit 66
    fi
done
if [[ -L "$RUN_DIR/logs" ]]; then
    printf 'run log directory must not be a symbolic link\n' >&2
    exit 66
fi
mkdir -p "$RUN_DIR/logs"
if [[ -n "$(find "$RUN_DIR/logs" -mindepth 1 -maxdepth 1 \
    ! -name "slurm-$SLURM_JOB_ID.out" ! -name "slurm-$SLURM_JOB_ID.err" \
    -print -quit)" ]]; then
    printf 'run log directory contains artifacts from a different job\n' >&2
    exit 66
fi

mkdir -p \
    "$RUN_DIR/home" "$RUN_DIR/tmp" "$RUN_DIR/cache" \
    "$RUN_DIR/data" "$OUTPUT_DIR"
chmod 700 \
    "$RUN_DIR" "$RUN_DIR/home" "$RUN_DIR/logs" "$RUN_DIR/tmp" \
    "$RUN_DIR/cache" "$RUN_DIR/data" "$OUTPUT_DIR"

if ! module load python-data; then
    printf 'failed to load python-data\n' >&2
    exit 69
fi
if [[ "$(uname -m)" != x86_64 ]]; then
    printf 'source-pool rebuild requires an x86_64 Roihu CPU node\n' >&2
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
export MDMETA_OFFLINE=1

record_exit() {
    local exit_code=$?
    local checksum_exit=0
    trap - EXIT
    set +e

    chmod 700 "$OUTPUT_DIR" 2>/dev/null
    find "$OUTPUT_DIR" -type f -exec chmod 600 {} + 2>/dev/null

    if [[ -f "$RUN_DIR/environment.txt" && -f "$OUTPUT_REPORT" ]]; then
        (
            cd "$RUN_DIR" || exit 1
            checksum_inputs=(environment.txt output/rebuild_report.json)
            if [[ -f output/source_manifest.json ]]; then
                checksum_inputs+=(output/source_manifest.json)
            fi
            sha256sum "${checksum_inputs[@]}" > .SHA256SUMS.tmp || exit 1
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

ORIGINAL_MANIFEST="$SOURCE_DIR/$ORIGINAL_MANIFEST_RELATIVE"
SUPERSEDED_MANIFEST="$SOURCE_DIR/$SUPERSEDED_MANIFEST_RELATIVE"
SUPERSEDED_REPORT="$SOURCE_DIR/$SUPERSEDED_REPORT_RELATIVE"
for lineage_input in \
    "$ORIGINAL_MANIFEST" "$SUPERSEDED_MANIFEST" "$SUPERSEDED_REPORT"; do
    if [[ ! -f "$lineage_input" || -L "$lineage_input" ]]; then
        printf 'required lineage input is absent from the verified source archive\n' >&2
        exit 66
    fi
done
chmod -R u=rX,go= "$SOURCE_DIR"

ACTUAL_ORIGINAL_SHA256=$(sha256sum "$ORIGINAL_MANIFEST" | awk '{print $1}')
ACTUAL_SUPERSEDED_MANIFEST_SHA256=$(sha256sum "$SUPERSEDED_MANIFEST" | awk '{print $1}')
ACTUAL_SUPERSEDED_REPORT_SHA256=$(sha256sum "$SUPERSEDED_REPORT" | awk '{print $1}')
ACTUAL_PLAN_SHA256=$(sha256sum "$PLAN" | awk '{print $1}')
ACTUAL_SCREEN_SHA256=$(sha256sum "$SCREEN" | awk '{print $1}')
ACTUAL_AUDIT_REPORT_SHA256=$(sha256sum "$AUDIT_REPORT" | awk '{print $1}')
if [[ "$ACTUAL_ORIGINAL_SHA256" != "$ORIGINAL_MANIFEST_FILE_SHA256" ]]; then
    printf 'original source manifest digest mismatch\n' >&2
    exit 65
fi
if [[ "$ACTUAL_SUPERSEDED_MANIFEST_SHA256" != "$SUPERSEDED_MANIFEST_FILE_SHA256" ]]; then
    printf 'superseded source manifest digest mismatch\n' >&2
    exit 65
fi
if [[ "$ACTUAL_SUPERSEDED_REPORT_SHA256" != "$SUPERSEDED_REPORT_FILE_SHA256" ]]; then
    printf 'superseded substitution report digest mismatch\n' >&2
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
if [[ "$ACTUAL_AUDIT_REPORT_SHA256" != "$AUDIT_REPORT_FILE_SHA256" ]]; then
    printf 'accepted audit report digest mismatch\n' >&2
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
    printf 'original_source_manifest_file_sha256=%s\n' "$ORIGINAL_MANIFEST_FILE_SHA256"
    printf 'superseded_source_manifest_file_sha256=%s\n' "$SUPERSEDED_MANIFEST_FILE_SHA256"
    printf 'superseded_substitution_report_file_sha256=%s\n' "$SUPERSEDED_REPORT_FILE_SHA256"
    printf 'provisional_plan_file_sha256=%s\n' "$PLAN_FILE_SHA256"
    printf 'fulltext_screen_file_sha256=%s\n' "$SCREEN_FILE_SHA256"
    printf 'accepted_audit_report_file_sha256=%s\n' "$AUDIT_REPORT_FILE_SHA256"
    printf 'failed_stage_job_ids=%s\n' "$FAILED_STAGE_JOB_IDS"
    printf 'rebuild_job_id=%s\n' "$SLURM_JOB_ID"
    printf 'slurm_account=%s\n' "$SLURM_JOB_ACCOUNT"
    printf 'slurm_partition=%s\n' "$SLURM_JOB_PARTITION"
    printf 'slurm_node=%s\n' "${SLURMD_NODENAME:-unknown}"
    printf 'network_used=false\n'
    printf 'private_paths_recorded=false\n'
    module list 2>&1
    module show python-data 2>&1
    python3 -c 'import defusedxml,httpx,pydantic; print("httpx=" + httpx.__version__); print("pydantic=" + pydantic.__version__); print("defusedxml=" + defusedxml.__version__)'
} > "$ENVIRONMENT_TEMP"
mv "$ENVIRONMENT_TEMP" "$RUN_DIR/environment.txt"
chmod 600 "$RUN_DIR/environment.txt"

set +e
srun --kill-on-bad-exit=1 --ntasks=1 \
    python3 "$SOURCE_DIR/scripts/rebuild_frozen_source_pool.py" \
    --original-source-manifest "$ORIGINAL_MANIFEST" \
    --original-source-manifest-sha256 "$ORIGINAL_MANIFEST_FILE_SHA256" \
    --superseded-source-manifest "$SUPERSEDED_MANIFEST" \
    --superseded-source-manifest-sha256 "$SUPERSEDED_MANIFEST_FILE_SHA256" \
    --superseded-substitution-report "$SUPERSEDED_REPORT" \
    --superseded-substitution-report-sha256 "$SUPERSEDED_REPORT_FILE_SHA256" \
    --provisional-plan "$PLAN" \
    --provisional-plan-sha256 "$PLAN_FILE_SHA256" \
    --fulltext-screen "$SCREEN" \
    --fulltext-screen-sha256 "$SCREEN_FILE_SHA256" \
    --accepted-audit-report "$AUDIT_REPORT" \
    --accepted-audit-report-sha256 "$AUDIT_REPORT_FILE_SHA256" \
    --matching-cache-dir "$MATCHING_CACHE" \
    --diagnostic-dir "$DIAGNOSTIC_DIR" \
    --source-commit "$SOURCE_COMMIT" \
    --source-archive-sha256 "$SOURCE_ARCHIVE_SHA256" \
    --failed-stage-job-ids "$FAILED_STAGE_JOB_IDS" \
    --rebuild-job-id "$SLURM_JOB_ID" \
    --output-manifest "$OUTPUT_MANIFEST" \
    --output-report "$OUTPUT_REPORT"
REBUILD_EXIT_CODE=$?
set -e

if [[ "$REBUILD_EXIT_CODE" -eq 3 ]]; then
    python3 -c '
import json
import sys
from pathlib import Path

from scripts.rebuild_frozen_source_pool import (
    validate_blocked_rebuild_report_files,
)

report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
validate_blocked_rebuild_report_files(
    report,
    original_manifest_path=Path(sys.argv[2]),
    expected_original_manifest_file_sha256=sys.argv[3],
    superseded_manifest_path=Path(sys.argv[4]),
    expected_superseded_manifest_file_sha256=sys.argv[5],
    superseded_substitution_report_path=Path(sys.argv[6]),
    expected_superseded_substitution_report_file_sha256=sys.argv[7],
    provisional_plan_path=Path(sys.argv[8]),
    expected_plan_file_sha256=sys.argv[9],
    fulltext_screen_path=Path(sys.argv[10]),
    expected_screen_file_sha256=sys.argv[11],
    accepted_audit_report_path=Path(sys.argv[12]),
    expected_audit_report_file_sha256=sys.argv[13],
    matching_cache_dir=Path(sys.argv[14]),
    diagnostic_dir=Path(sys.argv[15]),
)
' "$OUTPUT_REPORT" \
        "$ORIGINAL_MANIFEST" "$ORIGINAL_MANIFEST_FILE_SHA256" \
        "$SUPERSEDED_MANIFEST" "$SUPERSEDED_MANIFEST_FILE_SHA256" \
        "$SUPERSEDED_REPORT" "$SUPERSEDED_REPORT_FILE_SHA256" \
        "$PLAN" "$PLAN_FILE_SHA256" "$SCREEN" "$SCREEN_FILE_SHA256" \
        "$AUDIT_REPORT" "$AUDIT_REPORT_FILE_SHA256" \
        "$MATCHING_CACHE" "$DIAGNOSTIC_DIR"
    exit 3
fi
if [[ "$REBUILD_EXIT_CODE" -ne 0 ]]; then
    exit "$REBUILD_EXIT_CODE"
fi

python3 -c '
import json
import sys
from pathlib import Path

from scripts.rebuild_frozen_source_pool import validate_rebuild_outputs

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
report = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
audit = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
validate_rebuild_outputs(
    manifest,
    report,
    audit,
    original_manifest_path=Path(sys.argv[4]),
    expected_original_manifest_file_sha256=sys.argv[5],
    superseded_manifest_path=Path(sys.argv[6]),
    expected_superseded_manifest_file_sha256=sys.argv[7],
    superseded_substitution_report_path=Path(sys.argv[8]),
    expected_superseded_substitution_report_file_sha256=sys.argv[9],
    provisional_plan_path=Path(sys.argv[10]),
    expected_plan_file_sha256=sys.argv[11],
    fulltext_screen_path=Path(sys.argv[12]),
    expected_screen_file_sha256=sys.argv[13],
    accepted_audit_report_path=Path(sys.argv[3]),
    expected_audit_report_file_sha256=sys.argv[14],
    matching_cache_dir=Path(sys.argv[15]),
    diagnostic_dir=Path(sys.argv[16]),
)
' "$OUTPUT_MANIFEST" "$OUTPUT_REPORT" "$AUDIT_REPORT" \
    "$ORIGINAL_MANIFEST" "$ORIGINAL_MANIFEST_FILE_SHA256" \
    "$SUPERSEDED_MANIFEST" "$SUPERSEDED_MANIFEST_FILE_SHA256" \
    "$SUPERSEDED_REPORT" "$SUPERSEDED_REPORT_FILE_SHA256" \
    "$PLAN" "$PLAN_FILE_SHA256" "$SCREEN" "$SCREEN_FILE_SHA256" \
    "$AUDIT_REPORT_FILE_SHA256" "$MATCHING_CACHE" "$DIAGNOSTIC_DIR"
