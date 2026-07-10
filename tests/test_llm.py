from __future__ import annotations

import pytest

from mdlit.jats import Paragraph
from mdlit.llm import EvidenceIntegrityError, SchemaConstrainedLLMExtractor


class FakeBackend:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.prompt = ""
        self.schema: dict = {}

    def complete(self, prompt: str, json_schema: dict) -> dict:
        self.prompt = prompt
        self.schema = json_schema
        return self.response


def test_schema_constrained_llm_accepts_exact_evidence() -> None:
    text = "Production simulations used GROMACS 2024.1 for 100 ns."
    start = text.index("GROMACS")
    backend = FakeBackend(
        {
            "facts": [
                {
                    "field_name": "program",
                    "raw_value": "GROMACS",
                    "normalized_value": "GROMACS",
                    "unit": None,
                    "paragraph_id": "p1",
                    "start_char": start,
                    "end_char": start + len("GROMACS"),
                    "confidence": 0.93,
                }
            ]
        }
    )
    extractor = SchemaConstrainedLLMExtractor(backend, model_id="fake-1")
    facts = extractor.extract(
        [Paragraph("Methods", "p1", text)],
        document_id="PMC1",
        source_uri="https://example.org/PMC1",
    )

    assert facts[0].normalized_value == "GROMACS"
    assert facts[0].method == "schema_constrained_llm:fake-1"
    assert facts[0].evidence[0].quote == "GROMACS"
    assert "Do not infer missing values" in backend.prompt
    assert "facts" in backend.schema["properties"]


def test_schema_constrained_llm_rejects_non_matching_span() -> None:
    text = "Simulations used GROMACS."
    backend = FakeBackend(
        {
            "facts": [
                {
                    "field_name": "program",
                    "raw_value": "AMBER",
                    "normalized_value": "AMBER",
                    "unit": None,
                    "paragraph_id": "p1",
                    "start_char": 17,
                    "end_char": 22,
                    "confidence": 0.8,
                }
            ]
        }
    )
    extractor = SchemaConstrainedLLMExtractor(backend, model_id="fake-1")

    with pytest.raises(EvidenceIntegrityError, match="raw_value"):
        extractor.extract(
            [Paragraph("Methods", "p1", text)],
            document_id="PMC1",
            source_uri="https://example.org/PMC1",
        )


def test_schema_constrained_llm_rejects_unknown_paragraph() -> None:
    backend = FakeBackend(
        {
            "facts": [
                {
                    "field_name": "program",
                    "raw_value": "GROMACS",
                    "normalized_value": "GROMACS",
                    "unit": None,
                    "paragraph_id": "missing",
                    "start_char": 0,
                    "end_char": 7,
                    "confidence": 0.8,
                }
            ]
        }
    )
    extractor = SchemaConstrainedLLMExtractor(backend, model_id="fake-1")

    with pytest.raises(EvidenceIntegrityError, match="Unknown paragraph_id"):
        extractor.extract(
            [Paragraph("Methods", "p1", "GROMACS")],
            document_id="PMC1",
            source_uri="https://example.org/PMC1",
        )


def test_schema_constrained_llm_rejects_inconsistent_normalization() -> None:
    text = "Production simulations used GROMACS."
    start = text.index("GROMACS")
    backend = FakeBackend(
        {
            "facts": [
                {
                    "field_name": "program",
                    "raw_value": "GROMACS",
                    "normalized_value": "AMBER",
                    "unit": None,
                    "paragraph_id": "p1",
                    "start_char": start,
                    "end_char": start + len("GROMACS"),
                    "confidence": 0.8,
                }
            ]
        }
    )
    extractor = SchemaConstrainedLLMExtractor(backend, model_id="fake-1")

    with pytest.raises(EvidenceIntegrityError, match="normalization"):
        extractor.extract(
            [Paragraph("Methods", "p1", text)],
            document_id="PMC1",
            source_uri="https://example.org/PMC1",
        )
