import json

from mdmeta.benchmarking import (
    compare_systems,
    load_event_run,
    paired_bootstrap_delta,
    validated_union,
)
from mdmeta.models import EventType, Evidence, ProtocolEvent


def event(event_id: str, event_type: EventType, duration: float) -> ProtocolEvent:
    quote = "100 ns"
    return ProtocolEvent(
        event_id=event_id,
        event_type=event_type,
        duration_ps=duration,
        temperature_k=300,
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


def test_load_llm_run_and_operational_metadata(tmp_path) -> None:
    path = tmp_path / "llm.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "llm-protocol-extraction-run-v1",
                "model_id": "Qwen/test",
                "completions": [
                    {"latency_ms": 100.0, "total_tokens": 20, "finish_reason": "stop"},
                    {"latency_ms": 300.0, "total_tokens": 30, "finish_reason": "stop"},
                ],
                "documents": [
                    {
                        "document_id": "PMC1",
                        "paragraph_count": 1,
                        "event_count": 1,
                        "events": [event("e1", EventType.PRODUCTION, 100_000).model_dump(mode="json")],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    events, metadata = load_event_run(path)
    result = compare_systems(
        events,
        {"llm": (events, metadata)},
        bootstrap_iterations=10,
    )
    operational = result["systems"]["llm"]["operational"]
    assert operational["model_id"] == "Qwen/test"
    assert operational["median_latency_ms"] == 200.0
    assert operational["total_tokens"] == 50
    assert result["systems"]["llm"]["scientific"]["event_attribute"]["f1"] == 1.0


def test_validated_union_deduplicates_but_retains_complementary_events() -> None:
    production = event("a", EventType.PRODUCTION, 100_000)
    equilibration = event("b", EventType.EQUILIBRATION, 2_000)
    combined = validated_union(
        {"PMC1": [production]},
        {"PMC1": [production.model_copy(update={"event_id": "other"}), equilibration]},
    )
    assert len(combined["PMC1"]) == 2
    assert {item.event_type for item in combined["PMC1"]} == {
        EventType.PRODUCTION,
        EventType.EQUILIBRATION,
    }


def test_paired_bootstrap_reports_candidate_improvement() -> None:
    reference = {
        "PMC1": [event("r1", EventType.PRODUCTION, 100_000)],
        "PMC2": [event("r2", EventType.PRODUCTION, 100_000)],
    }
    baseline = {"PMC1": [], "PMC2": []}
    candidate = {
        "PMC1": [event("c1", EventType.PRODUCTION, 100_000)],
        "PMC2": [event("c2", EventType.PRODUCTION, 100_000)],
    }
    delta = paired_bootstrap_delta(
        candidate,
        baseline,
        reference,
        iterations=50,
        seed=1,
    )
    assert delta["observed_delta"] == 1.0
    assert delta["paired_article_bootstrap_95_ci"] == [1.0, 1.0]
    assert delta["bootstrap_probability_delta_gt_zero"] == 1.0


def test_empty_reference_bootstrap_is_defined() -> None:
    delta = paired_bootstrap_delta({}, {}, {}, iterations=10)
    assert delta["observed_delta"] == 0.0
    assert delta["paired_article_bootstrap_95_ci"] == [0.0, 0.0]


def test_unknown_baseline_is_rejected() -> None:
    try:
        compare_systems({}, {"system": ({}, {})}, baseline_name="missing")
    except ValueError as exc:
        assert "unknown baseline" in str(exc)
    else:
        raise AssertionError("unknown baseline was accepted")
