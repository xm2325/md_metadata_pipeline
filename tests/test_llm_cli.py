import json

from mdmeta import llm_cli


class FakeBackend:
    model_id = "Qwen/Qwen3.6-27B"

    def __init__(self):
        self.last_audit = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def complete(self, prompt, json_schema):
        text = "The production simulation was run for 100 ns at 300 K in the NPT ensemble."
        self.last_audit = {
            "model_id": self.model_id,
            "prompt_sha256": "a" * 64,
            "schema_sha256": "b" * 64,
            "response_sha256": "c" * 64,
        }
        return {
            "events": [
                {
                    "event_type": "production",
                    "paragraph_id": "p1",
                    "start_char": 0,
                    "end_char": len(text),
                    "quote": text,
                    "duration": {"raw_text": "100 ns", "value": 100, "unit": "ns"},
                    "temperature": {"raw_text": "300 K", "value": 300, "unit": "K"},
                    "pressure": None,
                    "timestep": None,
                    "ensemble": "NPT",
                    "restraints": None,
                    "replicates": None,
                    "confidence": 0.8,
                }
            ]
        }


def test_cli_groups_paragraphs_and_writes_audited_output(monkeypatch, tmp_path):
    text = "The production simulation was run for 100 ns at 300 K in the NPT ensemble."
    input_path = tmp_path / "paragraphs.jsonl"
    output_path = tmp_path / "events.json"
    input_path.write_text(
        json.dumps(
            {
                "document_id": "PMC1",
                "section": "Methods",
                "paragraph_id": "p1",
                "text": text,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    fake = FakeBackend()
    monkeypatch.setattr(
        llm_cli.OpenAICompatibleStructuredBackend,
        "from_env",
        classmethod(lambda cls: fake),
    )

    result = llm_cli.run(input_path, output_path, max_paragraphs_per_request=8)

    assert result.model_id == "Qwen/Qwen3.6-27B"
    assert result.document_count == 1
    assert result.paragraph_count == 1
    assert result.event_count == 1
    assert len(result.completions) == 1
    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written["source_filename"] == "paragraphs.jsonl"
    assert written["documents"][0]["events"][0]["duration_ps"] == 100000.0
    assert "The production simulation" not in json.dumps(written["completions"])
