from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mdmeta.benchmark import canonical_sha256
from scripts.substitute_frozen_article import substitute_frozen_article


SPLITS = ("development", "validation", "locked_test")
GENERATED_AT = "2026-07-15T12:00:00Z"


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _xml(document_id: str) -> bytes:
    return (
        f"<article><front><article-meta><article-id pub-id-type='pmcid'>{document_id}"
        f"</article-id></article-meta></front><body><sec><title>Methods</title><p>"
        f"frozen fixture for {document_id}</p></sec></body></article>"
    ).encode()


def _write_json(path: Path, payload: dict) -> str:
    data = json.dumps(payload, indent=2, sort_keys=True).encode()
    path.write_bytes(data)
    return _sha256(data)


def _fixture(tmp_path: Path) -> dict:
    selected_ids = [f"PMC{index:06d}" for index in range(1, 61)]
    reserve_ids = ["PMC000061", "PMC000062"]
    all_ids = selected_ids + reserve_ids
    xml_by_id = {document_id: _xml(document_id) for document_id in all_ids}
    screen = {
        "study_id": "screen-pool",
        "study_status": "provisional_temporal_isolation",
        "plan_sha256": "b" * 64,
        "screening_scope": "machine_triage_not_human_eligibility",
        "records": [
            {
                "document_id": document_id,
                "split": "development",
                "full_text_sha256": _sha256(xml_by_id[document_id]),
                "xml_size_bytes": len(xml_by_id[document_id]),
                "machine_screen_status": "strong_biomolecular_protocol_signal",
                "machine_eligible_for_annotation": True,
            }
            for document_id in all_ids
        ],
        "failures": [],
    }
    screen_sha256 = canonical_sha256(screen)

    articles = [
        {
            "document_id": document_id,
            "title": f"Article {document_id}",
            "source_uri": f"https://europepmc.org/articles/{document_id}",
            "year": 2020,
        }
        for document_id in selected_ids
    ]
    plan_core = {
        "study_id": "provisional-60",
        "study_status": "provisional_temporal_isolation_machine_screened",
        "source_pool_plan_sha256": screen["plan_sha256"],
        "screen_sha256": screen_sha256,
        "screening_scope": "machine_triage_not_human_eligibility",
        "development": selected_ids[:30],
        "validation": selected_ids[30:40],
        "locked_test": selected_ids[40:],
        "rejected_or_reserve": [
            {
                "document_id": document_id,
                "reason": "eligible_reserve_not_selected",
                "machine_screen_status": "strong_biomolecular_protocol_signal",
                "article_type": "research-article",
            }
            for document_id in reserve_ids
        ],
    }
    plan = {
        **plan_core,
        "development": articles[:30],
        "validation": articles[30:40],
        "locked_test": articles[40:],
        "plan_sha256": canonical_sha256(plan_core),
        "interpretation": "machine-screened provisional plan",
    }
    split_by_id = {
        row["document_id"]: split
        for split in SPLITS
        for row in plan[split]
    }
    parent_core = {
        "study_id": "parent-60",
        "study_status": "provisional_temporal_isolation_machine_screened",
        "plan_sha256": plan["plan_sha256"],
        "source_screen_sha256": screen_sha256,
        "source_workflow_run": 29087844703,
        "source_workflow_artifact_id": 8225494475,
        "source_workflow_artifact_digest": f"sha256:{'c' * 64}",
        "articles": [
            {
                "document_id": document_id,
                "split": split_by_id[document_id],
                "source_uri": f"https://europepmc.org/articles/{document_id}",
                "full_text_sha256": _sha256(xml_by_id[document_id]),
            }
            for document_id in selected_ids
        ],
    }
    parent = {**parent_core, "manifest_sha256": canonical_sha256(parent_core)}

    parent_path = tmp_path / "parent.json"
    plan_path = tmp_path / "plan.json"
    screen_path = tmp_path / "screen.json"
    cache_dir = tmp_path / "jats"
    cache_dir.mkdir()
    parent_file_sha256 = _write_json(parent_path, parent)
    plan_file_sha256 = _write_json(plan_path, plan)
    screen_file_sha256 = _write_json(screen_path, screen)

    old_document_id = "PMC000045"
    replacement_document_id = reserve_ids[0]
    (cache_dir / f"{old_document_id}.xml").write_bytes(
        (
            f"<article><front><article-meta><article-id pub-id-type='pmcid'>"
            f"{old_document_id}</article-id></article-meta></front><body>"
            "currently available but drifted JATS</body></article>"
        ).encode()
    )
    (cache_dir / f"{replacement_document_id}.xml").write_bytes(
        xml_by_id[replacement_document_id]
    )
    return {
        "parent_manifest_path": parent_path,
        "expected_parent_file_sha256": parent_file_sha256,
        "provisional_plan_path": plan_path,
        "expected_plan_file_sha256": plan_file_sha256,
        "fulltext_screen_path": screen_path,
        "expected_screen_file_sha256": screen_file_sha256,
        "jats_cache_dir": cache_dir,
        "replace_document_id": old_document_id,
        "replacement_document_id": replacement_document_id,
        "generated_at": GENERATED_AT,
        "parent": parent,
        "xml_by_id": xml_by_id,
    }


def _call(case: dict, **updates):
    arguments = {
        key: value
        for key, value in case.items()
        if key not in {"parent", "xml_by_id"}
    }
    arguments.update(updates)
    return substitute_frozen_article(**arguments)


def test_substitutes_first_eligible_reserve_and_preserves_59_rows(tmp_path: Path) -> None:
    case = _fixture(tmp_path)

    manifest, report = _call(case)

    old_position = 44
    assert manifest["articles"][old_position]["document_id"] == "PMC000061"
    assert manifest["articles"][old_position]["split"] == "locked_test"
    assert manifest["articles"][old_position]["source_uri"] == (
        "https://europepmc.org/articles/PMC000061"
    )
    assert manifest["articles"][old_position]["full_text_sha256"] == _sha256(
        case["xml_by_id"]["PMC000061"]
    )
    assert manifest["manifest_sha256"] == canonical_sha256(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    assert manifest["parent_manifest_sha256"] == case["parent"]["manifest_sha256"]
    assert manifest["model_output_used_for_substitution"] is False
    assert manifest["unchanged_article_count_expected"] == 59
    assert manifest["unchanged_article_count_observed"] == 59
    assert sum(
        before == after
        for before, after in zip(
            case["parent"]["articles"],
            manifest["articles"],
            strict=True,
        )
    ) == 59
    assert report["old"]["document_id"] == "PMC000045"
    assert report["new"]["document_id"] == "PMC000061"
    assert report["source_workflow_run"] == 29087844703
    assert report["source_workflow_artifact_id"] == 8225494475
    assert report["model_output_used"] is False
    assert report["full_text_included"] is False
    assert "frozen fixture for" not in json.dumps(report)
    assert report["report_sha256"] == canonical_sha256(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )


def test_rejects_reserve_that_is_not_first_in_original_plan(tmp_path: Path) -> None:
    case = _fixture(tmp_path)
    second_reserve = "PMC000062"
    (case["jats_cache_dir"] / f"{second_reserve}.xml").write_bytes(
        case["xml_by_id"][second_reserve]
    )

    with pytest.raises(ValueError, match="first eligible_reserve_not_selected"):
        _call(case, replacement_document_id=second_reserve)


def test_rejects_replacement_cache_hash_mismatch(tmp_path: Path) -> None:
    case = _fixture(tmp_path)
    replacement = case["replacement_document_id"]
    original = case["xml_by_id"][replacement]
    tampered = original[:-1] + bytes([original[-1] ^ 1])
    (case["jats_cache_dir"] / f"{replacement}.xml").write_bytes(tampered)

    with pytest.raises(ValueError, match="replacement JATS SHA-256 differs"):
        _call(case)


def test_rejects_when_parent_frozen_source_has_not_drifted(tmp_path: Path) -> None:
    case = _fixture(tmp_path)
    old_document_id = case["replace_document_id"]
    (case["jats_cache_dir"] / f"{old_document_id}.xml").write_bytes(
        case["xml_by_id"][old_document_id]
    )

    with pytest.raises(ValueError, match="has not drifted"):
        _call(case)


def test_rejects_drift_payload_for_a_different_article(tmp_path: Path) -> None:
    case = _fixture(tmp_path)
    old_document_id = case["replace_document_id"]
    wrong_payload = _xml("PMC999999")
    (case["jats_cache_dir"] / f"{old_document_id}.xml").write_bytes(wrong_payload)

    with pytest.raises(ValueError, match="does not declare PMCID"):
        _call(case)
