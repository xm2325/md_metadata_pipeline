from pathlib import Path

import pytest

SCRIPTS = {
    "stage_inputs.sbatch": "${12:-}",
    "llm_extract.sbatch": "${9:-}",
    "model_integration.sbatch": "${8:-}",
}


@pytest.mark.parametrize(("filename", "digest_position"), SCRIPTS.items())
def test_model_pipeline_accepts_only_hash_bound_external_manifests(
    filename: str,
    digest_position: str,
) -> None:
    script = (Path("hpc/roihu") / filename).read_text(encoding="utf-8")
    assert "SOURCE_MANIFEST_SPEC=" in script
    assert f"SOURCE_MANIFEST_FILE_SHA256={digest_position}" in script
    assert "EXTERNAL_SOURCE_MANIFEST=$(realpath -e" in script
    assert "external source manifest requires its lowercase file SHA-256" in script
    assert "external source manifest must be a regular file in the matching project" in script
    assert '"/projappl/$RUN_PROJECT/$USER/"*' in script
    assert "ACTUAL_SOURCE_MANIFEST_FILE_SHA256=$(sha256sum" in script
    assert "source manifest file digest mismatch" in script
    assert "source_manifest_file_sha256=%s" in script
    assert "source_manifest_external=%s" in script


@pytest.mark.parametrize("filename", SCRIPTS)
def test_existing_archive_relative_manifest_mode_is_retained(filename: str) -> None:
    script = (Path("hpc/roihu") / filename).read_text(encoding="utf-8")
    assert 'SOURCE_MANIFEST="$SOURCE_DIR/$SOURCE_MANIFEST_SPEC"' in script
    assert "source manifest is missing from the verified source archive" in script


def test_scale_inference_has_a_bounded_zero_task_article_policy() -> None:
    script = (Path("hpc/roihu") / "llm_extract.sbatch").read_text(encoding="utf-8")
    assert "--maximum-no-task-article-fraction 0.025" in script
