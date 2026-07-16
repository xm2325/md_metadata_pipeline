#!/bin/bash -l
#SBATCH --job-name=mdmeta-cpu-validate
#SBATCH --partition=small
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:30:00

umask 077

RUN_DIR_INPUT=${1:?run directory required}
SOURCE_ARCHIVE_INPUT=${2:?source archive required}
SOURCE_COMMIT=${3:?source commit required}
SOURCE_ARCHIVE_SHA256=${4:?source archive SHA-256 required}

if [[ -L "$RUN_DIR_INPUT" || -L "$SOURCE_ARCHIVE_INPUT" ]]; then
    printf 'run directory and source archive arguments must not be symbolic links\n' >&2
    exit 64
fi
if ! RUN_DIR=$(realpath -m -- "$RUN_DIR_INPUT"); then
    printf 'could not canonicalize run directory\n' >&2
    exit 64
fi
if ! SOURCE_ARCHIVE=$(realpath -e -- "$SOURCE_ARCHIVE_INPUT"); then
    printf 'source archive does not exist\n' >&2
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
ARCHIVE_PROJECT=${SOURCE_ARCHIVE#/projappl/}
ARCHIVE_PROJECT=${ARCHIVE_PROJECT%%/*}
if [[ ! "$RUN_PROJECT" =~ ^project_[0-9]+$ || ! "$USER" =~ ^[A-Za-z0-9._-]+$ ]]; then
    printf 'project or user identity has an unsafe form\n' >&2
    exit 64
fi
if [[ "$RUN_PROJECT" != "$ARCHIVE_PROJECT" ]]; then
    printf 'run directory and source archive must belong to the same project\n' >&2
    exit 64
fi
if [[ "$RUN_DIR" != "/scratch/$RUN_PROJECT/$USER/"* ]]; then
    printf 'run directory must be below the submitting user private project path\n' >&2
    exit 64
fi
if [[ "$SOURCE_ARCHIVE" != "/projappl/$ARCHIVE_PROJECT/$USER/"* ]]; then
    printf 'source archive must be below the submitting user private project path\n' >&2
    exit 64
fi
if [[ -n "${SLURM_JOB_ACCOUNT:-}" && "$SLURM_JOB_ACCOUNT" != "$RUN_PROJECT" ]]; then
    printf 'Slurm account does not match the storage project\n' >&2
    exit 64
fi
if [[ -n "${SLURM_JOB_PARTITION:-}" && "$SLURM_JOB_PARTITION" != small ]]; then
    printf 'CPU validation must run in the small partition\n' >&2
    exit 64
fi

if [[ -e "$RUN_DIR/source" || -e "$RUN_DIR/result.json" ]]; then
    printf 'run artifacts already exist; use a new run directory\n' >&2
    exit 66
fi
mkdir -p "$RUN_DIR/home" "$RUN_DIR/logs" "$RUN_DIR/tmp"
chmod 700 "$RUN_DIR" "$RUN_DIR/home" "$RUN_DIR/logs" "$RUN_DIR/tmp"

if ! module load python-data; then
    printf 'failed to load python-data\n' >&2
    exit 69
fi
if [[ "$(uname -m)" != x86_64 ]]; then
    printf 'CPU validation requires an x86_64 Roihu CPU node\n' >&2
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
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
unset PYTEST_ADDOPTS || true

SUMMARY_PATH="$RUN_DIR/result.json"
PYTEST_LOG="$RUN_DIR/pytest.log"
JUNIT_XML="$RUN_DIR/pytest.xml"
ARCHIVE_COPY="$RUN_DIR/source-archive.tar"
ARCHIVE_INVENTORY="$RUN_DIR/archive-inventory.json"
SOURCE_DIR="$RUN_DIR/source"
STARTED_AT=$(date --utc --iso-8601=seconds)
STAGE=initializing
PYTEST_EXIT_CODE=''
ARCHIVE_SHA_VERIFIED=0
ARCHIVE_SAFETY_VERIFIED=0
SOURCE_COMMIT_VERIFIED=0

write_summary() {
    local process_exit_code=$1
    local completed_at=$2
    python3 -c '
import hashlib
import importlib.metadata
import json
import os
import platform
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

(
    output_name,
    run_name,
    source_commit,
    source_digest,
    started_at,
    completed_at,
    process_exit,
    pytest_exit,
    stage,
    archive_sha_verified,
    archive_safety_verified,
    source_commit_verified,
) = sys.argv[1:]
output = Path(output_name)
run_dir = Path(run_name)

def version(distribution):
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None

def digest(relative):
    path = run_dir / relative
    if not path.is_file():
        return None
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()

inventory = None
inventory_path = run_dir / "archive-inventory.json"
if inventory_path.is_file():
    try:
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        inventory = None

junit = None
junit_path = run_dir / "pytest.xml"
if junit_path.is_file():
    try:
        root = ET.parse(junit_path).getroot()
        suites = [root] if root.tag == "testsuite" else list(root.findall("./testsuite"))
        junit = {
            "tests": sum(int(item.attrib.get("tests", 0)) for item in suites),
            "failures": sum(int(item.attrib.get("failures", 0)) for item in suites),
            "errors": sum(int(item.attrib.get("errors", 0)) for item in suites),
            "skipped": sum(int(item.attrib.get("skipped", 0)) for item in suites),
            "seconds": sum(float(item.attrib.get("time", 0.0)) for item in suites),
        }
    except (ET.ParseError, OSError, TypeError, ValueError):
        junit = None

exit_code = int(process_exit)
payload = {
    "schema_version": "mdmeta.roihu-cpu-validation.v1",
    "status": "pass" if exit_code == 0 else "fail",
    "stage": stage,
    "started_at": started_at,
    "completed_at": completed_at,
    "exit_code": exit_code,
    "source": {
        "commit": source_commit,
        "archive_sha256": source_digest,
        "archive_sha256_verified": archive_sha_verified == "1",
        "archive_safety_verified": archive_safety_verified == "1",
        "commit_marker_verified": source_commit_verified == "1",
        "execution_source": "verified_archive_snapshot",
        "source_path_recorded": False,
        "archive_inventory": inventory,
    },
    "slurm": {
        "job_id": os.environ.get("SLURM_JOB_ID"),
        "account": os.environ.get("SLURM_JOB_ACCOUNT"),
        "partition": os.environ.get("SLURM_JOB_PARTITION"),
        "node": os.environ.get("SLURMD_NODENAME"),
    },
    "runtime": {
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "pytest": version("pytest"),
        "pydantic": version("pydantic"),
        "httpx": version("httpx"),
        "defusedxml": version("defusedxml"),
    },
    "pytest": {
        "exit_code": int(pytest_exit) if pytest_exit else None,
        "test_files": [
            "tests/test_llm_adapter.py",
            "tests/test_llm_batch.py",
            "tests/test_model_snapshot.py",
            "tests/test_model_backed_integration.py",
            "tests/test_substitute_frozen_article.py",
            "tests/test_audit_frozen_source_pool.py",
            "tests/test_rebuild_frozen_source_pool.py",
        ],
        "junit": junit,
        "log_path": "pytest.log",
        "junit_path": "pytest.xml" if junit_path.is_file() else None,
        "log_sha256": digest("pytest.log"),
        "junit_sha256": digest("pytest.xml"),
    },
    "environment_sha256": digest("environment.txt"),
}
output.parent.mkdir(parents=True, exist_ok=True)
descriptor, temporary_name = tempfile.mkstemp(
    dir=output.parent, prefix=f".{output.name}.", suffix=".tmp"
)
temporary = Path(temporary_name)
try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, output)
    os.chmod(output, 0o600)
finally:
    temporary.unlink(missing_ok=True)
' "$SUMMARY_PATH" "$RUN_DIR" "$SOURCE_COMMIT" "$SOURCE_ARCHIVE_SHA256" \
        "$STARTED_AT" "$completed_at" "$process_exit_code" "$PYTEST_EXIT_CODE" \
        "$STAGE" "$ARCHIVE_SHA_VERIFIED" "$ARCHIVE_SAFETY_VERIFIED" \
        "$SOURCE_COMMIT_VERIFIED"
}

record_exit() {
    local process_exit_code=$?
    local completed_at
    completed_at=$(date --utc --iso-8601=seconds)
    trap - EXIT
    set +e
    if ! write_summary "$process_exit_code" "$completed_at"; then
        printf 'failed to write machine-readable validation summary\n' >&2
        if [[ "$process_exit_code" -eq 0 ]]; then
            process_exit_code=70
        fi
    fi
    printf '%s\n' "$process_exit_code" > "$RUN_DIR/.exit-code.tmp"
    mv "$RUN_DIR/.exit-code.tmp" "$RUN_DIR/exit-code.txt"
    exit "$process_exit_code"
}
trap record_exit EXIT

STAGE=archive_copy
cp -- "$SOURCE_ARCHIVE" "$ARCHIVE_COPY"
chmod 600 "$ARCHIVE_COPY"
ACTUAL_ARCHIVE_SHA256=$(sha256sum "$ARCHIVE_COPY" | awk '{print $1}')
if [[ "$ACTUAL_ARCHIVE_SHA256" != "$SOURCE_ARCHIVE_SHA256" ]]; then
    printf 'source archive digest mismatch\n' >&2
    exit 65
fi
ARCHIVE_SHA_VERIFIED=1

STAGE=archive_safety
python3 -c '
import json
import posixpath
import sys
import tarfile

archive_name, expected_commit = sys.argv[1:]
seen = set()
member_count = 0
regular_file_count = 0
total_regular_file_bytes = 0
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
        member_count += 1
        if member.isfile():
            regular_file_count += 1
            total_regular_file_bytes += member.size
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
print(json.dumps({
    "member_count": member_count,
    "regular_file_count": regular_file_count,
    "total_regular_file_bytes": total_regular_file_bytes,
}, sort_keys=True))
' "$ARCHIVE_COPY" "$SOURCE_COMMIT" > "$RUN_DIR/.archive-inventory.json.tmp"
mv "$RUN_DIR/.archive-inventory.json.tmp" "$ARCHIVE_INVENTORY"
chmod 600 "$ARCHIVE_INVENTORY"
ARCHIVE_SAFETY_VERIFIED=1
SOURCE_COMMIT_VERIFIED=1

STAGE=archive_extract
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
chmod -R u=rX,go= "$SOURCE_DIR"

STAGE=environment
export PYTHONPATH="$SOURCE_DIR/src"
ENVIRONMENT_TEMP="$RUN_DIR/.environment.txt.tmp"
{
    date --utc --iso-8601=seconds
    hostname
    uname -a
    printf 'source_commit=%s\n' "$SOURCE_COMMIT"
    printf 'source_archive_sha256=%s\n' "$SOURCE_ARCHIVE_SHA256"
    module list 2>&1
    module show python-data 2>&1
    python3 -c 'import defusedxml,httpx,pydantic,pytest; print("pytest=" + pytest.__version__); print("httpx=" + httpx.__version__); print("pydantic=" + pydantic.__version__); print("defusedxml=" + defusedxml.__version__)'
} > "$ENVIRONMENT_TEMP"
mv "$ENVIRONMENT_TEMP" "$RUN_DIR/environment.txt"
chmod 600 "$RUN_DIR/environment.txt"

TEST_FILES=(
    tests/test_llm_adapter.py
    tests/test_llm_batch.py
    tests/test_model_snapshot.py
    tests/test_model_backed_integration.py
    tests/test_substitute_frozen_article.py
    tests/test_audit_frozen_source_pool.py
    tests/test_rebuild_frozen_source_pool.py
)

STAGE=pytest
set +e
(
    cd "$SOURCE_DIR"
    srun --kill-on-bad-exit=1 --ntasks=1 \
        python3 -m pytest \
        --quiet \
        --color=no \
        -p no:cacheprovider \
        --basetemp="$RUN_DIR/pytest-tmp" \
        --junitxml="$JUNIT_XML" \
        "${TEST_FILES[@]}"
) 2>&1 | tee "$PYTEST_LOG"
PIPE_EXIT_CODES=("${PIPESTATUS[@]}")
set -e
PYTEST_EXIT_CODE=${PIPE_EXIT_CODES[0]}
TEE_EXIT_CODE=${PIPE_EXIT_CODES[1]}
chmod 600 "$PYTEST_LOG"
if [[ "$TEE_EXIT_CODE" -ne 0 ]]; then
    printf 'failed to retain pytest log\n' >&2
    exit 74
fi
if [[ "$PYTEST_EXIT_CODE" -ne 0 ]]; then
    printf 'focused CPU validation failed with pytest exit code %s\n' "$PYTEST_EXIT_CODE" >&2
    exit "$PYTEST_EXIT_CODE"
fi

STAGE=complete
