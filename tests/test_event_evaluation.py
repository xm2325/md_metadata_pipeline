from mdlit.event_evaluation import evaluate_protocol_events
from mdlit.models import ProtocolEvent


def _event(event_id: str, duration: float) -> ProtocolEvent:
    return ProtocolEvent(
        event_id=event_id,
        order=0,
        phase="production",
        duration_value=duration,
        duration_unit="ns",
        ensemble="NPT",
        completeness="partial",
    )


def test_event_evaluation_reports_exact_and_attribute_metrics() -> None:
    predicted = {"DOC": [_event("p", 100)]}
    reference = {"DOC": [_event("r", 100)]}
    result = evaluate_protocol_events(predicted, reference, bootstrap_iterations=20)
    assert result["event_exact"]["f1"] == 1
    assert result["event_attribute"]["f1"] == 1
    assert result["article_count"] == 1
