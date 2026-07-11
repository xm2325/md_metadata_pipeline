import httpx

from mdmeta.models import ValidationState
from mdmeta.validation import IdentifierValidator, summarize_validation


def mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_pdb_validated() -> None:
    validator = IdentifierValidator(
        mock_client(lambda request: httpx.Response(200, json={"7zk3": [{"title": "entry"}]}))
    )
    record = validator.validate_pdb("7ZK3")
    assert record.state is ValidationState.VALIDATED
    assert record.response_sha256
    assert record.attempts == 1


def test_pdb_404_is_conflict_not_network_failure() -> None:
    validator = IdentifierValidator(mock_client(lambda request: httpx.Response(404, json={})))
    assert validator.validate_pdb("2GMX").state is ValidationState.CONFLICT


def test_success_with_invalid_json_is_unresolved_not_biological_conflict() -> None:
    validator = IdentifierValidator(
        mock_client(
            lambda request: httpx.Response(
                200,
                content=b"upstream proxy returned HTML",
                headers={"Content-Type": "text/html"},
            )
        )
    )
    record = validator.validate_pdb("7ZK3")
    assert record.state is ValidationState.UNRESOLVED
    assert record.reason == "invalid_json_response"
    assert record.response_sha256


def test_success_with_wrong_json_shape_is_unresolved() -> None:
    validator = IdentifierValidator(
        mock_client(lambda request: httpx.Response(200, json=[{"id": "7zk3"}]))
    )
    record = validator.validate_pdb("7ZK3")
    assert record.state is ValidationState.UNRESOLVED
    assert record.reason == "unexpected_json_type:list"


def test_success_with_malformed_endpoint_payload_is_unresolved() -> None:
    pdb = IdentifierValidator(
        mock_client(lambda request: httpx.Response(200, json={"7zk3": None}))
    ).validate_pdb("7ZK3")
    assert pdb.state is ValidationState.UNRESOLVED
    assert pdb.reason == "malformed_pdb_summary_payload"

    uniprot = IdentifierValidator(
        mock_client(lambda request: httpx.Response(200, json={"primaryAccession": None}))
    ).validate_uniprot("Q5XXA6")
    assert uniprot.state is ValidationState.UNRESOLVED
    assert uniprot.reason == "malformed_uniprot_payload"


def test_malformed_mapping_payload_is_unresolved() -> None:
    validator = IdentifierValidator(
        mock_client(
            lambda request: httpx.Response(200, json={"7zk3": {"UniProt": []}})
        )
    )
    record = validator.validate_mapping("7ZK3", "Q5XXA6")
    assert record.state is ValidationState.UNRESOLVED
    assert record.reason == "malformed_mapping_payload"


def test_timeout_is_unresolved_not_conflict() -> None:
    def handler(request):
        raise httpx.ReadTimeout("timeout", request=request)

    delays = []
    validator = IdentifierValidator(
        mock_client(handler),
        retries=1,
        sleep=delays.append,
    )
    record = validator.validate_pdb("7ZK3")
    assert record.state is ValidationState.UNRESOLVED
    assert record.attempts == 2
    assert [item.outcome for item in record.request_log] == ["network_error", "network_error"]
    assert delays == [0.25]


def test_mapping_chain_conflict() -> None:
    payload = {"7zk3": {"UniProt": {"Q5XXA6": {"mappings": [{"chain_id": "A"}]}}}}
    validator = IdentifierValidator(
        mock_client(lambda request: httpx.Response(200, json=payload))
    )
    record = validator.validate_mapping("7ZK3", "Q5XXA6", "B")
    assert record.state is ValidationState.CONFLICT
    assert record.mapping_segments[0].chain_id == "A"


def test_mapping_parses_residue_ranges() -> None:
    payload = {
        "7zk3": {
            "UniProt": {
                "Q5XXA6": {
                    "mappings": [
                        {
                            "chain_id": "A",
                            "start": {"residue_number": 4},
                            "end": {"residue_number": 102},
                            "unp_start": 11,
                            "unp_end": 109,
                        }
                    ]
                }
            }
        }
    }
    record = IdentifierValidator(
        mock_client(lambda request: httpx.Response(200, json=payload))
    ).validate_mapping("7ZK3", "Q5XXA6", "A")
    assert record.state is ValidationState.VALIDATED
    segment = record.mapping_segments[0]
    assert (segment.pdb_start, segment.pdb_end) == (4, 102)
    assert (segment.uniprot_start, segment.uniprot_end) == (11, 109)


def test_retry_after_429_then_success() -> None:
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0.5"}, json={})
        return httpx.Response(200, json={"7zk3": [{"title": "entry"}]})

    delays = []
    record = IdentifierValidator(
        mock_client(handler),
        retries=2,
        sleep=delays.append,
    ).validate_pdb("7ZK3")
    assert record.state is ValidationState.VALIDATED
    assert record.attempts == 2
    assert delays == [0.5]
    assert record.request_log[0].http_status == 429
    assert record.request_log[0].retry_after_seconds == 0.5


def test_successful_response_cache_avoids_second_network_call(tmp_path) -> None:
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"7zk3": [{"title": "entry"}]})

    validator = IdentifierValidator(mock_client(handler), cache_dir=tmp_path)
    first = validator.validate_pdb("7ZK3")
    second = validator.validate_pdb("7ZK3")
    assert calls == 1
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.attempts == 0
    assert second.response_sha256 == first.response_sha256


def test_corrupt_cache_is_ignored_and_replaced(tmp_path) -> None:
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"7zk3": [{"title": "entry"}]})

    validator = IdentifierValidator(mock_client(handler), cache_dir=tmp_path)
    endpoint = "https://www.ebi.ac.uk/pdbe/api/pdb/entry/summary/7zk3"
    validator.cache._path(endpoint).write_text("{truncated", encoding="utf-8")
    record = validator.validate_pdb("7ZK3")
    assert record.state is ValidationState.VALIDATED
    assert calls == 1


def test_validation_summary_preserves_states_and_attempts(tmp_path) -> None:
    valid = IdentifierValidator(
        mock_client(lambda request: httpx.Response(200, json={"7zk3": [{"title": "entry"}]})),
        cache_dir=tmp_path,
    ).validate_pdb("7ZK3")
    cached = IdentifierValidator(
        mock_client(lambda request: (_ for _ in ()).throw(AssertionError("network used"))),
        cache_dir=tmp_path,
    ).validate_pdb("7ZK3")
    conflict = IdentifierValidator(
        mock_client(lambda request: httpx.Response(404, json={}))
    ).validate_pdb("2GMX")
    summary = summarize_validation([valid, cached, conflict])
    assert summary["state_counts"] == {"conflict": 1, "validated": 2}
    assert summary["cache_hit_count"] == 1
    assert summary["total_network_attempts"] == 2
    assert summary["unresolved_or_conflict_count"] == 1
