from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mdmeta.benchmark import canonical_sha256
from mdmeta.model_snapshot import SCHEMA_VERSION, load_and_verify_model_snapshot


def _write_fake_snapshot(tmp_path: Path) -> tuple[Path, Path, dict]:
    snapshot_dir = tmp_path / "snapshot"
    snapshot_dir.mkdir()
    files = {
        "config.json": b'{"model_type":"test"}\n',
        "model.safetensors": b"tiny-fake-weights",
        "tokenizer.json": b"{}\n",
    }
    rows = []
    for relative, content in files.items():
        path = snapshot_dir / relative
        path.write_bytes(content)
        rows.append(
            {
                "path": relative,
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    rows.sort(key=lambda row: row["path"])
    core = {
        "schema_version": SCHEMA_VERSION,
        "repo_id": "test/tiny-model",
        "revision": "a" * 40,
        "tokenizer_revision": "a" * 40,
        "license": "apache-2.0",
        "gated": False,
        "trust_remote_code": False,
        "staged_at": "2026-07-15T00:00:00Z",
        "runtime": {
            "architecture": "test",
            "python": "test",
            "huggingface_hub": None,
        },
        "file_count": len(rows),
        "total_size_bytes": sum(row["size_bytes"] for row in rows),
        "weight_file_count": 1,
        "weight_size_bytes": len(files["model.safetensors"]),
        "files": rows,
    }
    manifest = {**core, "manifest_sha256": canonical_sha256(core)}
    manifest_path = tmp_path / "model-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return snapshot_dir, manifest_path, manifest


def test_verifies_tiny_offline_snapshot_and_manifest(tmp_path: Path) -> None:
    snapshot_dir, manifest_path, manifest = _write_fake_snapshot(tmp_path)

    observed = load_and_verify_model_snapshot(snapshot_dir, manifest_path)

    assert observed == manifest
    assert observed["manifest_sha256"] == canonical_sha256(
        {key: value for key, value in observed.items() if key != "manifest_sha256"}
    )


def test_rejects_snapshot_file_digest_mismatch(tmp_path: Path) -> None:
    snapshot_dir, manifest_path, _ = _write_fake_snapshot(tmp_path)
    (snapshot_dir / "model.safetensors").write_bytes(b"modified-weights")

    with pytest.raises(ValueError, match="(?:size|digest) mismatch"):
        load_and_verify_model_snapshot(snapshot_dir, manifest_path)


def test_rejects_uncommitted_snapshot_file(tmp_path: Path) -> None:
    snapshot_dir, manifest_path, _ = _write_fake_snapshot(tmp_path)
    (snapshot_dir / "unexpected.txt").write_text("not in manifest", encoding="utf-8")

    with pytest.raises(ValueError, match="file set differs"):
        load_and_verify_model_snapshot(snapshot_dir, manifest_path)


def test_rejects_committed_pickle_capable_weight(tmp_path: Path) -> None:
    snapshot_dir, manifest_path, manifest = _write_fake_snapshot(tmp_path)
    pickle_path = snapshot_dir / "pytorch_model.bin"
    pickle_path.write_bytes(b"not-real-pickle-weights")
    row = {
        "path": pickle_path.name,
        "size_bytes": pickle_path.stat().st_size,
        "sha256": hashlib.sha256(pickle_path.read_bytes()).hexdigest(),
    }
    core = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    core["files"] = sorted([*core["files"], row], key=lambda item: item["path"])
    core["file_count"] += 1
    core["total_size_bytes"] += row["size_bytes"]
    manifest_path.write_text(
        json.dumps({**core, "manifest_sha256": canonical_sha256(core)}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="prohibited pickle-capable"):
        load_and_verify_model_snapshot(snapshot_dir, manifest_path)


def test_rejects_manifest_aggregate_mismatch(tmp_path: Path) -> None:
    snapshot_dir, manifest_path, manifest = _write_fake_snapshot(tmp_path)
    core = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    core["weight_size_bytes"] += 1
    manifest_path.write_text(
        json.dumps({**core, "manifest_sha256": canonical_sha256(core)}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="weight_size_bytes"):
        load_and_verify_model_snapshot(snapshot_dir, manifest_path)


def test_rejects_committed_snapshot_without_safetensors(tmp_path: Path) -> None:
    snapshot_dir, manifest_path, manifest = _write_fake_snapshot(tmp_path)
    (snapshot_dir / "model.safetensors").unlink()
    core = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    core["files"] = [
        row for row in core["files"] if row["path"] != "model.safetensors"
    ]
    core["file_count"] = len(core["files"])
    core["total_size_bytes"] = sum(row["size_bytes"] for row in core["files"])
    core["weight_file_count"] = 0
    core["weight_size_bytes"] = 0
    manifest_path.write_text(
        json.dumps({**core, "manifest_sha256": canonical_sha256(core)}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="safetensors"):
        load_and_verify_model_snapshot(snapshot_dir, manifest_path)


def test_rejects_symlinked_manifest(tmp_path: Path) -> None:
    snapshot_dir, manifest_path, _ = _write_fake_snapshot(tmp_path)
    manifest_link = tmp_path / "model-manifest-link.json"
    manifest_link.symlink_to(manifest_path)

    with pytest.raises(ValueError, match="symbolic links"):
        load_and_verify_model_snapshot(snapshot_dir, manifest_link)
