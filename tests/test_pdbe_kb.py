import httpx

from mdmeta.models import ValidationState
from mdmeta.pdbe_kb import fetch_pdbe_kb_annotations
from mdmeta.validation import IdentifierValidator


def mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_pdbe_kb_discovers_provider_and_projects_site_residue() -> None:
    catalogue = {
        "6vsb": [
            {
                "origin": "M-CSA",
                "labels": ["Catalytic residue"],
                "evidence_codes": ["ECO:0000269"],
                "release_date": "2026-01-01",
                "url": "https://example.org/mcsa",
                "annotations": None,
            }
        ]
    }
    provider_payload = {
        "6vsb": [
            {
                "origin": "M-CSA",
                "annotations": [
                    {
                        "label": "Catalytic residue",
                        "site_residues": [
                            {
                                "chain_id": "A",
                                "residue_number": 331,
                                "author_residue_number": 331,
                                "entity_id": 1,
                                "raw_score": 0.9,
                                "confidence_score": 0.8,
                                "confidence_classification": "high",
                            }
                        ],
                    }
                ],
            }
        ]
    }

    def handler(request):
        if "/funpdbe_annotation/M-CSA/" in str(request.url):
            return httpx.Response(200, json=provider_payload)
        return httpx.Response(200, json=catalogue)

    enrichment = fetch_pdbe_kb_annotations(
        IdentifierValidator(mock_client(handler)),
        "6VSB",
    )
    assert enrichment.schema_version == "pdbe-kb-enrichment-v2"
    assert enrichment.state is ValidationState.VALIDATED
    assert enrichment.reason == "pdbe_kb_annotations_projected"
    assert enrichment.provider_counts == {"M-CSA": 1}
    assert enrichment.provider_state_counts == {"validated": 1}
    assert enrichment.provider_catalogue[0].labels == ["Catalytic residue"]
    assert enrichment.provider_requests[0].annotation_count == 1
    annotation = enrichment.annotations[0]
    assert annotation.pdb_id == "6VSB"
    assert annotation.chain_id == "A"
    assert (annotation.residue_start, annotation.residue_end) == (331, 331)
    assert annotation.author_residue_number == 331
    assert annotation.entity_id == 1
    assert annotation.confidence_classification == "high"
    assert enrichment.raw_payload is None


def test_pdbe_kb_retains_catalogue_without_guessing_unknown_provider_rows() -> None:
    payload = {"6vsb": [{"providerSpecificBlob": {"score": 0.8}}]}
    enrichment = fetch_pdbe_kb_annotations(
        IdentifierValidator(mock_client(lambda request: httpx.Response(200, json=payload))),
        "6VSB",
        retain_payload=True,
    )
    assert enrichment.state is ValidationState.VALIDATED
    assert enrichment.reason == "pdbe_kb_catalogue_contains_no_supported_providers"
    assert enrichment.annotations == []
    assert enrichment.provider_requests == []
    assert enrichment.raw_payload == {
        "catalogue": payload,
        "provider_annotations": {},
    }


def test_pdbe_kb_provider_response_can_be_valid_and_empty() -> None:
    catalogue = {"6vsb": [{"origin": "DEPTH", "labels": ["depth"]}]}
    provider_payload = {"6vsb": [{"origin": "DEPTH", "annotations": None}]}

    def handler(request):
        if "funpdbe_annotation" in str(request.url):
            return httpx.Response(200, json=provider_payload)
        return httpx.Response(200, json=catalogue)

    enrichment = fetch_pdbe_kb_annotations(
        IdentifierValidator(mock_client(handler)),
        "6VSB",
    )
    assert enrichment.state is ValidationState.VALIDATED
    assert enrichment.reason == "pdbe_kb_providers_returned_no_annotations"
    assert enrichment.provider_requests[0].reason == "provider_response_contains_no_annotations"


def test_pdbe_kb_annotations_with_known_provider_404_remain_validated() -> None:
    catalogue = {
        "6vsb": [
            {"origin": "M-CSA", "labels": ["Catalytic residue"]},
            {"origin": "WEBnma", "labels": ["mobility"]},
        ]
    }
    provider_payload = {
        "6vsb": [
            {
                "origin": "M-CSA",
                "annotations": [
                    {
                        "label": "Catalytic residue",
                        "site_residues": [{"chain_id": "A", "residue_number": 1}],
                    }
                ],
            }
        ]
    }

    def handler(request):
        url = str(request.url)
        if "/WEBnma/" in url:
            return httpx.Response(
                404,
                json={"message": "Requested endpoint does not contain any data"},
            )
        if "/M-CSA/" in url:
            return httpx.Response(200, json=provider_payload)
        return httpx.Response(200, json=catalogue)

    enrichment = fetch_pdbe_kb_annotations(
        IdentifierValidator(mock_client(handler)),
        "6VSB",
    )
    assert enrichment.state is ValidationState.VALIDATED
    assert enrichment.reason == "pdbe_kb_annotations_projected_with_provider_conflicts"
    assert enrichment.provider_state_counts == {"conflict": 1, "validated": 1}
    assert len(enrichment.annotations) == 1


def test_pdbe_kb_malformed_catalogue_success_is_unresolved() -> None:
    enrichment = fetch_pdbe_kb_annotations(
        IdentifierValidator(
            mock_client(lambda request: httpx.Response(200, json={"6vsb": {"bad": "shape"}}))
        ),
        "6VSB",
    )
    assert enrichment.state is ValidationState.UNRESOLVED
    assert enrichment.reason == "malformed_pdbe_kb_catalogue_payload"


def test_pdbe_kb_provider_failure_marks_partial_result_unresolved() -> None:
    catalogue = {"6vsb": [{"origin": "DEPTH", "labels": ["depth"]}]}

    def handler(request):
        if "funpdbe_annotation" in str(request.url):
            raise httpx.ReadTimeout("timeout", request=request)
        return httpx.Response(200, json=catalogue)

    enrichment = fetch_pdbe_kb_annotations(
        IdentifierValidator(mock_client(handler), retries=0),
        "6VSB",
    )
    assert enrichment.state is ValidationState.UNRESOLVED
    assert enrichment.reason == "pdbe_kb_provider_retrieval_incomplete"
    assert enrichment.provider_state_counts == {"unresolved": 1}
    assert enrichment.provider_requests[0].reason == "network_error:ReadTimeout"


def test_pdbe_kb_404_is_conflict_and_catalogue_network_failure_is_unresolved() -> None:
    missing = fetch_pdbe_kb_annotations(
        IdentifierValidator(mock_client(lambda request: httpx.Response(404, json={}))),
        "6VSB",
    )
    assert missing.state is ValidationState.CONFLICT

    def timeout(request):
        raise httpx.ReadTimeout("timeout", request=request)

    unavailable = fetch_pdbe_kb_annotations(
        IdentifierValidator(mock_client(timeout), retries=0),
        "6VSB",
    )
    assert unavailable.state is ValidationState.UNRESOLVED
    assert unavailable.reason == "network_error:ReadTimeout"


def test_pdbe_kb_rejects_invalid_pdb_id_before_network() -> None:
    validator = IdentifierValidator(
        mock_client(lambda request: (_ for _ in ()).throw(AssertionError("network used")))
    )
    try:
        fetch_pdbe_kb_annotations(validator, "INVALID")
    except ValueError as exc:
        assert "invalid PDB identifier" in str(exc)
    else:
        raise AssertionError("invalid identifier was accepted")
