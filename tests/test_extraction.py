from pathlib import Path

from mdlit.extraction import DeterministicExtractor
from mdlit.jats import parse_jats


def _facts():
    article = parse_jats(Path("data/demo/article.xml"))
    return DeterministicExtractor().extract(article.paragraphs, "DOC1", "synthetic://doc1")


def test_expected_fields_are_extracted() -> None:
    facts = _facts()
    values = {(f.field_name, f.normalized_value, f.unit) for f in facts}
    expected = {
        ("pdb_id", "1UBQ", None),
        ("uniprot_accession", "P0CG47", None),
        ("program", "GROMACS", None),
        ("program_version", "2022.3", None),
        ("force_field", "CHARMM36m", None),
        ("water_model", "TIP3P", None),
        ("temperature", 310, "K"),
        ("pressure", 1, "bar"),
        ("ensemble", "NPT", None),
        ("time_step", 0.002, "ps"),
        ("replicates", 3, None),
        ("simulation_duration", 500, "ns"),
    }
    assert expected <= values


def test_all_facts_have_valid_evidence_offsets() -> None:
    facts = _facts()
    assert facts
    for fact in facts:
        for evidence in fact.evidence:
            assert evidence.end_char - evidence.start_char == len(evidence.quote)
            assert len(evidence.context_sha256) == 64
