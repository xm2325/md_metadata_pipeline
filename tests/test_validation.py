import httpx

from mdmeta.models import ValidationState
from mdmeta.validation import IdentifierValidator


def mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_pdb_validated() -> None:
    validator = IdentifierValidator(
        mock_client(lambda request: httpx.Response(200, json={"7zk3": [{"title": "entry"}]}))
    )
    record = validator.validate_pdb("7ZK3")
    assert record.state is ValidationState.VALIDATED
    assert record.response_sha256


def test_pdb_404_is_conflict_not_network_failure() -> None:
    validator = IdentifierValidator(mock_client(lambda request: httpx.Response(404, json={})))
    assert validator.validate_pdb("2GMX").state is ValidationState.CONFLICT


def test_timeout_is_unresolved_not_conflict() -> None:
    def handler(request):
        raise httpx.ReadTimeout("timeout", request=request)

    validator = IdentifierValidator(mock_client(handler))
    assert validator.validate_pdb("7ZK3").state is ValidationState.UNRESOLVED


def test_mapping_chain_conflict() -> None:
    payload = {"7zk3": {"UniProt": {"Q5XXA6": {"mappings": [{"chain_id": "A"}]}}}}
    validator = IdentifierValidator(
        mock_client(lambda request: httpx.Response(200, json=payload))
    )
    record = validator.validate_mapping("7ZK3", "Q5XXA6", "B")
    assert record.state is ValidationState.CONFLICT
