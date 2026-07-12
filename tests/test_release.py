from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mdmeta.integration import ArticleMetadata, IntegratedMDRecord, ProvenanceRecord
from mdmeta.release import (
    CHECKSUMS_NAME,
    RELEASE_MANIFEST_NAME,
    ReleaseManifest,
    ReleaseProvenance,
    activate_release,
    create_release_bundle,
    current_release,
    export_release_schema,
    rollback_release,
    stage_release,
    verify_release_bundle,
)
from mdmeta.storage import SQLiteRecordStore


CREATED_AT = datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)
PROVENANCE = ReleaseProvenance(
    package_version="0.11.0",
    git_commit="a" * 40,
    workflow_run_url="https://github.com/example/project/actions/runs/123",
    workflow_run_id=123,
    workflow_run_attempt=1,
    dependency_lock_sha256="c" * 64,
    source_manifest_sha256="b" * 64,
)


def _record(document_id: str) -> IntegratedMDRecord:
    source = f"fixture:{document_id}"
    return IntegratedMDRecord(
        article=ArticleMetadata(
            document_id=document_id,
            title=f"Article {document_id}",
            source_uri=f"https://example.org/articles/{document_id}",
            full_text_sha256=hashlib.sha256(source.encode("utf-8")).hexdigest(),
        ),
        literature_facts=[],
        protocol_events=[],
        pdb_validations=[],
        mapping_discoveries=[],
        uniprot_validations=[],
        mapping_validations=[],
        residue_mappings=[],
        provenance=ProvenanceRecord(),
        completeness={"fixture": "complete"},
    )


def _prepare_unsealed_bundle(root: Path, document_ids: list[str]) -> Path:
    root.mkdir(parents=True)
    store = SQLiteRecordStore(root / "records.sqlite")
    for document_id in document_ids:
        store.write(_record(document_id))
    store.checkpoint()
    (root / "summary.json").write_text(
        json.dumps({"document_ids": document_ids}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return root


def _seal(root: Path, document_ids: list[str], version: str):
    _prepare_unsealed_bundle(root, document_ids)
    return create_release_bundle(
        root,
        dataset_id="https://example.org/datasets/mdmeta-test",
        dataset_version=version,
        title="MD metadata test dataset",
        license="LicenseRef-Test-Only",
        creators=["Test Creator"],
        publisher="Test Publisher",
        created_at=CREATED_AT,
        provenance=PROVENANCE,
    )


def test_create_and_verify_strict_release_bundle(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    manifest = _seal(root, ["DOC1"], "test-v1")

    assert isinstance(manifest, ReleaseManifest)
    assert manifest.dataset_id == "https://example.org/datasets/mdmeta-test"
    assert manifest.license == "LicenseRef-Test-Only"
    assert manifest.provenance.git_commit == "a" * 40
    assert manifest.database.article_count == 1
    assert manifest.database.record_schema == "integrated-md-record-v1"
    assert {item.path for item in manifest.files} == {
        "database-manifest.json",
        "records.sqlite",
        "summary.json",
    }
    report = verify_release_bundle(root)
    assert report["valid"] is True
    assert report["bundle_sha256"] == manifest.bundle_sha256
    assert len(manifest.bundle_sha256) == 64

    database_manifest = json.loads((root / "database-manifest.json").read_text())
    assert database_manifest["record_validation"]["valid"] is True
    assert database_manifest["sha256"] == manifest.database.sha256


def test_release_metadata_and_provenance_are_explicit(tmp_path: Path) -> None:
    root = _prepare_unsealed_bundle(tmp_path / "bundle", ["DOC1"])
    with pytest.raises(ValueError, match="license must be non-empty"):
        create_release_bundle(
            root,
            dataset_id="dataset:test",
            dataset_version="v1",
            title="Test",
            license=" ",
            creators=["Test Creator"],
            publisher="Test Publisher",
            created_at=CREATED_AT,
            provenance=PROVENANCE,
        )
    assert not (root / "database-manifest.json").exists()
    assert not (root / RELEASE_MANIFEST_NAME).exists()

    with pytest.raises(ValueError, match="license must not be a placeholder"):
        create_release_bundle(
            root,
            dataset_id="dataset:test",
            dataset_version="v1",
            title="Test",
            license="unknown",
            creators=["Test Creator"],
            publisher="Test Publisher",
            created_at=CREATED_AT,
            provenance=PROVENANCE,
        )
    assert not (root / "database-manifest.json").exists()
    assert not (root / RELEASE_MANIFEST_NAME).exists()
    assert not (root / CHECKSUMS_NAME).exists()

    with pytest.raises(ValueError, match="git_commit"):
        ReleaseProvenance(
            package_version="0.10.0",
            git_commit="short",
            workflow_run_url="https://github.com/example/project/actions/runs/123",
            workflow_run_id=123,
            workflow_run_attempt=1,
            dependency_lock_sha256="c" * 64,
            source_manifest_sha256=None,
        )

    with pytest.raises(ValueError, match="stable MAJOR.MINOR.PATCH"):
        ReleaseProvenance(
            package_version="0.11.0rc1",
            git_commit="a" * 40,
            workflow_run_url="https://github.com/example/project/actions/runs/123",
            workflow_run_id=123,
            workflow_run_attempt=1,
            dependency_lock_sha256="c" * 64,
            source_manifest_sha256=None,
        )

    with pytest.raises(ValueError, match="must identify workflow_run_id"):
        ReleaseProvenance(
            package_version="0.11.0",
            git_commit="a" * 40,
            workflow_run_url="https://github.com/example/project/actions/runs/456",
            workflow_run_id=123,
            workflow_run_attempt=1,
            dependency_lock_sha256="c" * 64,
            source_manifest_sha256=None,
        )

    with pytest.raises(ValueError, match="integer"):
        ReleaseProvenance(
            package_version="0.11.0",
            git_commit="a" * 40,
            workflow_run_url="https://github.com/example/project/actions/runs/123",
            workflow_run_id="123",  # type: ignore[arg-type]
            workflow_run_attempt=1,
            dependency_lock_sha256="c" * 64,
            source_manifest_sha256=None,
        )


def test_release_manifest_does_not_coerce_numeric_timestamp(tmp_path: Path) -> None:
    manifest = _seal(tmp_path / "bundle", ["DOC1"], "test-v1")
    payload = manifest.model_dump(mode="json")
    payload["created_at"] = 0

    with pytest.raises(ValueError, match="ISO 8601 string or datetime"):
        ReleaseManifest.model_validate(payload)


@pytest.mark.parametrize("failure", ["tampered", "extra", "missing", "symlink"])
def test_bundle_rejects_inventory_and_content_tampering(
    tmp_path: Path, failure: str
) -> None:
    original = tmp_path / "original"
    _seal(original, ["DOC1"], "test-v1")
    bundle = tmp_path / failure
    shutil.copytree(original, bundle)

    if failure == "tampered":
        (bundle / "summary.json").write_text("tampered\n", encoding="utf-8")
    elif failure == "extra":
        (bundle / "not-in-manifest.txt").write_text("extra", encoding="utf-8")
    elif failure == "missing":
        (bundle / "summary.json").unlink()
    else:
        outside = tmp_path / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        (bundle / "summary.json").unlink()
        (bundle / "summary.json").symlink_to(outside)

    with pytest.raises(ValueError):
        verify_release_bundle(bundle)


def test_bundle_rejects_duplicate_and_unsafe_manifest_paths(tmp_path: Path) -> None:
    original = tmp_path / "original"
    _seal(original, ["DOC1"], "test-v1")

    duplicate = tmp_path / "duplicate"
    shutil.copytree(original, duplicate)
    payload = json.loads((duplicate / RELEASE_MANIFEST_NAME).read_text())
    payload["files"].append(payload["files"][0])
    (duplicate / RELEASE_MANIFEST_NAME).write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="does not satisfy"):
        verify_release_bundle(duplicate)

    traversal = tmp_path / "traversal"
    shutil.copytree(original, traversal)
    payload = json.loads((traversal / RELEASE_MANIFEST_NAME).read_text())
    payload["files"][0]["path"] = "../escape"
    (traversal / RELEASE_MANIFEST_NAME).write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="does not satisfy"):
        verify_release_bundle(traversal)

    duplicate_checksum = tmp_path / "duplicate-checksum"
    shutil.copytree(original, duplicate_checksum)
    checksums = (duplicate_checksum / CHECKSUMS_NAME).read_text(encoding="utf-8")
    first = checksums.splitlines()[0]
    (duplicate_checksum / CHECKSUMS_NAME).write_text(
        checksums + first + "\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="duplicate path"):
        verify_release_bundle(duplicate_checksum)


def test_bundle_creation_rejects_symlink_and_invalid_record_database(tmp_path: Path) -> None:
    symlink_bundle = _prepare_unsealed_bundle(tmp_path / "symlink", ["DOC1"])
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (symlink_bundle / "linked.txt").symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        create_release_bundle(
            symlink_bundle,
            dataset_id="dataset:test",
            dataset_version="v1",
            title="Test",
            license="LicenseRef-Test-Only",
            creators=["Test Creator"],
            publisher="Test Publisher",
            created_at=CREATED_AT,
            provenance=PROVENANCE,
        )

    invalid = _prepare_unsealed_bundle(tmp_path / "invalid", ["DOC1"])
    with closing(sqlite3.connect(invalid / "records.sqlite")) as connection:
        connection.execute("UPDATE articles SET record_json = '{'")
        connection.commit()
    with pytest.raises(ValueError, match="not a valid finalized snapshot"):
        create_release_bundle(
            invalid,
            dataset_id="dataset:test",
            dataset_version="v1",
            title="Test",
            license="LicenseRef-Test-Only",
            creators=["Test Creator"],
            publisher="Test Publisher",
            created_at=CREATED_AT,
            provenance=PROVENANCE,
        )

    mismatched = _prepare_unsealed_bundle(tmp_path / "mismatched-manifest", ["DOC1"])
    (mismatched / "database-manifest.json").write_text(
        json.dumps(
            {
                "valid": True,
                "sha256": "0" * 64,
                "byte_size": 0,
                "article_count": 99,
                "record_schema": "integrated-md-record-v1",
                "integrity": {"schema_version": 1},
                "record_validation": {"checked": 99, "valid": True, "errors": []},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="does not match the snapshot"):
        create_release_bundle(
            mismatched,
            dataset_id="dataset:test",
            dataset_version="v1",
            title="Test",
            license="LicenseRef-Test-Only",
            creators=["Test Creator"],
            publisher="Test Publisher",
            created_at=CREATED_AT,
            provenance=PROVENANCE,
        )


def test_schema_export_detects_drift(tmp_path: Path) -> None:
    schema = tmp_path / "schemas" / "release.schema.json"
    export_release_schema(schema)
    export_release_schema(schema, check=True)
    schema.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="out of date"):
        export_release_schema(schema, check=True)


def test_stage_activate_and_rollback_are_digest_addressed_and_atomic(tmp_path: Path) -> None:
    bundle_a = tmp_path / "bundle-a"
    bundle_b = tmp_path / "bundle-b"
    manifest_a = _seal(bundle_a, ["DOC1"], "test-v1")
    manifest_b = _seal(bundle_b, ["DOC1", "DOC2"], "test-v2")
    release_root = tmp_path / "deployment"

    staged_a = stage_release(bundle_a, release_root)
    staged_b = stage_release(bundle_b, release_root)
    assert staged_a.name == manifest_a.bundle_sha256
    assert staged_b.name == manifest_b.bundle_sha256
    assert stage_release(bundle_a, release_root) == staged_a
    assert current_release(release_root) is None

    first = activate_release(release_root, manifest_a.bundle_sha256)
    assert first == {"current": manifest_a.bundle_sha256, "previous": None}
    assert current_release(release_root) == manifest_a.bundle_sha256
    assert SQLiteRecordStore(
        release_root / "current" / "records.sqlite", read_only=True
    ).count_articles() == 1

    second = activate_release(release_root, manifest_b.bundle_sha256)
    assert second["previous"] == manifest_a.bundle_sha256
    assert current_release(release_root) == manifest_b.bundle_sha256
    assert SQLiteRecordStore(
        release_root / "current" / "records.sqlite", read_only=True
    ).count_articles() == 2

    rolled_back = rollback_release(release_root, manifest_a.bundle_sha256)
    assert rolled_back["previous"] == manifest_b.bundle_sha256
    assert current_release(release_root) == manifest_a.bundle_sha256

    (staged_b / "summary.json").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ValueError):
        activate_release(release_root, manifest_b.bundle_sha256)
    assert current_release(release_root) == manifest_a.bundle_sha256


def test_stage_rejects_release_root_inside_source_bundle(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _seal(bundle, ["DOC1"], "test-v1")

    with pytest.raises(ValueError, match="must not be inside the source bundle"):
        stage_release(bundle, bundle / "deployment")

    assert not (bundle / "deployment").exists()
