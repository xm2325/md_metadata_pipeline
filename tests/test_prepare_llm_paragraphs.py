import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "prepare_llm_paragraphs.py"
SPEC = importlib.util.spec_from_file_location("prepare_llm_paragraphs", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_prepare_protocol_paragraphs_freezes_hashes_and_selection(tmp_path) -> None:
    xml = tmp_path / "article.xml"
    xml.write_text(
        """
        <article>
          <body>
            <sec><title>Methods</title><p id="m1">A 100 ns production simulation was run.</p></sec>
            <sec><title>Results</title><p id="r1">The structure remained stable.</p></sec>
          </body>
        </article>
        """,
        encoding="utf-8",
    )
    output = tmp_path / "paragraphs.jsonl"
    manifest_path = tmp_path / "manifest.json"
    result = MODULE.run(
        [("DOC1", xml)],
        output,
        manifest_path,
        protocol_only=True,
    )
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert [row["paragraph_id"] for row in rows] == ["m1"]
    assert result["article_count"] == 1
    assert result["paragraph_count"] == 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["output_sha256"] == result["output_sha256"]
    assert len(manifest["sources"][0]["xml_sha256"]) == 64


def test_prepare_rejects_duplicate_document_ids(tmp_path) -> None:
    xml = tmp_path / "article.xml"
    xml.write_text(
        "<article><body><sec><title>Methods</title><p>MD simulation.</p></sec></body></article>",
        encoding="utf-8",
    )
    try:
        MODULE.run(
            [("DOC1", xml), ("DOC1", xml)],
            tmp_path / "out.jsonl",
            tmp_path / "manifest.json",
            protocol_only=False,
        )
    except ValueError as exc:
        assert "duplicate document_id" in str(exc)
    else:
        raise AssertionError("duplicate document identifier was accepted")
