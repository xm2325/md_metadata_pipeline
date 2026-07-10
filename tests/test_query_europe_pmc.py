import httpx
import pytest

from scripts.query_europe_pmc import (
    _article,
    _bounded_retry_after,
    _get_page_with_retry,
    software_family,
)


def test_software_family_and_article_conversion() -> None:
    assert software_family("Simulated with GROMACS and OpenMM") == "gromacs+openmm"
    article = _article(
        {
            "pmcid": "PMC123",
            "title": "An MD simulation",
            "abstractText": "GROMACS was used",
            "pubYear": "2025",
            "doi": "10.1/test",
            "license": "CC BY",
        }
    )
    assert article is not None
    assert article["document_id"] == "PMC123"
    assert article["year"] == 2025
    assert article["software_family"] == "gromacs"


class SequenceClient:
    def __init__(self, outcomes: list[httpx.Response | Exception]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    def get(self, url: str, params: dict):
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _response(status: int, retry_after: str | None = None) -> httpx.Response:
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return httpx.Response(
        status,
        headers=headers,
        content=b'{"resultList":{"result":[]}}',
        request=httpx.Request("GET", "https://example.test"),
    )


def test_page_retry_recovers_from_503_and_honours_bounded_retry_after() -> None:
    client = SequenceClient([_response(503, "0.25"), _response(200)])
    sleeps: list[float] = []
    response = _get_page_with_retry(
        client, params={"cursorMark": "*"}, retries=2, sleep=sleeps.append
    )
    assert response.status_code == 200
    assert client.calls == 2
    assert sleeps == [0.25]
    assert _bounded_retry_after(_response(429, "120"), 1.0) == 30.0


def test_page_retry_recovers_from_transport_error() -> None:
    request = httpx.Request("GET", "https://example.test")
    client = SequenceClient([httpx.ReadTimeout("timeout", request=request), _response(200)])
    sleeps: list[float] = []
    assert _get_page_with_retry(
        client, params={"cursorMark": "cursor-1"}, retries=1, sleep=sleeps.append
    ).status_code == 200
    assert sleeps == [1.0]


def test_non_retryable_status_fails_immediately() -> None:
    client = SequenceClient([_response(400)])
    with pytest.raises(httpx.HTTPStatusError):
        _get_page_with_retry(client, params={"cursorMark": "*"}, retries=5, sleep=lambda _: None)
    assert client.calls == 1


def test_retry_exhaustion_reports_cursor() -> None:
    client = SequenceClient([_response(503), _response(503)])
    with pytest.raises(RuntimeError, match="cursor='locked-cursor'"):
        _get_page_with_retry(
            client,
            params={"cursorMark": "locked-cursor"},
            retries=1,
            sleep=lambda _: None,
        )
