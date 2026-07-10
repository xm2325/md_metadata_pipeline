import json
from pathlib import Path

from mdlit.clients import PDBeClient, UniProtClient
from mdlit.extraction import DeterministicExtractor
from mdlit.jats import parse_jats
from mdlit.models import ArticleMetadata, MDRecord
from mdlit.validation import _extract_mappings, validate_live, validate_semantics


class FixturePDBe(PDBeClient):
    def entry_summary(self, pdb_id: str):
        data = json.loads(Path("data/contract/pdbe_summary_1ubq.json").read_text())
        return data, "a" * 64, "fixture://pdbe-summary"

    def uniprot_mapping(self, pdb_id: str):
        data = json.loads(Path("data/contract/pdbe_sifts_1ubq.json").read_text())
        return data, "b" * 64, "fixture://pdbe-sifts"


class FixtureUniProt(UniProtClient):
    def entry(self, accession: str):
        data = json.loads(Path("data/contract/uniprot_p0cg47.json").read_text())
        return data, "c" * 64, "fixture://uniprot"


def _record() -> MDRecord:
    article = parse_jats(Path("data/demo/article.xml"))
    facts = DeterministicExtractor().extract(article.paragraphs, "DOC", "synthetic://doc")
    return MDRecord(
        article=ArticleMetadata(document_id="DOC", source_uri="synthetic://doc"), facts=facts
    )


def test_semantic_validation() -> None:
    record = validate_semantics(_record())
    temperature = record.facts_for("temperature")[0]
    assert any(event.status == "validated" for event in temperature.validation)


def test_sifts_fixture_parses_residue_mapping() -> None:
    data = json.loads(Path("data/contract/pdbe_sifts_1ubq.json").read_text())
    mappings = _extract_mappings("1ubq", data)
    assert len(mappings) == 1
    assert mappings[0].uniprot_accession == "P0CG47"
    assert mappings[0].pdb_start == 1
    assert mappings[0].uniprot_end == 76


def test_live_validation_with_contract_fixtures() -> None:
    record = validate_live(_record(), pdbe=FixturePDBe(), uniprot=FixtureUniProt())
    assert len(record.mappings) == 1
    assert any(
        event.validator == "PDB_UniProt_cross_check" and event.status == "validated"
        for event in record.record_validation
    )
    assert any(
        event.validator == "PDBe_entry_summary" and event.status == "validated"
        for event in record.facts_for("pdb_id")[0].validation
    )
    assert any(
        event.validator == "UniProt_entry" and event.status == "validated"
        for event in record.facts_for("uniprot_accession")[0].validation
    )


class FailingPDBe(PDBeClient):
    def entry_summary(self, pdb_id: str):
        raise RuntimeError("summary unavailable")

    def uniprot_mapping(self, pdb_id: str):
        raise RuntimeError("mapping unavailable")


class EmptyMappingPDBe(FixturePDBe):
    def uniprot_mapping(self, pdb_id: str):
        return {pdb_id.lower(): {"UniProt": {}}}, "d" * 64, "fixture://empty-sifts"


def test_service_failure_is_unresolved_not_conflict() -> None:
    record = validate_live(_record(), pdbe=FailingPDBe(), uniprot=FixtureUniProt())
    cross_check = [
        event for event in record.record_validation if event.validator == "PDB_UniProt_cross_check"
    ][0]
    assert cross_check.status == "unresolved"
    assert any(
        event.validator == "PDBe_SIFTS_mapping" and event.status == "unresolved"
        for event in record.record_validation
    )


def test_successful_empty_mapping_can_report_conflict() -> None:
    record = validate_live(_record(), pdbe=EmptyMappingPDBe(), uniprot=FixtureUniProt())
    cross_check = [
        event for event in record.record_validation if event.validator == "PDB_UniProt_cross_check"
    ][0]
    assert cross_check.status == "conflict"
