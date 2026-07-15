import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

from mdmeta.llm_adapter import (
    EvidenceIntegrityError,
    SchemaConstrainedEventExtractor,
    StructuredOutputError,
    VLLMStructuredBackend,
)
from mdmeta.models import EventType
from mdmeta.protocol_events import Paragraph


class FakeBackend:
    def __init__(self, payload):
        self.payload = payload
        self.prompt = ""
        self.schema = {}

    def complete(self, prompt, json_schema):
        self.prompt = prompt
        self.schema = json_schema
        return self.payload


class FakeBatchBackend(FakeBackend):
    def __init__(self, payloads):
        super().__init__(None)
        self.payloads = payloads
        self.prompts = []

    def complete_many(self, prompts, json_schema):
        self.prompts = prompts
        self.schema = json_schema
        return self.payloads


def _install_fake_vllm(monkeypatch, response_texts, *, version="0.19.1"):
    class FakeStructuredOutputsParams:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeSamplingParams:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeLLM:
        instances = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.chat_calls = []
            self.instances.append(self)

        def get_tokenizer(self):
            class FakeTokenizer:
                @staticmethod
                def apply_chat_template(conversation, *, tokenize, add_generation_prompt):
                    assert tokenize is True
                    assert add_generation_prompt is True
                    content = conversation[0]["content"]
                    return list(range(len(content.split()) + 2))

            return FakeTokenizer()

        def chat(self, conversations, *, sampling_params, use_tqdm):
            self.chat_calls.append((conversations, sampling_params, use_tqdm))
            return [
                SimpleNamespace(
                    prompt_token_ids=list(range(index + 3)),
                    outputs=[
                        SimpleNamespace(
                            text=text,
                            token_ids=list(range(index + 2)),
                            finish_reason="stop",
                        )
                    ],
                )
                for index, text in enumerate(response_texts)
            ]

    vllm_module = ModuleType("vllm")
    vllm_module.__version__ = version
    vllm_module.LLM = FakeLLM
    vllm_module.SamplingParams = FakeSamplingParams
    sampling_module = ModuleType("vllm.sampling_params")
    sampling_module.StructuredOutputsParams = FakeStructuredOutputsParams
    vllm_module.sampling_params = sampling_module
    monkeypatch.setitem(sys.modules, "vllm", vllm_module)
    monkeypatch.setitem(sys.modules, "vllm.sampling_params", sampling_module)
    return FakeLLM


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
                "event_type_raw_text": "production simulation",
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
    events = SchemaConstrainedEventExtractor(backend, "fake-model").extract([paragraph])
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
    assert event.relation_method == "schema_constrained_llm:fake-model:exact_span_v1"
    assert "Do not infer missing values" in backend.prompt
    assert "event_type_raw_text" in backend.prompt
    assert "never invent placeholders" in backend.prompt
    assert "Never emit a separate phase-only or duplicate event" in backend.prompt
    assert "never return an event with all protocol attributes null" in backend.prompt
    assert "populate every supported protocol attribute" in backend.prompt
    assert "'80 ns' into duration" in backend.prompt
    assert "'NPT' into ensemble" in backend.prompt
    assert "'no restrictions' into restraints" in backend.prompt
    assert "events" in backend.schema["properties"]


def test_repairs_offsets_for_one_unique_exact_quote_without_mutating_response():
    paragraph = _paragraph()
    payload = _payload(paragraph)
    payload["events"][0]["start_char"] = 1
    payload["events"][0]["end_char"] = 9
    original = json.loads(json.dumps(payload))

    event = SchemaConstrainedEventExtractor(FakeBackend(payload), "fake").extract([paragraph])[0]

    assert event.evidence[0].start_char == 0
    assert event.evidence[0].end_char == len(paragraph.text)
    assert event.relation_method.endswith("unique_exact_quote_offset_repair_v1")
    assert payload == original


def test_rejects_quote_that_is_not_present_in_paragraph():
    paragraph = _paragraph()
    payload = _payload(paragraph)
    payload["events"][0]["quote"] = "Production ran for 100 ns."
    with pytest.raises(EvidenceIntegrityError, match="not present"):
        SchemaConstrainedEventExtractor(FakeBackend(payload), "fake").extract([paragraph])


def test_rejects_ambiguous_quote_when_offsets_do_not_disambiguate():
    quote = "Production MD ran for 100 ns."
    paragraph = Paragraph("PMC1", "Methods", "p1", f"{quote} Then {quote}")
    payload = {
        "events": [
            {
                "event_type": "production",
                "event_type_raw_text": "Production",
                "paragraph_id": "p1",
                "start_char": 1,
                "end_char": 9,
                "quote": quote,
                "duration": {"raw_text": "100 ns", "value": 100, "unit": "ns"},
                "confidence": 0.9,
            }
        ]
    }
    with pytest.raises(EvidenceIntegrityError, match="ambiguous"):
        SchemaConstrainedEventExtractor(FakeBackend(payload), "fake").extract([paragraph])


def test_valid_offsets_disambiguate_a_repeated_exact_quote():
    quote = "Production MD ran for 100 ns."
    paragraph = Paragraph("PMC1", "Methods", "p1", f"{quote} Then {quote}")
    start = len(quote) + len(" Then ")
    payload = {
        "events": [
            {
                "event_type": "production",
                "event_type_raw_text": "Production",
                "paragraph_id": "p1",
                "start_char": start,
                "end_char": start + len(quote),
                "quote": quote,
                "duration": {"raw_text": "100 ns", "value": 100, "unit": "ns"},
                "confidence": 0.9,
            }
        ]
    }

    event = SchemaConstrainedEventExtractor(FakeBackend(payload), "fake").extract([paragraph])[0]

    assert event.evidence[0].start_char == start
    assert event.relation_method.endswith("exact_span_v1")


def test_rejects_event_type_that_disagrees_with_exact_source_cue():
    paragraph = _paragraph()
    payload = _payload(paragraph)
    payload["events"][0]["event_type"] = "minimisation"
    with pytest.raises(EvidenceIntegrityError, match="event_type disagrees"):
        SchemaConstrainedEventExtractor(FakeBackend(payload), "fake").extract([paragraph])


@pytest.mark.parametrize(
    ("event_type", "event_type_raw_text", "text"),
    [
        ("production", "reproduction", "Protein reproduction was observed for 100 ns."),
        ("heating", "wheat", "The wheat model was observed for 100 ns."),
    ],
)
def test_event_type_cues_require_word_boundaries(event_type, event_type_raw_text, text):
    paragraph = Paragraph("PMC1", "Methods", "p1", text)
    payload = {
        "events": [
            {
                "event_type": event_type,
                "event_type_raw_text": event_type_raw_text,
                "paragraph_id": "p1",
                "start_char": 0,
                "end_char": len(text),
                "quote": text,
                "duration": {"raw_text": "100 ns", "value": 100, "unit": "ns"},
                "confidence": 0.9,
            }
        ]
    }
    with pytest.raises(EvidenceIntegrityError, match="event_type disagrees"):
        SchemaConstrainedEventExtractor(FakeBackend(payload), "fake").extract([paragraph])


def test_generic_production_word_requires_molecular_simulation_context():
    text = "Protein production continued for 100 ns."
    paragraph = Paragraph("PMC1", "Methods", "p1", text)
    payload = {
        "events": [
            {
                "event_type": "production",
                "event_type_raw_text": "production",
                "paragraph_id": "p1",
                "start_char": 0,
                "end_char": len(text),
                "quote": text,
                "duration": {"raw_text": "100 ns", "value": 100, "unit": "ns"},
                "confidence": 0.9,
            }
        ]
    }
    with pytest.raises(EvidenceIntegrityError, match="simulation context"):
        SchemaConstrainedEventExtractor(FakeBackend(payload), "fake").extract([paragraph])


def test_generic_md_execution_phrase_does_not_prove_production_phase():
    text = "Equilibration MD simulations were performed for 100 ns."
    paragraph = Paragraph("PMC1", "Methods", "p1", text)
    payload = {
        "events": [
            {
                "event_type": "production",
                "event_type_raw_text": "MD simulations were performed",
                "paragraph_id": "p1",
                "start_char": 0,
                "end_char": len(text),
                "quote": text,
                "duration": {"raw_text": "100 ns", "value": 100, "unit": "ns"},
                "confidence": 0.9,
            }
        ]
    }
    with pytest.raises(EvidenceIntegrityError, match="event_type disagrees"):
        SchemaConstrainedEventExtractor(FakeBackend(payload), "fake").extract([paragraph])


@pytest.mark.parametrize(
    ("event_type", "event_type_raw_text", "text", "raw_duration"),
    [
        ("heating", "heat the system", "We heat the system for 100 ps.", "100 ps"),
        (
            "equilibration",
            "equilibrium phase",
            "The equilibrium phase lasted 100 ps.",
            "100 ps",
        ),
        (
            "sampling_interval",
            "stored",
            "Coordinates were stored every 10 ps.",
            "10 ps",
        ),
        (
            "sampling_interval",
            "collected",
            "Coordinates were collected every 10 ps.",
            "10 ps",
        ),
    ],
)
def test_accepts_explicit_conservative_phase_synonyms(
    event_type,
    event_type_raw_text,
    text,
    raw_duration,
):
    paragraph = Paragraph("PMC1", "Methods", "p1", text)
    value, unit = raw_duration.split()
    payload = {
        "events": [
            {
                "event_type": event_type,
                "event_type_raw_text": event_type_raw_text,
                "paragraph_id": "p1",
                "start_char": 0,
                "end_char": len(text),
                "quote": text,
                "duration": {"raw_text": raw_duration, "value": int(value), "unit": unit},
                "confidence": 0.9,
            }
        ]
    }

    event = SchemaConstrainedEventExtractor(FakeBackend(payload), "fake").extract([paragraph])[0]

    assert event.event_type.value == event_type


@pytest.mark.parametrize("restraints", ["", "   "])
def test_rejects_blank_restraints(restraints):
    paragraph = _paragraph()
    payload = _payload(paragraph)
    payload["events"][0]["restraints"] = restraints
    with pytest.raises(ValueError, match="restraints"):
        SchemaConstrainedEventExtractor(FakeBackend(payload), "fake").extract([paragraph])


def test_accepts_nonblank_restraints_only_when_exactly_present_in_quote():
    text = "Production MD was run for 100 ns with no restrictions."
    paragraph = Paragraph("PMC1", "Methods", "p1", text)
    payload = {
        "events": [
            {
                "event_type": "production",
                "event_type_raw_text": "Production",
                "paragraph_id": "p1",
                "start_char": 0,
                "end_char": len(text),
                "quote": text,
                "duration": {"raw_text": "100 ns", "value": 100, "unit": "ns"},
                "restraints": "no restrictions",
                "confidence": 0.9,
            }
        ]
    }

    event = SchemaConstrainedEventExtractor(FakeBackend(payload), "fake").extract([paragraph])[0]

    assert event.restraints == "no restrictions"


def test_filters_unsupported_attributes_but_keeps_exact_supported_duration():
    production_quote = (
        "The production run was performed in NPT ensemble (constant number of particles, "
        "pressure, and temperature) with no restrictions for 80 ns."
    )
    equilibration_quote = (
        "MD simulation of all complexes was performed in a solvent environment to reach an "
        "equilibrate state."
    )
    text = f"{production_quote} {equilibration_quote} The temperature was set to 310 K."
    paragraph = Paragraph("PMC1", "Methods", "p1", text)
    response = {
        "events": [
            {
                "event_type": "production",
                "event_type_raw_text": "with no restrictions for 80 ns",
                "paragraph_id": "p1",
                "start_char": 100,
                "end_char": 101,
                "quote": production_quote,
                "duration": {"raw_text": "80 ns", "value": 80, "unit": "ns"},
                "temperature": {"raw_text": "310 K", "value": 310, "unit": "K"},
                "restraints": "N",
                "confidence": 1,
            },
            {
                "event_type": "unknown",
                "event_type_raw_text": "MD simulation",
                "paragraph_id": "p1",
                "start_char": len(production_quote) + 1,
                "end_char": len(production_quote) + 1 + len(equilibration_quote),
                "quote": equilibration_quote,
                "restraints": "N",
                "confidence": 1,
            },
        ]
    }

    extractor = SchemaConstrainedEventExtractor(FakeBackend(response), "fake")
    audit = extractor.validate_response_with_audit([paragraph], response)

    assert len(audit.events) == 1
    event = audit.events[0]
    assert event.event_type is EventType.PRODUCTION
    assert event.duration_ps == 80_000
    assert event.temperature_k is None
    assert event.restraints is None
    assert {row["field"] for row in audit.attribute_rejections} == {
        "temperature",
        "restraints",
    }
    assert [row["reason_code"] for row in audit.candidate_rejections] == [
        "unknown_phase_conflicts_with_explicit_cue"
    ]
    assert {row["reason_code"] for row in audit.repairs} == {
        "unique_exact_quote_offset_repair_v1",
        "unique_quote_phase_cue_repair_v1",
    }
    assert extractor.validate_response([paragraph], response) == audit.events


def test_one_character_restraint_cue_cannot_create_an_event():
    text = "MD simulation was performed using NAMD."
    paragraph = Paragraph("PMC1", "Methods", "p1", text)
    response = {
        "events": [
            {
                "event_type": "unknown",
                "event_type_raw_text": "MD simulation",
                "paragraph_id": "p1",
                "start_char": 0,
                "end_char": len(text),
                "quote": text,
                "restraints": "N",
                "confidence": 1,
            }
        ]
    }

    extractor = SchemaConstrainedEventExtractor(FakeBackend(response), "fake")
    audit = extractor.validate_response_with_audit([paragraph], response)

    assert audit.events == []
    assert audit.attribute_rejections[0]["reason_code"] == "restraints_evidence_rejected"
    assert audit.candidate_rejections[0]["reason_code"] == "no_valid_protocol_attribute"
    with pytest.raises(EvidenceIntegrityError, match="no protocol attribute"):
        extractor.validate_response([paragraph], response)


def test_filters_quantity_value_inconsistent_with_raw_text():
    paragraph = _paragraph()
    payload = _payload(paragraph)
    payload["events"][0]["duration"]["value"] = 200
    audit = SchemaConstrainedEventExtractor(
        FakeBackend(payload), "fake"
    ).validate_response_with_audit([paragraph], payload)

    assert audit.events[0].duration_ps is None
    assert audit.attribute_rejections[0]["reason_code"] == "duration_evidence_rejected"
    assert "value disagrees" in audit.attribute_rejections[0]["message"]


def test_filters_quantity_not_present_in_quote():
    paragraph = _paragraph()
    payload = _payload(paragraph)
    payload["events"][0]["pressure"] = {"raw_text": "2 bar", "value": 2, "unit": "bar"}
    audit = SchemaConstrainedEventExtractor(
        FakeBackend(payload), "fake"
    ).validate_response_with_audit([paragraph], payload)

    assert audit.events[0].pressure_bar is None
    assert audit.attribute_rejections[0]["reason_code"] == "pressure_evidence_rejected"
    assert "not present" in audit.attribute_rejections[0]["message"]


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


def test_extract_many_uses_batch_backend_and_separate_validation():
    first = _paragraph()
    second = Paragraph("PMC2", "Results", "p2", "No MD protocol is reported here.")
    backend = FakeBatchBackend([_payload(first), {"events": []}])
    extractor = SchemaConstrainedEventExtractor(backend, "fake-batch")

    events = extractor.extract_many([[first], [second]])

    assert len(events[0]) == 1
    assert events[1] == []
    assert len(backend.prompts) == 2
    assert "paragraph_id=p2" in backend.prompts[1]
    assert "events" in backend.schema["properties"]
    assert extractor.validate_response([second], {"events": []}) == []


def test_vllm_backend_batches_chat_with_deterministic_structured_decoding(monkeypatch):
    fake_llm_type = _install_fake_vllm(
        monkeypatch,
        [json.dumps({"events": []}), json.dumps({"events": []})],
    )
    revision = "a" * 40
    tokenizer_revision = "b" * 40
    backend = VLLMStructuredBackend(
        model="org/pinned-model",
        revision=revision,
        tokenizer_revision=tokenizer_revision,
        max_tokens=512,
        seed=17,
    )

    schema = {"type": "object", "properties": {"events": {"type": "array"}}}
    assert backend.complete_many(["first prompt", "second prompt"], schema) == [
        {"events": []},
        {"events": []},
    ]

    engine = fake_llm_type.instances[-1]
    assert engine.kwargs["revision"] == revision
    assert engine.kwargs["tokenizer_revision"] == tokenizer_revision
    assert engine.kwargs["trust_remote_code"] is False
    conversations, sampling_params, use_tqdm = engine.chat_calls[-1]
    assert conversations == [
        [{"role": "user", "content": "first prompt"}],
        [{"role": "user", "content": "second prompt"}],
    ]
    assert use_tqdm is False
    assert sampling_params.kwargs["temperature"] == 0.0
    assert sampling_params.kwargs["seed"] == 17
    assert sampling_params.kwargs["max_tokens"] == 512
    assert sampling_params.kwargs["n"] == 1
    structured = sampling_params.kwargs["structured_outputs"]
    assert structured.kwargs == {
        "json": schema,
        "disable_additional_properties": True,
    }
    metadata = backend.last_batch_metadata
    assert metadata == [
        {"prompt_tokens": 3, "completion_tokens": 2, "finish_reason": "stop"},
        {"prompt_tokens": 4, "completion_tokens": 3, "finish_reason": "stop"},
    ]
    metadata[0]["prompt_tokens"] = 999
    assert backend.last_batch_metadata[0]["prompt_tokens"] == 3
    assert "first prompt" not in json.dumps(backend.last_batch_metadata)
    assert backend.provenance["runtime_versions"]["vllm"] == "0.19.1"
    assert backend.provenance["sampling"] == {
        "temperature": 0.0,
        "seed": 17,
        "max_tokens": 512,
        "n": 1,
    }


@pytest.mark.parametrize(
    "response_text",
    [
        "```json\n{\"events\": []}\n```",
        '{"events": [], "events": []}',
        '{"value": NaN}',
        "[]",
    ],
)
def test_vllm_backend_rejects_non_strict_json(monkeypatch, response_text):
    _install_fake_vllm(monkeypatch, [response_text])
    backend = VLLMStructuredBackend(
        model="org/pinned-model",
        revision="a" * 40,
        tokenizer_revision="b" * 40,
    )

    with pytest.raises(StructuredOutputError):
        backend.complete("prompt", {"type": "object"})


def test_vllm_backend_rejects_wrong_runtime_version(monkeypatch):
    _install_fake_vllm(monkeypatch, [], version="0.19.0")

    with pytest.raises(RuntimeError, match="requires vLLM 0.19.1"):
        VLLMStructuredBackend(
            model="org/pinned-model",
            revision="a" * 40,
            tokenizer_revision="b" * 40,
        )


def test_vllm_backend_rejects_prompt_that_cannot_fit_reserved_output(monkeypatch):
    _install_fake_vllm(monkeypatch, [json.dumps({"events": []})])
    backend = VLLMStructuredBackend(
        model="org/pinned-model",
        revision="a" * 40,
        tokenizer_revision="b" * 40,
        max_tokens=8,
        max_model_len=10,
    )

    with pytest.raises(StructuredOutputError, match="exceeding max_model_len"):
        backend.complete("one two three", {"type": "object"})


def test_vllm_backend_requires_immutable_revisions():
    with pytest.raises(ValueError, match="pinned 40-character Git commit"):
        VLLMStructuredBackend(
            model="org/model",
            revision="main",
            tokenizer_revision="b" * 40,
        )
