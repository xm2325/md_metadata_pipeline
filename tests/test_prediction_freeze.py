import hashlib
from pathlib import Path

import pytest

from mdmeta.benchmark import canonical_sha256
from scripts.freeze_machine_predictions import (
    freeze_predictions,
    method_paragraphs,
    read_cached_xml,
)

XML = b'''<article article-type="research-article"><body><sec><title>Molecular dynamics methods</title><p id="p1">The protein system was equilibrated for 2 ns at 300 K. A production simulation of 100 ns used the NPT ensemble and a time step of 2 fs.</p></sec></body></article>'''


def _inputs() -> tuple[dict, dict]:
    digest = hashlib.sha256(XML).hexdigest()
    screen = {
        "plan_sha256": "a" * 64,
        "records": [
            {
                "document_id": "PMC1",
                "full_text_sha256": digest,
            }
        ],
    }
    plan = {
        "study_status": "provisional_temporal_isolation_machine_screened",
        "plan_sha256": "b" * 64,
        "screen_sha256": canonical_sha256(screen),
        "development": [
            {
                "document_id": "PMC1",
                "source_uri": "https://europepmc.org/articles/PMC1",
            }
        ],
        "validation": [],
        "locked_test": [],
    }
    return plan, screen


def test_method_paragraphs_and_prediction_freeze() -> None:
    paragraphs = method_paragraphs("PMC1", XML)
    assert len(paragraphs) == 1
    assert paragraphs[0].paragraph_id == "p1"

    plan, screen = _inputs()
    result = freeze_predictions(plan, screen, lambda _: XML)
    assert result["article_count_succeeded"] == 1
    assert result["failure_count"] == 0
    assert result["event_count"] == 2
    assert result["human_reference_used"] is False
    assert result["accuracy_evaluated"] is False
    assert result["blinding_status"] == "separate_artifact_not_in_human_workpack"
    assert result["source_snapshot_policy"] == "same_runner_ephemeral_jats_cache"
    assert len(result["prediction_sha256"]) == 64
    assert {event["event_type"] for event in result["articles"][0]["events"]} == {
        "equilibration",
        "production",
    }


def test_cached_xml_reader(tmp_path: Path) -> None:
    (tmp_path / "PMC1.xml").write_bytes(XML)
    assert read_cached_xml(tmp_path, "pmc1") == XML
    with pytest.raises(FileNotFoundError, match="missing cached JATS snapshot"):
        read_cached_xml(tmp_path, "PMC2")


def test_prediction_freeze_fails_closed_on_changed_full_text() -> None:
    plan, screen = _inputs()
    changed = XML.replace(b"100 ns", b"200 ns")
    result = freeze_predictions(plan, screen, lambda _: changed)
    assert result["article_count_succeeded"] == 0
    assert result["failure_count"] == 1
    assert "SHA-256 changed" in result["failures"][0]["message"]


def test_prediction_freeze_rejects_wrong_screen_commitment() -> None:
    plan, screen = _inputs()
    plan["screen_sha256"] = "c" * 64
    with pytest.raises(ValueError, match="does not match"):
        freeze_predictions(plan, screen, lambda _: XML)
