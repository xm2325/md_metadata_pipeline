from mdmeta.event_evaluation import evaluate_events
from mdmeta.models import EventType, Evidence, ProtocolEvent


def _event(
    event_id: str,
    event_type: EventType,
    duration: float,
    *,
    temperature: float = 300,
) -> ProtocolEvent:
    quote = "100 ns"
    return ProtocolEvent(
        event_id=event_id,
        event_type=event_type,
        duration_ps=duration,
        temperature_k=temperature,
        evidence=[
            Evidence(
                document_id="PMC1",
                section="Methods",
                paragraph_id="p1",
                quote=quote,
                start_char=0,
                end_char=len(quote),
                context_sha256="a" * 64,
            )
        ],
        relation_method="test",
        confidence=1.0,
    )


def test_exact_attribute_and_duration_phase_metrics() -> None:
    reference = {"PMC1": [_event("r", EventType.PRODUCTION, 100_000)]}
    prediction = {"PMC1": [_event("p", EventType.PRODUCTION, 100_000)]}
    result = evaluate_events(prediction, reference, bootstrap_iterations=50)
    assert result["event_exact"]["f1"] == 1.0
    assert result["event_attribute"]["f1"] == 1.0
    assert result["duration_phase"]["f1"] == 1.0
    assert result["event_attribute"]["article_bootstrap_95_ci_f1"] == [1.0, 1.0]


def test_wrong_phase_is_counted_as_error() -> None:
    reference = {"PMC1": [_event("r", EventType.PRODUCTION, 100_000)]}
    prediction = {"PMC1": [_event("p", EventType.EQUILIBRATION, 100_000)]}
    result = evaluate_events(prediction, reference, bootstrap_iterations=10)
    assert result["duration_phase"]["tp"] == 0
    assert result["duration_phase"]["fp"] == 1
    assert result["duration_phase"]["fn"] == 1
