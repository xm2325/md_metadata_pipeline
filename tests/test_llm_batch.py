from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from mdmeta.benchmark import canonical_sha256
from mdmeta.llm_adapter import SchemaConstrainedEventExtractor
from mdmeta.llm_batch import (
    FrozenArticle,
    fetch_frozen_jats,
    run_model_batch,
    select_articles,
    validate_source_manifest,
)


def _article(document_id: str, xml_bytes: bytes = b"<article />") -> dict[str, str]:
    return {
        "document_id": document_id,
        "split": "development",
        "source_uri": f"https://europepmc.org/articles/{document_id}",
        "full_text_sha256": hashlib.sha256(xml_bytes).hexdigest(),
    }


def _manifest(*rows: dict[str, str]) -> dict:
    core = {
        "schema_version": "test.frozen-jats.v1",
        "articles": list(rows),
    }
    return {**core, "manifest_sha256": canonical_sha256(core)}


def test_manifest_commitment_and_explicit_selection_are_deterministic() -> None:
    payload = _manifest(_article("PMC1"), _article("PMC2"), _article("PMC3"))
    articles = validate_source_manifest(payload)

    selected = select_articles(articles, document_ids=["pmc3", "PMC1"])

    assert [article.document_id for article in selected] == ["PMC3", "PMC1"]
    assert [article.document_id for article in select_articles(articles, limit=1)] == ["PMC1"]
    with pytest.raises(ValueError, match="mutually exclusive"):
        select_articles(articles, document_ids=["PMC1"], limit=1)
    with pytest.raises(ValueError, match="only 3"):
        select_articles(articles, limit=4)
    with pytest.raises(ValueError, match="commitment"):
        validate_source_manifest({**payload, "schema_version": "tampered"})
    with pytest.raises(ValueError, match="absent"):
        select_articles(articles, document_ids=["PMC999"])


class _NoNetworkClient:
    def get(self, endpoint: str):
        raise AssertionError(f"cache hit unexpectedly used the network: {endpoint}")


def test_frozen_jats_cache_requires_the_manifest_hash(tmp_path: Path) -> None:
    xml_bytes = b"<article><body><sec><title>Methods</title></sec></body></article>"
    article = FrozenArticle.model_validate(_article("PMC42", xml_bytes))
    cache_dir = tmp_path / "jats"
    cache_dir.mkdir()
    cached_path = cache_dir / "PMC42.xml"
    cached_path.write_bytes(xml_bytes)

    observed, cache_hit = fetch_frozen_jats(
        article,
        cache_dir=cache_dir,
        client=_NoNetworkClient(),
    )

    assert observed == xml_bytes
    assert cache_hit is True
    cached_path.write_bytes(xml_bytes + b"tampered")
    with pytest.raises(ValueError, match="cached JATS SHA-256 mismatch"):
        fetch_frozen_jats(
            article,
            cache_dir=cache_dir,
            client=_NoNetworkClient(),
        )


class _FakeBatchBackend:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = responses
        self.calls: list[tuple[list[str], dict]] = []
        self.last_batch_metadata = [
            {"prompt_tokens": 10, "completion_tokens": 2},
            {"prompt_tokens": 11, "completion_tokens": 3},
            {"prompt_tokens": 12, "completion_tokens": 4},
        ]

    def complete_many(self, prompts: list[str], json_schema: dict) -> list[dict]:
        self.calls.append((prompts, json_schema))
        return self.responses


def test_model_batch_classifies_every_task_without_silent_dropping() -> None:
    accepted_text = "Production MD simulations were run for 100 ns."
    schema_rejected_text = "Equilibration was performed at 300 K."
    evidence_rejected_text = "Coordinates were sampled every 10 ps."
    xml_bytes = f"""\
<article><body>
  <sec><title>Methods</title>
    <p id="p1">{accepted_text}</p>
    <p id="p2">{schema_rejected_text}</p>
    <p id="p3">{evidence_rejected_text}</p>
  </sec>
</body></article>
""".encode()
    article = FrozenArticle.model_validate(_article("PMC7", xml_bytes))
    responses = [
        {
            "events": [
                {
                    "event_type": "production",
                    "paragraph_id": "p1",
                    "start_char": 0,
                    "end_char": len(accepted_text),
                    "quote": accepted_text,
                    "duration": {
                        "raw_text": "100 ns",
                        "value": 100,
                        "unit": "ns",
                    },
                    "confidence": 0.9,
                }
            ]
        },
        {"events": "not-an-array"},
        {
            "events": [
                {
                    "event_type": "sampling_interval",
                    "paragraph_id": "p3",
                    "start_char": 0,
                    "end_char": 5,
                    "quote": "10 ps",
                    "duration": {
                        "raw_text": "10 ps",
                        "value": 10,
                        "unit": "ps",
                    },
                    "confidence": 0.8,
                }
            ]
        },
    ]
    backend = _FakeBatchBackend(responses)
    extractor = SchemaConstrainedEventExtractor(backend, "fake-pinned-model")
    checkpoints: list[dict] = []

    result = run_model_batch(
        backend=backend,
        extractor=extractor,
        articles=[article],
        xml_by_document={"PMC7": xml_bytes},
        batch_size=3,
        determinism_check=False,
        checkpoint=checkpoints.append,
    )

    assert result["task_count"] == 3
    assert result["task_count_classified"] == 3
    assert result["classification_counts"] == {
        "accepted": 1,
        "evidence_rejected": 1,
        "schema_rejected": 1,
    }
    assert [task["classification"] for task in result["tasks"]] == [
        "accepted",
        "schema_rejected",
        "evidence_rejected",
    ]
    assert result["event_count"] == 1
    assert result["phase_counts"] == {"production": 1}
    assert result["usage"]["total_tokens"] == 42
    assert result["per_article"]["PMC7"] == {
        "split": "development",
        "paragraph_count": 3,
        "accepted_paragraph_count": 1,
        "rejected_paragraph_count": 2,
        "event_count": 1,
        "event_bearing_paragraph_count": 1,
    }
    assert len(backend.calls) == 1
    assert checkpoints[-1]["task_count_classified"] == 3
    assert checkpoints[-1]["status"] == "running"
