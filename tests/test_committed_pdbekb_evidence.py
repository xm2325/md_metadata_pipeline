from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_committed_pdbekb_scale80_summary_preserves_claim_boundaries() -> None:
    path = ROOT / "study" / "pdbekb_scale80" / "run_summary.json"
    report = json.loads(path.read_text(encoding="utf-8"))

    assert report["schema_version"] == "mdmeta.pdbekb-scale80-run.v1"
    assert report["source"]["input_article_count"] == 80
    assert report["source"]["input_uniprot_accession_count"] == 107
    assert report["migration"]["from_schema_version"] == 1
    assert report["migration"]["to_schema_version"] == 2
    assert report["migration"]["integrity"] == "ok"
    assert report["migration"]["foreign_key_violation_count"] == 0
    assert report["migration"]["fail_closed_ordering_probe"]["database_mutated"] is False
    enrichment = report["pdbekb_enrichment"]
    assert sum(enrichment["state_counts"].values()) == 107
    assert enrichment["state_counts"] == {
        "validated": 94,
        "not_applicable": 3,
        "unresolved": 10,
    }
    assert enrichment["annotation_group_count"] == 815
    assert enrichment["annotation_residue_range_count"] == 152861
    assert enrichment["partner_count"] == 390
    assert enrichment["linked_pdb_id_count"] == 2732
    assert enrichment["raw_sequences_retained"] is False
    assert enrichment["raw_api_payloads_retained_in_report"] is False
    final = report["persistence_and_api"]
    assert final["article_count"] == final["record_validation_checked"] == 80
    assert final["record_validation_errors"] == 0
    assert final["sqlite_integrity"] == "ok"
    assert final["foreign_key_violation_count"] == 0
    assert final["sidecar_file_count"] == 0
    boundary = report["scientific_claim_boundary"]
    assert boundary["human_reference_labels_used"] is False
    assert boundary["accuracy_estimated"] is False

    serialized = json.dumps(report, sort_keys=True)
    for private_fragment in ("/scratch", "/projappl", "xiaomei", "private_key"):
        assert private_fragment not in serialized
