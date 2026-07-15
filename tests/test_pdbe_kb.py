import httpx

from mdmeta.models import ValidationState
from mdmeta.pdbe_kb import fetch_pdbe_kb_annotations
from mdmeta.validation import IdentifierValidator


def mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_pdbe_kb_projects_explicit_provider_annotation_and_range() -> None:
    payload = {
        "6vsb": [
            {
                "origin": "M-CSA",
                "annotation_type": "catalytic_residue",
                "label": "Catalytic residue",
                "chain_id": "A",
                "residues": [{"start": 331, "end": 331}],
            }
        ]
    }
    enrichment = fetch_pdbe_kb_annotations(
        IdentifierValidator(mock_client(lambda request: httpx.Response(200, json=payload))),
        "6VSB",
    )
    assert enrichment.state is ValidationState.VALIDATED
    assert enrichment.reason == "pdbe_kb_annotations_projected"
    assert enrichment.provider_counts == {"M-CSA": 1}
    annotation = enrichment.annotations[0]
    assert annotation.pdb_id == "6VSB"
    assert annotation.chain_id == "A"
    assert (annotation.residue_start, annotation.residue_end) == (331, 331)
    assert enrichment.raw_payload is None


def test_pdbe_kb_preserves_valid_service_response_without_guessing_projection() -> None:
    payload = {"6vsb": [{"providerSpecificBlob": {"score": 0.8}}]}
    enrichment = fetch_pdbe_kb_annotations(
        IdentifierValidator(mock_client(lambda request: httpx.Response(200, json=payload))),
        "6VSB",
        retain_payload=True,
    )
    assert enrichment.state is ValidationState.VALIDATED
    assert enrichment.reason == "pdbe_kb_payload_available_no_supported_projection"
    assert enrichment.annotations == []
    assert enrichment.raw_payload == payload


def test_pdbe_kb_malformed_success_is_unresolved() -> None:
    enrichment = fetch_pdbe_kb_annotations(
        IdentifierValidator(
            mock_client(lambda request: httpx.Response(200, json={"6vsb": {"bad": "shape"}}))
        ),
        "6VSB",
    )
    assert enrichment.state is ValidationState.UNRESOLVED
    assert enrichment.reason == "malformed_pdbe_kb_payload"


def test_pdbe_kb_404_is_conflict_and_network_failure_is_unresolved() -> None:
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
