from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Annotated, Iterator, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from . import __version__
from .storage import SCHEMA_VERSION
from .verify import RECORD_SCHEMA_VERSION, sha256_file, verify_database


RELEASE_MANIFEST_SCHEMA = "mdmeta-dataset-release-v1"
RELEASE_MANIFEST_NAME = "release-manifest.json"
DATABASE_MANIFEST_NAME = "database-manifest.json"
CHECKSUMS_NAME = "SHA256SUMS.txt"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_SHA256_RE = re.compile(_SHA256_PATTERN)
_GIT_COMMIT_PATTERN = r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$"
_STABLE_SEMVER_RE = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$"
)
_PLACEHOLDERS = {"n/a", "noassertion", "none", "tbd", "todo", "unknown"}
Sha256 = Annotated[str, Field(pattern=_SHA256_PATTERN)]


def _safe_relative_path(value: str) -> str:
    if not value or any(ord(character) < 32 for character in value):
        raise ValueError("bundle paths must be non-empty and contain no control characters")
    if "\\" in value:
        raise ValueError("bundle paths must use POSIX separators")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("bundle paths must remain inside the bundle")
    normalized = path.as_posix()
    if normalized in {".", ""} or normalized != value:
        raise ValueError("bundle paths must be normalized relative POSIX paths")
    return normalized


def _non_empty(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must be non-empty")
    return normalized


def _dataset_identifier(value: str) -> str:
    normalized = _non_empty(value, "dataset_id")
    parsed = urlsplit(normalized)
    if not parsed.scheme or (parsed.scheme in {"http", "https"} and not parsed.netloc):
        raise ValueError("dataset_id must be a canonical URI")
    return normalized


class BundleFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    byte_size: StrictInt = Field(ge=0)
    sha256: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _safe_relative_path(value)


class DatabaseContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    verification_manifest_path: str
    byte_size: StrictInt = Field(ge=0)
    sha256: str = Field(pattern=_SHA256_PATTERN)
    article_count: StrictInt = Field(ge=0)
    schema_version: Literal[1] = SCHEMA_VERSION
    record_schema: Literal["integrated-md-record-v1"] = RECORD_SCHEMA_VERSION

    @field_validator("path", "verification_manifest_path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _safe_relative_path(value)


class ReleaseProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package_version: str = Field(pattern=_STABLE_SEMVER_RE.pattern)
    git_commit: str = Field(pattern=_GIT_COMMIT_PATTERN)
    workflow_run_url: str
    workflow_run_id: StrictInt = Field(ge=1)
    workflow_run_attempt: StrictInt = Field(ge=1)
    dependency_lock_sha256: Sha256
    source_manifest_sha256: Sha256 | None

    @field_validator("package_version", mode="before")
    @classmethod
    def validate_package_version(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("package_version must be a string")
        normalized = _non_empty(value, "package_version")
        if _STABLE_SEMVER_RE.fullmatch(normalized) is None:
            raise ValueError("package_version must be stable MAJOR.MINOR.PATCH SemVer")
        return normalized

    @field_validator("workflow_run_url")
    @classmethod
    def validate_workflow_url(cls, value: str) -> str:
        normalized = _non_empty(value, "workflow_run_url")
        parsed = urlsplit(normalized)
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("workflow_run_url must be an absolute HTTPS URL")
        return normalized

    @model_validator(mode="after")
    def validate_workflow_identity(self) -> "ReleaseProvenance":
        expected_suffix = f"/actions/runs/{self.workflow_run_id}"
        if not urlsplit(self.workflow_run_url).path.rstrip("/").endswith(expected_suffix):
            raise ValueError("workflow_run_url must identify workflow_run_id")
        return self


class ReleaseManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_schema: Literal["mdmeta-dataset-release-v1"] = RELEASE_MANIFEST_SCHEMA
    dataset_id: str
    dataset_version: str
    title: str
    license: str
    creators: list[str] = Field(min_length=1)
    publisher: str
    created_at: datetime
    completion_state: Literal["complete"] = "complete"
    database: DatabaseContract
    files: list[BundleFile] = Field(min_length=2)
    provenance: ReleaseProvenance
    bundle_sha256: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("dataset_id", "dataset_version", "title", "license", "publisher")
    @classmethod
    def validate_non_empty(cls, value: str, info) -> str:
        normalized = _non_empty(value, info.field_name)
        if info.field_name == "dataset_id":
            return _dataset_identifier(normalized)
        if normalized.casefold() in _PLACEHOLDERS:
            raise ValueError(f"{info.field_name} must not be a placeholder")
        return normalized

    @field_validator("creators")
    @classmethod
    def validate_creators(cls, values: list[str]) -> list[str]:
        normalized = [_non_empty(value, "creator") for value in values]
        if any(value.casefold() in _PLACEHOLDERS for value in normalized):
            raise ValueError("creators must not contain placeholders")
        if len(set(normalized)) != len(normalized):
            raise ValueError("creators must not contain duplicates")
        return normalized

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value.astimezone(timezone.utc)

    @field_validator("created_at", mode="before")
    @classmethod
    def validate_created_at_input(cls, value: object) -> object:
        if not isinstance(value, (str, datetime)):
            raise ValueError("created_at must be an ISO 8601 string or datetime")
        return value

    @model_validator(mode="after")
    def validate_inventory(self) -> "ReleaseManifest":
        paths = [item.path for item in self.files]
        if len(set(paths)) != len(paths):
            raise ValueError("release manifest contains duplicate file paths")
        if paths != sorted(paths):
            raise ValueError("release manifest file inventory must be sorted by path")
        reserved = {RELEASE_MANIFEST_NAME, CHECKSUMS_NAME}
        if reserved.intersection(paths):
            raise ValueError("generated release metadata must not appear as payload files")
        if self.database.path == self.database.verification_manifest_path:
            raise ValueError("database and verification manifest paths must differ")
        sidecars = {
            f"{self.database.path}-wal",
            f"{self.database.path}-shm",
            f"{self.database.path}-journal",
        }
        if sidecars.intersection(paths):
            raise ValueError("SQLite sidecars must not be included in a release bundle")
        required = {self.database.path, self.database.verification_manifest_path}
        if not required.issubset(paths):
            raise ValueError("database files must be present in the bundle inventory")
        return self


def _canonical_json(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _manifest_core(manifest: ReleaseManifest) -> dict[str, object]:
    return manifest.model_dump(mode="json", exclude={"bundle_sha256"})


def _bundle_digest(manifest: ReleaseManifest) -> str:
    return hashlib.sha256(_canonical_json(_manifest_core(manifest))).hexdigest()


def _object_without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON contains duplicate key: {key}")
        result[key] = value
    return result


def _load_json(path: Path) -> object:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_object_without_duplicate_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON file: {path.name}") from exc


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write(path: Path, content: bytes) -> None:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _fsync_tree(root: Path) -> None:
    scanned = _scan_bundle(root)
    for path in scanned.values():
        with path.open("rb") as handle:
            os.fsync(handle.fileno())
    directories = sorted(
        (path for path in root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for directory in directories:
        _fsync_directory(directory)
    _fsync_directory(root)


def _scan_bundle(root: Path) -> dict[str, Path]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("bundle root must be a real directory, not a symlink")
    files: dict[str, Path] = {}
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in directory_names:
            candidate = base / name
            if candidate.is_symlink():
                raise ValueError(f"bundle contains a symlink: {candidate.relative_to(root)}")
            if not candidate.is_dir():
                raise ValueError(f"bundle contains a special path: {candidate.relative_to(root)}")
        for name in file_names:
            candidate = base / name
            relative = _safe_relative_path(candidate.relative_to(root).as_posix())
            if candidate.is_symlink():
                raise ValueError(f"bundle contains a symlink: {relative}")
            if not candidate.is_file():
                raise ValueError(f"bundle contains a special file: {relative}")
            files[relative] = candidate
    return files


def _validate_database_manifest(
    payload: object,
    report: dict[str, object],
) -> None:
    if not isinstance(payload, dict) or payload.get("valid") is not True:
        raise ValueError("database verification manifest is not valid")
    expected = {
        "sha256": report["sha256"],
        "byte_size": report["byte_size"],
        "article_count": report["article_count"],
        "record_schema": report["record_schema"],
    }
    mismatches = sorted(key for key, value in expected.items() if payload.get(key) != value)
    integrity = payload.get("integrity")
    if integrity != report["integrity"]:
        mismatches.append("integrity")
    record_validation = payload.get("record_validation")
    if record_validation != report["record_validation"]:
        mismatches.append("record_validation")
    if mismatches:
        raise ValueError(
            "database verification manifest does not match the snapshot: "
            + ", ".join(sorted(set(mismatches)))
        )


def _write_or_validate_database_manifest(path: Path, report: dict[str, object]) -> None:
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            raise ValueError("database verification manifest must be a regular file")
        _validate_database_manifest(_load_json(path), report)
        return
    rendered = json.dumps(report, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    _atomic_write(path, rendered)


def create_release_bundle(
    bundle_dir: str | Path,
    *,
    dataset_id: str,
    dataset_version: str,
    title: str,
    license: str,
    creators: list[str],
    publisher: str,
    database_path: str = "records.sqlite",
    database_manifest_path: str = DATABASE_MANIFEST_NAME,
    created_at: datetime,
    provenance: ReleaseProvenance,
) -> ReleaseManifest:
    """Seal a finalized database and its payload as a strict immutable bundle."""

    root = Path(bundle_dir)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("bundle root must be a real directory")
    _scan_bundle(root)
    database_relative = _safe_relative_path(database_path)
    verification_relative = _safe_relative_path(database_manifest_path)
    if database_relative == verification_relative:
        raise ValueError("database and verification manifest paths must differ")
    if database_relative in {RELEASE_MANIFEST_NAME, CHECKSUMS_NAME}:
        raise ValueError("database path conflicts with generated release metadata")
    if verification_relative in {RELEASE_MANIFEST_NAME, CHECKSUMS_NAME}:
        raise ValueError("database manifest path conflicts with generated release metadata")
    for generated in (root / RELEASE_MANIFEST_NAME, root / CHECKSUMS_NAME):
        if generated.exists() or generated.is_symlink():
            raise FileExistsError(generated)

    for field, value in (
        ("dataset_id", dataset_id),
        ("dataset_version", dataset_version),
        ("title", title),
        ("license", license),
        ("publisher", publisher),
    ):
        _non_empty(value, field)
    _dataset_identifier(dataset_id)
    if not creators:
        raise ValueError("creators must not be empty")
    normalized_creators = [_non_empty(value, "creator") for value in creators]
    if len(set(normalized_creators)) != len(normalized_creators):
        raise ValueError("creators must not contain duplicates")
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ValueError("created_at must include a timezone")
    provenance = ReleaseProvenance.model_validate(provenance)

    database = root / database_relative
    if database.is_symlink() or not database.is_file():
        raise ValueError("bundle database must be a regular file")
    for sidecar in (
        Path(f"{database}-wal"),
        Path(f"{database}-shm"),
        Path(f"{database}-journal"),
    ):
        if sidecar.exists() or sidecar.is_symlink():
            raise ValueError("finalized bundle must not contain SQLite sidecars")
    report = verify_database(database)
    if not report["valid"]:
        raise ValueError("bundle database is not a valid finalized snapshot")
    database_manifest = root / verification_relative
    database_manifest.parent.mkdir(parents=True, exist_ok=True)
    database_manifest_preexisting = database_manifest.exists() or database_manifest.is_symlink()
    try:
        _write_or_validate_database_manifest(database_manifest, report)

        scanned = _scan_bundle(root)
        payload_paths = sorted(
            path for path in scanned if path not in {RELEASE_MANIFEST_NAME, CHECKSUMS_NAME}
        )
        files = [
            BundleFile(
                path=path,
                byte_size=scanned[path].stat().st_size,
                sha256=sha256_file(scanned[path]),
            )
            for path in payload_paths
        ]
        manifest = ReleaseManifest(
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            title=title,
            license=license,
            creators=creators,
            publisher=publisher,
            created_at=created_at,
            database=DatabaseContract(
                path=database_relative,
                verification_manifest_path=verification_relative,
                byte_size=int(report["byte_size"]),
                sha256=str(report["sha256"]),
                article_count=int(report["article_count"]),
                schema_version=SCHEMA_VERSION,
                record_schema=RECORD_SCHEMA_VERSION,
            ),
            files=files,
            provenance=provenance,
            bundle_sha256="0" * 64,
        )
        manifest = manifest.model_copy(update={"bundle_sha256": _bundle_digest(manifest)})
        rendered_manifest = (
            json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True).encode(
                "utf-8"
            )
            + b"\n"
        )
        _atomic_write(root / RELEASE_MANIFEST_NAME, rendered_manifest)

        checksum_rows = [f"{item.sha256}  {item.path}" for item in manifest.files]
        checksum_rows.append(
            f"{sha256_file(root / RELEASE_MANIFEST_NAME)}  {RELEASE_MANIFEST_NAME}"
        )
        _atomic_write(
            root / CHECKSUMS_NAME,
            ("\n".join(sorted(checksum_rows)) + "\n").encode("utf-8"),
        )
        verify_release_bundle(root)
        return manifest
    except Exception:
        (root / RELEASE_MANIFEST_NAME).unlink(missing_ok=True)
        (root / CHECKSUMS_NAME).unlink(missing_ok=True)
        if not database_manifest_preexisting:
            database_manifest.unlink(missing_ok=True)
        raise


def _read_checksums(path: Path) -> dict[str, str]:
    checksums: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ValueError("invalid checksum file") from exc
    if not lines:
        raise ValueError("checksum file is empty")
    for line in lines:
        digest, separator, relative = line.partition("  ")
        if separator != "  " or _SHA256_RE.fullmatch(digest) is None:
            raise ValueError("checksum file contains a malformed row")
        relative = _safe_relative_path(relative)
        if relative in checksums:
            raise ValueError("checksum file contains a duplicate path")
        checksums[relative] = digest
    return checksums


def verify_release_bundle(bundle_dir: str | Path) -> dict[str, object]:
    """Strictly verify inventory, hashes, semantic records and database contract."""

    root = Path(bundle_dir)
    scanned = _scan_bundle(root)
    required_metadata = {RELEASE_MANIFEST_NAME, CHECKSUMS_NAME}
    missing_metadata = sorted(required_metadata - scanned.keys())
    if missing_metadata:
        raise ValueError(f"bundle is missing release metadata: {missing_metadata}")

    payload = _load_json(scanned[RELEASE_MANIFEST_NAME])
    try:
        manifest = ReleaseManifest.model_validate(payload)
    except ValueError as exc:
        raise ValueError("release manifest does not satisfy its schema") from exc
    expected_digest = _bundle_digest(manifest)
    if manifest.bundle_sha256 != expected_digest:
        raise ValueError("release manifest bundle digest does not match its canonical core")

    expected_files = {item.path for item in manifest.files} | required_metadata
    actual_files = set(scanned)
    missing = sorted(expected_files - actual_files)
    extra = sorted(actual_files - expected_files)
    if missing:
        raise ValueError(f"bundle is missing inventory files: {missing}")
    if extra:
        raise ValueError(f"bundle contains files absent from the inventory: {extra}")

    for item in manifest.files:
        path = scanned[item.path]
        if path.stat().st_size != item.byte_size:
            raise ValueError(f"bundle file size mismatch: {item.path}")
        if sha256_file(path) != item.sha256:
            raise ValueError(f"bundle file hash mismatch: {item.path}")

    checksums = _read_checksums(scanned[CHECKSUMS_NAME])
    expected_checksums = {item.path: item.sha256 for item in manifest.files}
    expected_checksums[RELEASE_MANIFEST_NAME] = sha256_file(scanned[RELEASE_MANIFEST_NAME])
    if checksums.keys() != expected_checksums.keys():
        raise ValueError("checksum inventory does not exactly match the release manifest")
    for path, digest in expected_checksums.items():
        if checksums[path] != digest:
            raise ValueError(f"checksum digest mismatch: {path}")

    database = scanned[manifest.database.path]
    report = verify_database(database, expected_articles=manifest.database.article_count)
    if not report["valid"]:
        raise ValueError("bundle database failed verification")
    database_mismatches = sorted(
        key
        for key, actual, expected in (
            ("byte_size", report["byte_size"], manifest.database.byte_size),
            ("sha256", report["sha256"], manifest.database.sha256),
            (
                "schema_version",
                report["integrity"]["schema_version"],
                manifest.database.schema_version,
            ),
            ("record_schema", report["record_schema"], manifest.database.record_schema),
        )
        if actual != expected
    )
    if database_mismatches:
        raise ValueError(
            "database does not match release contract: " + ", ".join(database_mismatches)
        )
    _validate_database_manifest(
        _load_json(scanned[manifest.database.verification_manifest_path]), report
    )
    return {
        "valid": True,
        "manifest_schema": manifest.manifest_schema,
        "dataset_id": manifest.dataset_id,
        "dataset_version": manifest.dataset_version,
        "bundle_sha256": manifest.bundle_sha256,
        "database_sha256": manifest.database.sha256,
        "article_count": manifest.database.article_count,
        "file_count": len(manifest.files),
    }


def _prepare_release_root(root: Path) -> Path:
    if root.is_symlink():
        raise ValueError("release root must not be a symlink")
    root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise ValueError("release root must be a directory")
    releases = root / "releases"
    if releases.is_symlink():
        raise ValueError("releases directory must not be a symlink")
    releases.mkdir(exist_ok=True)
    if not releases.is_dir():
        raise ValueError("releases path must be a directory")
    return releases


@contextmanager
def _release_lock(root: Path) -> Iterator[None]:
    lock = root / ".release.lock"
    if lock.is_symlink():
        raise ValueError("release lock must not be a symlink")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lock, flags, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def stage_release(bundle_dir: str | Path, release_root: str | Path) -> Path:
    """Copy a verified bundle into its immutable digest-addressed release directory."""

    source = Path(bundle_dir)
    report = verify_release_bundle(source)
    release_id = str(report["bundle_sha256"])
    root = Path(release_root)
    source_resolved = source.resolve()
    root_resolved = root.resolve()
    if root_resolved == source_resolved or source_resolved in root_resolved.parents:
        raise ValueError("release root must not be inside the source bundle")
    releases = _prepare_release_root(root)
    with _release_lock(root):
        target = releases / release_id
        if target.exists() or target.is_symlink():
            if target.is_symlink() or not target.is_dir():
                raise ValueError("release target is not an immutable directory")
            existing = verify_release_bundle(target)
            if existing["bundle_sha256"] != release_id:
                raise ValueError("existing release directory has the wrong digest")
            return target

        temporary = releases / f".{release_id}.{uuid.uuid4().hex}.tmp"
        try:
            shutil.copytree(source, temporary, symlinks=True)
            copied = verify_release_bundle(temporary)
            if copied["bundle_sha256"] != release_id:
                raise ValueError("staged release digest changed during copy")
            _fsync_tree(temporary)
            if target.exists() or target.is_symlink():
                raise FileExistsError(target)
            os.rename(temporary, target)
            _fsync_directory(releases)
        except Exception:
            if temporary.is_dir() and not temporary.is_symlink():
                shutil.rmtree(temporary)
            else:
                temporary.unlink(missing_ok=True)
            raise
    return target


def current_release(release_root: str | Path) -> str | None:
    root = Path(release_root)
    current = root / "current"
    if not current.exists() and not current.is_symlink():
        return None
    if not current.is_symlink():
        raise ValueError("current release pointer must be a symlink")
    target = os.readlink(current)
    parts = PurePosixPath(target).parts
    if len(parts) != 2 or parts[0] != "releases" or _SHA256_RE.fullmatch(parts[1]) is None:
        raise ValueError("current release pointer has an unsafe target")
    return parts[1]


def activate_release(release_root: str | Path, release_id: str) -> dict[str, str | None]:
    """Atomically switch ``current`` to an already staged and verified release."""

    if _SHA256_RE.fullmatch(release_id) is None:
        raise ValueError("release id must be a SHA-256 digest")
    root = Path(release_root)
    releases = _prepare_release_root(root)
    with _release_lock(root):
        target = releases / release_id
        if target.is_symlink() or not target.is_dir():
            raise FileNotFoundError(target)
        verified = verify_release_bundle(target)
        if verified["bundle_sha256"] != release_id:
            raise ValueError("release directory name does not match its verified digest")
        previous = current_release(root)
        if previous == release_id:
            return {"current": release_id, "previous": previous}
        temporary = root / f".current.{uuid.uuid4().hex}.tmp"
        try:
            os.symlink(f"releases/{release_id}", temporary, target_is_directory=True)
            os.replace(temporary, root / "current")
            _fsync_directory(root)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    return {"current": release_id, "previous": previous}


def rollback_release(release_root: str | Path, release_id: str) -> dict[str, str | None]:
    """Rollback by atomically activating a specified previously staged release."""

    return activate_release(release_root, release_id)


def export_release_schema(path: str | Path, *, check: bool = False) -> Path:
    """Write or compare the deterministic JSON Schema for the release manifest."""

    destination = Path(path)
    rendered = (
        json.dumps(ReleaseManifest.model_json_schema(), indent=2, sort_keys=True).encode("utf-8")
        + b"\n"
    )
    if check:
        if not destination.is_file() or destination.read_bytes() != rendered:
            raise ValueError(f"release schema artifact is out of date: {destination}")
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(destination, rendered)
    return destination


def _datetime_argument(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timestamp must be ISO 8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone")
    return parsed


def _provenance_from_args(args: argparse.Namespace) -> ReleaseProvenance:
    dependency_lock = Path(args.dependency_lock)
    if dependency_lock.is_symlink() or not dependency_lock.is_file():
        raise ValueError("dependency lock must be a regular file")
    source_manifest = Path(args.source_manifest) if args.source_manifest is not None else None
    if source_manifest is not None and (
        source_manifest.is_symlink() or not source_manifest.is_file()
    ):
        raise ValueError("source manifest must be a regular file")
    return ReleaseProvenance(
        package_version=__version__,
        git_commit=args.git_commit,
        workflow_run_url=args.workflow_run_url,
        workflow_run_id=args.workflow_run_id,
        workflow_run_attempt=args.workflow_run_attempt,
        dependency_lock_sha256=sha256_file(dependency_lock),
        source_manifest_sha256=(
            sha256_file(source_manifest) if source_manifest is not None else None
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Create, verify and activate MD metadata releases")
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create", help="seal a finalized dataset bundle")
    create.add_argument("--bundle-dir", type=Path, required=True)
    create.add_argument("--dataset-id", required=True)
    create.add_argument("--dataset-version", required=True)
    create.add_argument("--title", required=True)
    create.add_argument("--license", required=True)
    create.add_argument("--creator", action="append", dest="creators", required=True)
    create.add_argument("--publisher", required=True)
    create.add_argument("--database-path", default="records.sqlite")
    create.add_argument("--database-manifest-path", default=DATABASE_MANIFEST_NAME)
    create.add_argument("--created-at", type=_datetime_argument, required=True)
    create.add_argument("--git-commit", required=True)
    create.add_argument("--workflow-run-url", required=True)
    create.add_argument("--workflow-run-id", type=int, required=True)
    create.add_argument("--workflow-run-attempt", type=int, required=True)
    create.add_argument("--dependency-lock", type=Path, required=True)
    create.add_argument("--source-manifest", type=Path)

    verify = commands.add_parser("verify", help="verify a sealed dataset bundle")
    verify.add_argument("--bundle-dir", type=Path, required=True)

    schema = commands.add_parser("schema", help="export the release-manifest JSON Schema")
    schema.add_argument("--output", type=Path, required=True)
    schema.add_argument("--check", action="store_true")

    stage = commands.add_parser("stage", help="stage a verified immutable release")
    stage.add_argument("--bundle-dir", type=Path, required=True)
    stage.add_argument("--release-root", type=Path, required=True)

    for name in ("activate", "rollback"):
        command = commands.add_parser(name, help=f"{name} a staged release")
        command.add_argument("--release-root", type=Path, required=True)
        command.add_argument("--release-id", required=True)

    args = parser.parse_args()
    if args.command == "create":
        result: object = create_release_bundle(
            args.bundle_dir,
            dataset_id=args.dataset_id,
            dataset_version=args.dataset_version,
            title=args.title,
            license=args.license,
            creators=args.creators,
            publisher=args.publisher,
            database_path=args.database_path,
            database_manifest_path=args.database_manifest_path,
            created_at=args.created_at,
            provenance=_provenance_from_args(args),
        ).model_dump(mode="json")
    elif args.command == "verify":
        result = verify_release_bundle(args.bundle_dir)
    elif args.command == "schema":
        result = {"schema": str(export_release_schema(args.output, check=args.check))}
    elif args.command == "stage":
        result = {"release": str(stage_release(args.bundle_dir, args.release_root))}
    elif args.command == "activate":
        result = activate_release(args.release_root, args.release_id)
    else:
        result = rollback_release(args.release_root, args.release_id)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
