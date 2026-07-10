from pathlib import Path

import pytest
from pydantic import ValidationError

from mdlit.extraction import DeterministicExtractor
from mdlit.jats import parse_jats
from mdlit.models import ArticleMetadata, EvidenceSpan, MDRecord


def test_evidence_rejects_inconsistent_offsets() -> None:
    with pytest.raises(ValidationError):
        EvidenceSpan(
            document_id="d",
            source_uri="s",
            section="m",
            paragraph_id="p",
            start_char=0,
            end_char=3,
            quote="abcd",
            context_sha256="a" * 64,
        )


def test_mddb_partial_is_labelled() -> None:
    article = parse_jats(Path("data/demo/article.xml"))
    facts = DeterministicExtractor().extract(article.paragraphs, "DOC", "synthetic://doc")
    record = MDRecord(
        article=ArticleMetadata(document_id="DOC", source_uri="synthetic://doc"), facts=facts
    )
    export = record.to_mddb_partial()
    assert export["_export_status"] == "partial_not_ingestion_ready"
    assert export["PROGRAM"] == "GROMACS"
    assert export["PDBIDS"] == ["1UBQ"]
