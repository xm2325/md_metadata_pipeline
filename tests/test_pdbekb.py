from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from mdmeta.models import ValidationState
from mdmeta.pdbekb import (
    PDBeKBBatchReport,
    build_pdbekb_batch_report,
    fetch_pdbekb_enrichment,
)
from mdmeta.validation import IdentifierValidator
from scripts.run_pdbekb_enrichment import run


ACCESSION = "Q14676"


def _handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url.endswith(f"/uniprot/annotations/{ACCESSION}"):
        return httpx.Response(
            200,
            json={
                ACCESSION: {
                    "sequence": "A" * 20,
                    "length": 20,
                    "dataType": "UNIPROT",
                    "data": [
                        {
                            "name": "Predicted ligand pocket",
                            "accession": "p2rank",
                            "dataType": "ANNOTATION",
                            "residues": [
                                {
                                    "startIndex": 2,
                                    "endIndex": 4,
                                    "startCode": "A",
                                    "endCode": "D",
                                    "indexType": "UNIPROT",
                                    "pdbEntries": [
                                        {
                                            "pdbId": "3unn",
                                            "entityId": 2,
                                            "chainIds": ["B"],
                                        }
                                    ],
                                    "additionalData": {
                                        "resourceUrl": "https://example.org/p2rank/Q14676",
                                        "confidenceClassification": "high",
                                    },
                                },
                                {
                                    "startIndex": 4,
                                    "endIndex": 5,
                                    "startCode": "D",
                                    "endCode": "E",
                                    "indexType": "UNIPROT",
                                },
                            ],
                        }
                    ],
                }
            },
        )
    if url.endswith(f"/uniprot/annotation_partners/{ACCESSION}"):
        return httpx.Response(
            200,
            json={
                ACCESSION: {
                    "externalResources": [
                        {
                            "resourceName": "p2rank",
                            "url": "https://example.org/p2rank",
                            "annotationCategory": "predicted_ligand_binding_site",
                        }
                    ]
                }
            },
        )
    raise AssertionError(f"unexpected URL: {url}")


def _validator(handler=_handler, *, cache_dir: Path | None = None) -> IdentifierValidator:
    return IdentifierValidator(
        httpx.Client(transport=httpx.MockTransport(handler)),
        cache_dir=cache_dir,
        sleep=lambda _: None,
    )


def test_pdbekb_adapter_compacts_annotations_and_retains_audit_metadata(
    tmp_path: Path,
) -> None:
    enrichment = fetch_pdbekb_enrichment(
        _validator(cache_dir=tmp_path / "cache"), ACCESSION.lower()
    )

    assert enrichment.state is ValidationState.VALIDATED
    assert enrichment.sequence_length == 20
    assert enrichment.annotation_result.response_sha256 is not None
    assert enrichment.partner_result.response_sha256 is not None
    assert enrichment.annotation_result.attempts == 1
    assert len(enrichment.annotation_groups) == 1
    group = enrichment.annotation_groups[0]
    assert group.residue_range_count == 2
    assert group.covered_sequence_position_count == 4
    assert group.pdb_ids == ["3UNN"]
    assert group.resource_urls == ["https://example.org/p2rank/Q14676"]
    assert group.confidence_classifications == ["high"]
    assert enrichment.partners[0].annotation_category == "predicted_ligand_binding_site"
    payload = enrichment.model_dump(mode="json")
    assert "sequence" not in payload
    assert "payload" not in payload

    cached = fetch_pdbekb_enrichment(
        _validator(cache_dir=tmp_path / "cache"), ACCESSION
    )
    assert cached.annotation_result.cache_hit is True
    assert cached.partner_result.cache_hit is True
    assert cached.annotation_result.attempts == 0


def test_pdbekb_malformed_success_is_unresolved_not_biological_conflict() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/annotations/" in str(request.url):
            return httpx.Response(
                200,
                json={ACCESSION: {"length": 20, "data": [{"name": "missing fields"}]}},
            )
        return httpx.Response(200, json={ACCESSION: {"externalResources": []}})

    enrichment = fetch_pdbekb_enrichment(_validator(handler), ACCESSION)

    assert enrichment.state is ValidationState.UNRESOLVED
    assert enrichment.annotation_result.state is ValidationState.UNRESOLVED
    assert enrichment.annotation_result.reason == "malformed_annotation_payload"
    assert enrichment.partner_result.state is ValidationState.VALIDATED


def test_pdbekb_missing_accession_is_explicit_conflict() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/annotations/" in str(request.url):
            return httpx.Response(200, json={"OTHER": {"length": 1, "data": []}})
        return httpx.Response(200, json={ACCESSION: {"externalResources": []}})

    enrichment = fetch_pdbekb_enrichment(_validator(handler), ACCESSION)

    assert enrichment.state is ValidationState.CONFLICT
    assert enrichment.annotation_result.reason == "accession_missing_from_successful_response"


def test_pdbekb_batch_report_binds_verified_database_and_rejects_tampering(
    tmp_path: Path,
) -> None:
    database = tmp_path / "records.sqlite"
    database.write_bytes(b"portable verified database fixture")
    enrichment = fetch_pdbekb_enrichment(_validator(), ACCESSION)
    report = build_pdbekb_batch_report(
        [enrichment],
        source_database=database,
        source_database_schema_version=1,
        source_article_count=80,
        generated_at=datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
    )

    assert report.source_database_sha256 == hashlib.sha256(database.read_bytes()).hexdigest()
    assert report.requested_accessions == [ACCESSION]
    assert report.state_counts == {"validated": 1}
    assert report.annotation_group_count == 1
    assert report.annotation_residue_range_count == 2
    assert report.partner_count == 1
    assert report.linked_pdb_id_count == 1
    assert len(report.content_commitment_sha256) == 64

    tampered = report.model_dump(mode="json")
    tampered["source_article_count"] = 79
    with pytest.raises(ValidationError, match="content_commitment_sha256"):
        PDBeKBBatchReport.model_validate(tampered)


@pytest.mark.parametrize("accession", ["", "../Q14676", "P1234", "Q14676-2"])
def test_pdbekb_adapter_rejects_unsafe_or_nonprimary_accessions(accession: str) -> None:
    with pytest.raises(ValueError, match="invalid UniProt accession"):
        fetch_pdbekb_enrichment(_validator(), accession)


@pytest.mark.parametrize("workers", [0, 17])
def test_pdbekb_runner_bounds_public_api_concurrency(
    tmp_path: Path, workers: int
) -> None:
    with pytest.raises(ValueError, match="workers must be between 1 and 16"):
        run(
            tmp_path / "not-opened.sqlite",
            output=tmp_path / "report.json",
            cache_dir=tmp_path / "cache",
            require_complete=False,
            workers=workers,
        )
