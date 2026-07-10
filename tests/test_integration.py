from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from mdmeta.api import create_app
from mdmeta.integration import (
    AssetAvailability,
    MDToPDBMappingStatus,
    build_provenance,
    discover_uniprot_mappings,
    extract_article_metadata,
    extract_literature_facts,
    integrate_article,
    parse_jats_paragraphs,
    summarize_integrated_records,
)
from mdmeta.models import ValidationState
from mdmeta.storage import SQLiteRecordStore
from mdmeta.validation import IdentifierValidator

ROOT = Path(__file__).parents[1]
XML_PATH = ROOT / "examples" / "woo_2020" / "article_fixture.xml"
MANIFEST_PATH = ROOT / "examples" / "woo_2020" / "provenance_manifest.json"


def _mock_handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url.endswith("/pdb/entry/summary/6vsb"):
        return httpx.Response(200, json={"6vsb": [{"title": "spike open"}]})
    if url.endswith("/pdb/entry/summary/6vxx"):
        return httpx.Response(200, json={"6vxx": [{"title": "spike closed"}]})
    if url.endswith("/mappings/uniprot/6vsb"):
        return httpx.Response(
            200,
            json={
                "6vsb": {
                    "UniProt": {
                        "P0DTC2": {
                            "mappings": [
                                {
                                    "chain_id": "A",
                                    "start": {"residue_number": 27},
                                    "end": {"residue_number": 1146},
                                    "unp_start": 27,
                                    "unp_end": 1146,
                                }
                            ]
                        }
                    }
                }
            },
        )
    if url.endswith("/mappings/uniprot/6vxx"):
        return httpx.Response(
            200,
            json={
                "6vxx": {
                    "UniProt": {
                        "P0DTC2": {
                            "mappings": [
                                {
                                    "chain_id": "A",
                                    "start": {"residue_number": 27},
                                    "end": {"residue_number": 1147},
                                    "unp_start": 27,
                                    "unp_end": 1147,
                                }
                            ]
                        }
                    }
                }
            },
        )
    if url.endswith("/uniprotkb/P0DTC2.json"):
        return httpx.Response(
            200,
            json={
                "primaryAccession": "P0DTC2",
                "proteinDescription": {
                    "recommendedName": {"fullName": {"value": "Spike glycoprotein"}}
                },
            },
        )
    raise AssertionError(f"unexpected URL: {url}")


def _record(tmp_path: Path):
    client = httpx.Client(transport=httpx.MockTransport(_mock_handler))
    validator = IdentifierValidator(client, cache_dir=tmp_path / "cache")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return integrate_article(
        "WOO2020",
        XML_PATH.read_bytes(),
        source_uri="https://doi.org/10.1021/acs.jpcb.0c04553",
        validator=validator,
        provenance_manifest=manifest,
        provenance_base_dir=MANIFEST_PATH.parent,
    )


def test_article_and_exact_literature_fact_extraction() -> None:
    xml_bytes = XML_PATH.read_bytes()
    article = extract_article_metadata(
        "WOO2020",
        xml_bytes,
        source_uri="https://doi.org/10.1021/acs.jpcb.0c04553",
    )
    paragraphs = parse_jats_paragraphs("WOO2020", xml_bytes)
    facts = extract_literature_facts(paragraphs)
    pdb_facts = [fact for fact in facts if fact.field == "starting_pdb_id"]

    assert article.doi == "10.1021/acs.jpcb.0c04553"
    assert article.full_text_sha256 == hashlib.sha256(xml_bytes).hexdigest()
    assert [fact.value for fact in pdb_facts] == ["6VSB", "6VXX"]
    assert any(fact.field == "system_contains_membrane" for fact in facts)
    assert any(fact.field == "system_contains_glycans" for fact in facts)
    for fact in pdb_facts:
        paragraph = next(
            item for item in paragraphs if item.paragraph_id == fact.evidence.paragraph_id
        )
        assert paragraph.text[fact.evidence.start_char : fact.evidence.end_char] == fact.value


def test_end_to_end_integration_keeps_sources_separate(tmp_path: Path) -> None:
    record = _record(tmp_path)

    assert {item.query["pdb_id"] for item in record.pdb_validations} == {"6VSB", "6VXX"}
    assert all(item.state is ValidationState.VALIDATED for item in record.pdb_validations)
    assert {item.query["accession"] for item in record.uniprot_validations} == {"P0DTC2"}
    assert all(item.state is ValidationState.VALIDATED for item in record.mapping_validations)
    assert {segment.uniprot_accession for segment in record.residue_mappings} == {"P0DTC2"}
    assert {segment.pdb_id for segment in record.residue_mappings} == {"6VSB", "6VXX"}
    assert all(item.payload is None for item in record.pdb_validations)
    assert record.completeness["residue_mapping_scope"] == "pdb_to_uniprot_only"
    assert record.completeness["md_file_provenance"] == "declared_not_fully_verified"
    assert record.provenance.md_to_pdb_mapping_status is MDToPDBMappingStatus.NOT_COMPUTABLE
    assert any(
        asset.availability is AssetAvailability.DECLARED_UNAVAILABLE
        for asset in record.provenance.assets
    )


def test_mapping_network_failure_is_unresolved() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    validator = IdentifierValidator(httpx.Client(transport=httpx.MockTransport(handler)))
    discovery = discover_uniprot_mappings(validator, "6VSB")
    assert discovery.state is ValidationState.UNRESOLVED
    assert discovery.accessions == []
    assert discovery.reason.startswith("network_error")


def test_empty_successful_mapping_response_is_conflict() -> None:
    validator = IdentifierValidator(
        httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"6vsb": {}}))
        )
    )
    discovery = discover_uniprot_mappings(validator, "6VSB")
    assert discovery.state is ValidationState.CONFLICT
    assert discovery.reason == "no_uniprot_mapping_in_successful_response"


def test_verified_local_asset_hash_and_failure_modes(tmp_path: Path) -> None:
    asset = tmp_path / "prepared.gro"
    asset.write_text("coordinates", encoding="utf-8")
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    manifest = {
        "assets": [
            {
                "role": "prepared_structure",
                "availability": "verified_local",
                "local_path": "prepared.gro",
                "sha256": digest,
            }
        ],
        "md_to_pdb_mapping": {
            "status": "verified",
            "reason": "explicit residue correspondence file passed schema checks",
        },
    }
    provenance = build_provenance(manifest, base_dir=tmp_path)
    assert provenance.assets[0].sha256 == digest
    assert provenance.md_to_pdb_mapping_status is MDToPDBMappingStatus.VERIFIED

    with pytest.raises(ValueError, match="base_dir"):
        build_provenance(manifest)
    bad = json.loads(json.dumps(manifest))
    bad["assets"][0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        build_provenance(bad, base_dir=tmp_path)
    asset.unlink()
    with pytest.raises(FileNotFoundError):
        build_provenance(manifest, base_dir=tmp_path)


def test_sqlite_storage_and_rest_api(tmp_path: Path) -> None:
    record = _record(tmp_path)
    database = tmp_path / "records.sqlite"
    store = SQLiteRecordStore(database)
    store.write(record)
    assert store.count_articles() == 1
    assert store.get("WOO2020")["article"]["doi"] == "10.1021/acs.jpcb.0c04553"
    assert len(store.search(pdb_id="6vsb")) == 1
    assert len(store.search(uniprot_accession="P0DTC2")) == 1
    assert store.search(pdb_id="1ABC") == []

    client = TestClient(create_app(database))
    assert client.get("/health").json() == {"status": "ok", "article_count": 1}
    assert client.get("/records/WOO2020").status_code == 200
    assert client.get("/records/MISSING").status_code == 404
    assert client.get("/search", params={"pdb_id": "6VSB"}).json()["count"] == 1
    assert client.get("/search", params={"uniprot_accession": "P0DTC2"}).json()["count"] == 1
    assert client.get("/search").status_code == 400


def test_summary_reports_coverage(tmp_path: Path) -> None:
    record = _record(tmp_path)
    summary = summarize_integrated_records(
        [record],
        [{"document_id": "PMC0", "error_type": "ValueError"}],
    )
    assert summary["article_count_succeeded"] == 1
    assert summary["failure_count"] == 1
    assert summary["article_count_with_pdb"] == 1
    assert summary["unique_pdb_id_count"] == 2
    assert summary["unique_uniprot_accession_count"] == 1
    assert summary["residue_mapping_segment_count"] == 2
    assert summary["pdb_validation_state_counts"] == {"validated": 2}


def test_frozen_60_source_manifest_commitment() -> None:
    from scripts.run_integrated_60 import validate_source_manifest

    path = ROOT / "study" / "integration_60" / "source_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    articles = validate_source_manifest(manifest)
    assert len(articles) == 60
    assert sum(article["split"] == "development" for article in articles) == 30
    assert sum(article["split"] == "validation" for article in articles) == 10
    assert sum(article["split"] == "locked_test" for article in articles) == 20

    tampered = json.loads(json.dumps(manifest))
    tampered["articles"][0]["full_text_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="commitment"):
        validate_source_manifest(tampered)
