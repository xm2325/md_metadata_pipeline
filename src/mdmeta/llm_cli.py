from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .llm_adapter import PROMPT_VERSION, SchemaConstrainedEventExtractor
from .models import ProtocolEvent
from .openai_backend import OpenAICompatibleStructuredBackend
from .protocol_events import Paragraph


class InputParagraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1)
    section: str = Field(min_length=1)
    paragraph_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class DocumentExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    paragraph_count: int = Field(ge=1)
    event_count: int = Field(ge=0)
    events: list[ProtocolEvent]


class LLMExtractionRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "llm-protocol-extraction-run-v1"
    prompt_version: str
    model_id: str
    created_at: datetime
    source_filename: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_count: int = Field(ge=0)
    paragraph_count: int = Field(ge=0)
    event_count: int = Field(ge=0)
    completions: list[dict[str, object]]
    documents: list[DocumentExtraction]


def _load_jsonl(path: Path) -> list[InputParagraph]:
    rows: list[InputParagraph] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON on line {line_number}") from exc
        rows.append(InputParagraph.model_validate(payload))
    return rows


def _group(rows: list[InputParagraph]) -> OrderedDict[str, list[Paragraph]]:
    grouped: OrderedDict[str, list[Paragraph]] = OrderedDict()
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row.document_id, row.paragraph_id)
        if key in seen:
            raise ValueError(
                f"duplicate paragraph_id within document: {row.document_id}/{row.paragraph_id}"
            )
        seen.add(key)
        grouped.setdefault(row.document_id, []).append(
            Paragraph(row.document_id, row.section, row.paragraph_id, row.text)
        )
    return grouped


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def run(input_path: Path, output_path: Path, *, max_paragraphs_per_request: int) -> LLMExtractionRun:
    if max_paragraphs_per_request < 1:
        raise ValueError("max_paragraphs_per_request must be positive")
    source_bytes = input_path.read_bytes()
    rows = _load_jsonl(input_path)
    grouped = _group(rows)
    documents: list[DocumentExtraction] = []
    completions: list[dict[str, object]] = []

    with OpenAICompatibleStructuredBackend.from_env() as backend:
        extractor = SchemaConstrainedEventExtractor(backend)
        for document_id, paragraphs in grouped.items():
            events: list[ProtocolEvent] = []
            for start in range(0, len(paragraphs), max_paragraphs_per_request):
                chunk = paragraphs[start : start + max_paragraphs_per_request]
                events.extend(extractor.extract(chunk))
                if extractor.last_audit is not None:
                    completions.append(extractor.last_audit)
            unique = {event.event_id: event for event in events}
            ordered_events = [unique[event_id] for event_id in sorted(unique)]
            documents.append(
                DocumentExtraction(
                    document_id=document_id,
                    paragraph_count=len(paragraphs),
                    event_count=len(ordered_events),
                    events=ordered_events,
                )
            )
        model_id = backend.model_id

    result = LLMExtractionRun(
        prompt_version=PROMPT_VERSION,
        model_id=model_id,
        created_at=datetime.now(timezone.utc),
        source_filename=input_path.name,
        source_sha256=hashlib.sha256(source_bytes).hexdigest(),
        document_count=len(documents),
        paragraph_count=len(rows),
        event_count=sum(document.event_count for document in documents),
        completions=completions,
        documents=documents,
    )
    _atomic_write(output_path, result.model_dump_json(indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run evidence-checked MD protocol extraction through an OpenAI-compatible LLM."
    )
    parser.add_argument("--input", type=Path, required=True, help="JSONL paragraph input")
    parser.add_argument("--output", type=Path, required=True, help="Audited JSON result")
    parser.add_argument("--max-paragraphs-per-request", type=int, default=8)
    args = parser.parse_args()
    result = run(
        args.input,
        args.output,
        max_paragraphs_per_request=args.max_paragraphs_per_request,
    )
    print(
        json.dumps(
            {
                "model_id": result.model_id,
                "documents": result.document_count,
                "paragraphs": result.paragraph_count,
                "events": result.event_count,
                "output": str(args.output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
