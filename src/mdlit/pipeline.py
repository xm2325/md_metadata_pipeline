from __future__ import annotations

import json
from pathlib import Path

from .extraction import DeterministicExtractor, Extractor
from .extraction_v2 import ProtocolAwareExtractor
from .jats import parse_jats
from .models import ArticleMetadata, MDRecord
from .protocol import build_protocol_events
from .report import write_html_report
from .storage import write_sqlite
from .validation import validate_live, validate_semantics


def run_pipeline(
    xml_path: str | Path,
    document_id: str,
    source_uri: str,
    output_dir: str | Path,
    live_validation: bool = False,
    extractor: Extractor | None = None,
    extractor_version: str = "v2",
) -> MDRecord:
    parsed = parse_jats(xml_path)
    if extractor is None:
        extractor = (
            ProtocolAwareExtractor() if extractor_version == "v2" else DeterministicExtractor()
        )
    facts = extractor.extract(parsed.paragraphs, document_id=document_id, source_uri=source_uri)
    record = MDRecord(
        article=ArticleMetadata(
            document_id=document_id,
            title=parsed.title,
            doi=parsed.doi,
            pmcid=parsed.pmcid,
            source_uri=source_uri,
        ),
        facts=facts,
        protocol_events=build_protocol_events(facts),
    )
    validate_semantics(record)
    if live_validation:
        validate_live(record)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "record.json").write_text(record.model_dump_json(indent=2), encoding="utf-8")
    (output_dir / "protocol_events.json").write_text(
        json.dumps(
            [event.model_dump(mode="json") for event in record.protocol_events],
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (output_dir / "mddb_partial.json").write_text(
        json.dumps(record.to_mddb_partial(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    write_sqlite(record, output_dir / "audit.sqlite")
    write_html_report(record, output_dir / "report.html")
    return record
