import pytest

from mdmeta.llm_adapter import EvidenceIntegrityError, SchemaConstrainedEventExtractor
from mdmeta.models import EventType
from mdmeta.protocol_events import Paragraph


class FakeBackend:
    model_id = "fake-model"

    def __init__(self, payload):
        self.payload = payload
        self.prompt = ""
        self.schema = {}
        self.last_audit = None

    def complete(self, prompt, json_schema):
        self.prompt = prompt
        self.schema = json_schema
        self.last_audit = {"model_id": self.model_id, "request_id": "fake-request"}
        return self.payload


def _paragraph():
    text = (
        "The production simulation was run for 100 ns at 300 K and 1 bar in the NPT "
        "ensemble with a 2 fs time step using three replicates."
    )
    return Paragraph("PMC1", "Methods", "p1", text)


def _payload(paragraph):
    return {
        "events": [
            {
                "event_type": "production",
                "paragraph_id": "p1",
                "start_char": 0,
                "end_char": len(paragraph.text),
                "quote": paragraph.text,
                "duration": {"raw_text": "100 ns", "value": 100, "unit": "ns"},
                "temperature": {"raw_text": "300 K", "value": 300, "unit": "K"},
                "pressure": {"raw_text": "1 bar", "value": 1, "unit": "bar"},
                "timestep": {"raw_text": "2 fs", "value": 2, "unit": "fs"},
                "ensemble": "NPT",
                "restraints": None,
                "replicates": {"raw_text": "three", "value": 3},
                "confidence": 0.91,
            }
        ]
    }


def test_accepts_exact_evidence_and_normalizes_units():
    paragraph = _paragraph()
    backend = FakeBackend(_payload(paragraph))
    extractor = SchemaConstrainedEventExtractor(backend)
    events = extractor.extract([paragraph])
    assert len(events) == 1
    event = events[0]
    assert event.event_type is EventType.PRODUCTION
    assert event.duration_ps == 100_000
    assert event.temperature_k == 300
    assert event.pressure_bar == 1
    assert event.timestep_fs == 2
    assert event.ensemble == "NPT"
    assert event.replicates == 3
    assert event.evidence[0].quote == paragraph.text
    assert (
        event.relation_method
        == "schema_constrained_llm:fake-model:md-protocol-events-exact-span-v2"
    )
    assert "Do not infer missing values" in backend.prompt
    assert "Distinguish simulated duration" in backend.prompt
    assert "events" in backend.schema["properties"]
    assert extractor.last_audit == {"model_id": "fake-model", "request_id": "fake-request"}


def test_rejects_quote_that_does_not_match_offsets():
    paragraph = _paragraph()
    payload = _payload(paragraph)
    payload["events"][0]["start_char"] = 1
    with pytest.raises(EvidenceIntegrityError, match="quote"):
        SchemaConstrainedEventExtractor(FakeBackend(payload), "fake").extract([paragraph])


def test_rejects_quantity_value_inconsistent_with_raw_text():
    paragraph = _paragraph()
    payload = _payload(paragraph)
    payload["events"][0]["duration"]["value"] = 200
    with pytest.raises(EvidenceIntegrityError, match="value disagrees"):
        SchemaConstrainedEventExtractor(FakeBackend(payload), "fake").extract([paragraph])


def test_rejects_quantity_not_present_in_quote():
    paragraph = _paragraph()
    payload = _payload(paragraph)
    payload["events"][0]["pressure"] = {"raw_text": "2 bar", "value": 2, "unit": "bar"}
    with pytest.raises(EvidenceIntegrityError, match="not present"):
        SchemaConstrainedEventExtractor(FakeBackend(payload), "fake").extract([paragraph])


def test_rejects_unknown_paragraph():
    paragraph = _paragraph()
    payload = _payload(paragraph)
    payload["events"][0]["paragraph_id"] = "missing"
    with pytest.raises(EvidenceIntegrityError, match="unknown paragraph_id"):
        SchemaConstrainedEventExtractor(FakeBackend(payload), "fake").extract([paragraph])


def test_rejects_empty_event():
    paragraph = _paragraph()
    payload = _payload(paragraph)
    event = payload["events"][0]
    for field in (
        "duration",
        "temperature",
        "pressure",
        "timestep",
        "ensemble",
        "restraints",
        "replicates",
    ):
        event[field] = None
    with pytest.raises(EvidenceIntegrityError, match="no protocol attribute"):
        SchemaConstrainedEventExtractor(FakeBackend(payload), "fake").extract([paragraph])
