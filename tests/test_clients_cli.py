import hashlib
import json
from pathlib import Path

import httpx
from typer.testing import CliRunner

from mdlit.cli import app
from mdlit.clients import CachedHTTPClient, EuropePMCClient, PDBeClient, UniProtClient


class FakeResponse:
    content = b'{"ok": true}'

    def raise_for_status(self) -> None:
        return None


class FakeClient:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, url: str):
        return FakeResponse()


def test_cached_http_json_and_cache(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(httpx, "Client", FakeClient)
    client = CachedHTTPClient(cache_dir=tmp_path, retries=0)
    data, digest = client.get_json("https://example.test/item")
    assert data == {"ok": True}
    assert digest == hashlib.sha256(FakeResponse.content).hexdigest()
    monkeypatch.setattr(
        httpx, "Client", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network used"))
    )
    data2, _ = client.get_json("https://example.test/item")
    assert data2 == data


class RecordingHTTP:
    def __init__(self):
        self.urls = []

    def get_json(self, url: str, use_cache: bool = True):
        self.urls.append(url)
        return {"primaryAccession": "P0CG47"}, "d" * 64

    def get_text(self, url: str, use_cache: bool = True):
        self.urls.append(url)
        return "<article/>", "e" * 64


def test_resource_clients_build_documented_urls() -> None:
    http = RecordingHTTP()
    _, _, epmc_url = EuropePMCClient(http).full_text_xml("pmc1")
    _, _, pdbe_url = PDBeClient(http).entry_summary("1UBQ")
    _, _, mapping_url = PDBeClient(http).uniprot_mapping("1UBQ")
    _, _, uniprot_url = UniProtClient(http).entry("p0cg47")
    assert epmc_url.endswith("/PMC1/fullTextXML")
    assert pdbe_url.endswith("/pdb/entry/summary/1ubq")
    assert mapping_url.endswith("/mappings/uniprot/1ubq")
    assert uniprot_url.endswith("/P0CG47.json")


def test_cli_schema_extract_and_evaluate(tmp_path: Path) -> None:
    runner = CliRunner()
    schema_path = tmp_path / "schema.json"
    result = runner.invoke(app, ["schema", "--output", str(schema_path)])
    assert result.exit_code == 0
    assert "properties" in json.loads(schema_path.read_text())

    output_dir = tmp_path / "run"
    result = runner.invoke(
        app,
        [
            "extract",
            "--xml",
            "data/demo/article.xml",
            "--document-id",
            "DOC",
            "--source-uri",
            "synthetic://doc",
            "--output-dir",
            str(output_dir),
        ],
    )
    assert result.exit_code == 0
    evaluation_path = tmp_path / "evaluation.json"
    result = runner.invoke(
        app,
        [
            "evaluate",
            "--record",
            str(output_dir / "record.json"),
            "--gold",
            "data/demo/gold.json",
            "--output",
            str(evaluation_path),
        ],
    )
    assert result.exit_code == 0
    assert json.loads(evaluation_path.read_text())["f1"] == 1.0
