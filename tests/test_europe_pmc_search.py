from mdlit.clients import EuropePMCClient


class FixtureHTTP:
    def get_json(self, url: str):
        return {"resultList": {"result": []}}, "a" * 64


def test_europe_pmc_search_builds_encoded_url() -> None:
    client = EuropePMCClient(http=FixtureHTTP())  # type: ignore[arg-type]
    data, digest, url = client.search('OPEN_ACCESS:Y AND "molecular dynamics"', page_size=60)
    assert data == {"resultList": {"result": []}}
    assert digest == "a" * 64
    assert "pageSize=60" in url
    assert "molecular+dynamics" in url
