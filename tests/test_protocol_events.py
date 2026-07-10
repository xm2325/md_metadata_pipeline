from mdmeta.models import EventType
from mdmeta.protocol_events import Paragraph, extract_protocol_events


def test_links_conditions_to_equilibration_event() -> None:
    text = (
        "The system was equilibrated for 100 ps at 300 K and 1 bar in the NPT ensemble "
        "with a 2 fs time step."
    )
    events = extract_protocol_events(Paragraph("PMC1", "Methods", "P1", text))
    assert len(events) == 1
    event = events[0]
    assert event.event_type is EventType.EQUILIBRATION
    assert event.duration_ps == 100
    assert event.temperature_k == 300
    assert event.pressure_bar == 1
    assert event.ensemble == "NPT"
    assert event.timestep_fs == 2


def test_excludes_non_md_incubation_duration() -> None:
    text = "Cells were incubated for 24 h at 37 °C before imaging."
    assert extract_protocol_events(Paragraph("PMC1", "Cell culture", "P2", text)) == []


def test_phase_aware_production_and_analysis_window() -> None:
    production = "Production MD simulations were run for 500 ns in three independent runs."
    analysis = "The final 100 ns trajectory was used for further analysis."
    production_event = extract_protocol_events(Paragraph("PMC1", "MD", "P3", production))[0]
    analysis_event = extract_protocol_events(Paragraph("PMC1", "Results", "P4", analysis))[0]
    assert production_event.event_type is EventType.PRODUCTION
    assert production_event.replicates == 3
    assert analysis_event.event_type is EventType.ANALYSIS_WINDOW
