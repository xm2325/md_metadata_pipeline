from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import tempfile
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

from .benchmark import canonical_sha256


SCHEMA_VERSION = "mdmeta.huggingface-model-snapshot.v1"
_COMMIT = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _version(distribution: str) -> str | None:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _snapshot_files(snapshot_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(snapshot_dir.rglob("*")):
        if path.is_symlink():
            raise ValueError(
                f"model snapshot must not contain symlinks: {path.relative_to(snapshot_dir)}"
            )
        if not path.is_file():
            continue
        relative = path.relative_to(snapshot_dir)
        if relative.parts and relative.parts[0] == ".cache":
            continue
        if path.suffix.casefold() in {".bin", ".ckpt", ".pt", ".pth", ".pickle", ".pkl"}:
            raise ValueError(
                f"model snapshot contains a prohibited pickle-capable file: {relative}"
            )
        rows.append(
            {
                "path": relative.as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    if not rows:
        raise ValueError("model snapshot contains no files")
    return rows


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        os.chmod(path, 0o600)
    finally:
        temporary_path.unlink(missing_ok=True)


def stage_model_snapshot(
    *,
    repo_id: str,
    revision: str,
    expected_license: str,
    snapshot_dir: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    """Download one ungated immutable Hugging Face snapshot and hash every model file."""

    if not repo_id.strip():
        raise ValueError("model repository identifier must be non-empty")
    if _COMMIT.fullmatch(revision) is None:
        raise ValueError("model revision must be a full lowercase commit SHA")
    if not expected_license.strip():
        raise ValueError("expected model licence must be non-empty")
    if snapshot_dir.exists():
        raise FileExistsError("model snapshot target must not already exist")
    if manifest_path.exists():
        raise FileExistsError("model manifest target must not already exist")
    snapshot_dir.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(snapshot_dir.parent, 0o700)

    from huggingface_hub import HfApi, snapshot_download

    info = HfApi(token=False).model_info(repo_id=repo_id, revision=revision)
    if info.sha != revision:
        raise ValueError(f"model revision resolved to {info.sha!r}, expected {revision!r}")
    card_data = info.card_data
    observed_license = getattr(card_data, "license", None) if card_data is not None else None
    if not isinstance(observed_license, str):
        raise ValueError("model card does not declare a licence")
    if observed_license.casefold() != expected_license.casefold():
        raise ValueError(
            f"model licence {observed_license!r} does not match {expected_license!r}"
        )
    gated = bool(info.gated)
    if gated:
        raise ValueError("model snapshot must be ungated and downloadable without a token")

    temporary_dir = Path(
        tempfile.mkdtemp(
            dir=snapshot_dir.parent,
            prefix=f".{snapshot_dir.name}.",
            suffix=".staging",
        )
    )
    os.chmod(temporary_dir, 0o700)
    try:
        resolved = Path(
            snapshot_download(
                repo_id=repo_id,
                revision=revision,
                local_dir=temporary_dir,
                token=False,
            )
        ).resolve()
        if resolved != temporary_dir.resolve():
            raise ValueError("model snapshot was downloaded outside the staging directory")
        files = _snapshot_files(temporary_dir)
        weight_files = [row for row in files if row["path"].endswith(".safetensors")]
        if not weight_files:
            raise ValueError("model snapshot does not contain safetensors weights")
        os.replace(temporary_dir, snapshot_dir)
    finally:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)
    core: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "repo_id": repo_id,
        "revision": revision,
        "tokenizer_revision": revision,
        "license": observed_license,
        "gated": False,
        "trust_remote_code": False,
        "staged_at": _utc_now(),
        "runtime": {
            "architecture": platform.machine(),
            "python": platform.python_version(),
            "huggingface_hub": _version("huggingface-hub"),
        },
        "file_count": len(files),
        "total_size_bytes": sum(int(row["size_bytes"]) for row in files),
        "weight_file_count": len(weight_files),
        "weight_size_bytes": sum(int(row["size_bytes"]) for row in weight_files),
        "files": files,
    }
    manifest = {**core, "manifest_sha256": canonical_sha256(core)}
    try:
        _atomic_write(manifest_path, manifest)
    except Exception:
        shutil.rmtree(snapshot_dir, ignore_errors=True)
        raise
    return manifest


def load_and_verify_model_snapshot(
    snapshot_dir: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    """Verify the manifest commitment and every staged file before offline inference."""

    if snapshot_dir.is_symlink() or manifest_path.is_symlink():
        raise ValueError("model snapshot root and manifest must not be symbolic links")
    if not snapshot_dir.is_dir() or not manifest_path.is_file():
        raise FileNotFoundError("model snapshot root or manifest is missing")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    stored = payload.get("manifest_sha256")
    core = {key: value for key, value in payload.items() if key != "manifest_sha256"}
    if not isinstance(stored, str) or _SHA256.fullmatch(stored) is None:
        raise ValueError("model manifest has no valid SHA-256 commitment")
    if stored != canonical_sha256(core):
        raise ValueError("model manifest commitment is invalid")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported model snapshot manifest schema")
    revision = payload.get("revision")
    if not isinstance(revision, str) or _COMMIT.fullmatch(revision) is None:
        raise ValueError("model manifest revision is not immutable")
    tokenizer_revision = payload.get("tokenizer_revision")
    if not isinstance(tokenizer_revision, str) or _COMMIT.fullmatch(tokenizer_revision) is None:
        raise ValueError("model manifest tokenizer revision is not immutable")
    if tokenizer_revision != revision:
        raise ValueError("model and tokenizer revisions must be identical")
    if not isinstance(payload.get("repo_id"), str) or not payload["repo_id"].strip():
        raise ValueError("model manifest repository identifier is empty")
    if not isinstance(payload.get("license"), str) or not payload["license"].strip():
        raise ValueError("model manifest licence is empty")
    if payload.get("gated") is not False or payload.get("trust_remote_code") is not False:
        raise ValueError("model manifest violates the ungated/no-remote-code policy")

    file_rows = payload.get("files")
    if not isinstance(file_rows, list) or not file_rows:
        raise ValueError("model manifest contains no file inventory")
    observed_rows = _snapshot_files(snapshot_dir)
    observed_by_path = {str(row["path"]): row for row in observed_rows}
    expected_paths: set[str] = set()
    for row in file_rows:
        if not isinstance(row, dict):
            raise ValueError("model manifest contains an invalid file row")
        relative = row.get("path")
        digest = row.get("sha256")
        size = row.get("size_bytes")
        if not isinstance(relative, str) or not relative or relative.startswith("/"):
            raise ValueError("model manifest contains an unsafe file path")
        relative_path = Path(relative)
        if ".." in relative_path.parts or relative_path.as_posix() != relative:
            raise ValueError("model manifest contains an unsafe file path")
        if relative in expected_paths:
            raise ValueError("model manifest contains a duplicate file path")
        expected_paths.add(relative)
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise ValueError("model manifest contains an invalid file digest")
        observed = observed_by_path.get(relative)
        if observed is None:
            raise ValueError(f"model snapshot file is missing or is a symlink: {relative}")
        if observed["size_bytes"] != size:
            raise ValueError(f"model snapshot file size mismatch: {relative}")
        if observed["sha256"] != digest:
            raise ValueError(f"model snapshot file digest mismatch: {relative}")

    observed_paths = {row["path"] for row in observed_rows}
    if observed_paths != expected_paths:
        raise ValueError("model snapshot file set differs from its manifest")
    observed_weights = [
        row for row in observed_rows if str(row["path"]).endswith(".safetensors")
    ]
    if not observed_weights:
        raise ValueError("model snapshot does not contain safetensors weights")
    aggregates = {
        "file_count": len(observed_rows),
        "total_size_bytes": sum(int(row["size_bytes"]) for row in observed_rows),
        "weight_file_count": len(observed_weights),
        "weight_size_bytes": sum(int(row["size_bytes"]) for row in observed_weights),
    }
    for field, observed in aggregates.items():
        if payload.get(field) != observed:
            raise ValueError(f"model manifest {field} does not match the snapshot")
    return payload
