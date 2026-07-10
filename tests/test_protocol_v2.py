from mdlit.extraction_v2 import ProtocolAwareExtractor
from mdlit.jats import Paragraph
from mdlit.protocol import build_protocol_events, infer_phase
from mdlit.retrieval import select_protocol_paragraphs


def test_protocol_retrieval_rejects_cell_culture_temperature() -> None:
    paragraphs = [
        Paragraph("Cell culture", "p1", "Cells were incubated at 37 °C for 24 h."),
        Paragraph(
            "Molecular dynamics simulation",
            "p2",
            "Production simulations were performed with GROMACS 2022.3 at 300 K and 1 bar.",
        ),
    ]
    selected = select_protocol_paragraphs(paragraphs)
    assert {item.paragraph.paragraph_id for item in selected} == {"p2"}
    facts = ProtocolAwareExtractor().extract(paragraphs, "DOC", "synthetic://doc")
    temperatures = [fact.normalized_value for fact in facts if fact.field_name == "temperature"]
    assert temperatures == [300]


def test_program_context_does_not_treat_charmm_gui_as_engine() -> None:
    paragraph = Paragraph(
        "Molecular dynamics simulation",
        "p1",
        "The system was prepared using CHARMM-GUI and simulated with GROMACS 2021.5 using the CHARMM36m force field.",
    )
    facts = ProtocolAwareExtractor().extract([paragraph], "DOC", "synthetic://doc")
    programs = {str(f.normalized_value) for f in facts if f.field_name == "program"}
    force_fields = {str(f.normalized_value) for f in facts if f.field_name == "force_field"}
    assert programs == {"GROMACS"}
    assert "CHARMM36m" in force_fields


def test_duration_phase_and_event_graph() -> None:
    paragraph = Paragraph(
        "Molecular dynamics simulation",
        "p1",
        "The system was equilibrated for 1500 ps under the NPT ensemble at 300 K and 1 bar. "
        "Three independent production simulations of 500 ns used a time step of 2 fs.",
    )
    facts = ProtocolAwareExtractor().extract([paragraph], "DOC", "synthetic://doc")
    durations = [fact for fact in facts if fact.field_name == "simulation_duration"]
    assert {(f.normalized_value, f.phase) for f in durations} == {
        (1.5, "equilibration"),
        (500, "production"),
    }
    events = build_protocol_events(facts)
    assert {event.phase for event in events} >= {"equilibration", "production"}
    production = [event for event in events if event.phase == "production"][0]
    assert production.duration_value == 500
    assert production.time_step_ps == 0.002
    assert production.replicates == 3


def test_infer_phase_analysis_window() -> None:
    text = "The final 100 ns trajectory was selected for analysis."
    start = text.index("100")
    assert infer_phase(text, start, start + len("100 ns")) == "analysis_window"
