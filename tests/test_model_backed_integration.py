from __future__ import annotations

import hashlib

import pytest

from mdmeta.benchmark import canonical_sha256
from mdmeta.llm_adapter import SchemaConstrainedEventExtractor
from mdmeta.protocol_events import Paragraph
from scripts.run_model_backed_integration import (
    _prediction_commitment,
    _validated_event_map,
)


def _committed_prediction(core: dict) -> dict:
    return {**core, "result_sha256": canonical_sha256(core)}


def test_prediction_commitment_detects_mutation() -> None:
    payload = _committed_prediction({"schema_version": "test", "status": "pass"})
    assert _prediction_commitment(payload) == payload["result_sha256"]

    with pytest.raises(ValueError, match="commitment"):
        _prediction_commitment({**payload, "status": "failed"})


def test_maps_only_exact_task_bound_events_to_the_jats_paragraph() -> None:
    text = "Production MD simulations were run for 100 ns."
    context_sha256 = hashlib.sha256(text.encode()).hexdigest()
    xml_bytes = f"""\
<article><body><sec><title>Methods</title>
  <p id="p1">{text}</p>
</sec></body></article>
""".encode()
    revision = "a" * 40
    model_label = f"test/tiny@{revision}"
    response = {
        "events": [
            {
                "event_type": "production",
                "paragraph_id": "p1",
                "start_char": 0,
                "end_char": len(text),
                "quote": text,
                "duration": {"raw_text": "100 ns", "value": 100, "unit": "ns"},
                "confidence": 0.9,
            }
        ]
    }
    paragraph = Paragraph("PMC1", "Methods", "p1", text)
    event = SchemaConstrainedEventExtractor(  # type: ignore[arg-type]
        None,
        model_label,
    ).validate_response([paragraph], response)[0].model_dump(mode="json")
    prompt = SchemaConstrainedEventExtractor.build_prompt([paragraph])
    split = "development"
    task_id = hashlib.sha256(
        "|".join(("PMC1", split, "Methods", "p1", context_sha256)).encode()
    ).hexdigest()
    prediction = {
        "model": {
            "repo_id": "test/tiny",
            "revision": revision,
            "tokenizer_revision": revision,
        },
        "batch": {
            "tasks": [
                {
                    "task_id": task_id,
                    "document_id": "PMC1",
                    "split": split,
                    "section": "Methods",
                    "paragraph_id": "p1",
                    "context_sha256": context_sha256,
                    "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                    "response_sha256": canonical_sha256(response),
                    "response": response,
                    "classification": "accepted",
                    "event_count": 1,
                    "events": [event],
                }
            ]
        }
    }

    events_by_key, classifications = _validated_event_map(
        prediction,
        {"PMC1": xml_bytes},
        {"PMC1": split},
    )

    key = ("PMC1", "Methods", "p1", context_sha256)
    assert [item.event_id for item in events_by_key[key]] == [event["event_id"]]
    assert classifications == {"accepted": 1}

    prediction["batch"]["tasks"][0]["context_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="task set differs"):
        _validated_event_map(prediction, {"PMC1": xml_bytes}, {"PMC1": split})


def test_schema_invalid_response_cannot_be_relabelled_as_evidence_rejected() -> None:
    text = "Production MD simulations were run for 100 ns."
    context_sha256 = hashlib.sha256(text.encode()).hexdigest()
    xml_bytes = (
        f"<article><body><sec><title>Methods</title><p id='p1'>{text}</p>"
        "</sec></body></article>"
    ).encode()
    paragraph = Paragraph("PMC1", "Methods", "p1", text)
    split = "development"
    revision = "a" * 40
    response = {"events": "not-an-array"}
    task = {
        "task_id": hashlib.sha256(
            "|".join(("PMC1", split, "Methods", "p1", context_sha256)).encode()
        ).hexdigest(),
        "document_id": "PMC1",
        "split": split,
        "section": "Methods",
        "paragraph_id": "p1",
        "context_sha256": context_sha256,
        "prompt_sha256": hashlib.sha256(
            SchemaConstrainedEventExtractor.build_prompt([paragraph]).encode()
        ).hexdigest(),
        "response_sha256": canonical_sha256(response),
        "response": response,
        "classification": "evidence_rejected",
        "event_count": 0,
        "events": [],
    }
    prediction = {
        "model": {
            "repo_id": "test/tiny",
            "revision": revision,
            "tokenizer_revision": revision,
        },
        "batch": {"tasks": [task]},
    }

    with pytest.raises(ValueError, match="not schema-valid"):
        _validated_event_map(
            prediction,
            {"PMC1": xml_bytes},
            {"PMC1": split},
        )
