from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mdmeta.graph import GraphExportManifest, export_neo4j_graph, verify_neo4j_graph
from mdmeta.integration import ArticleMetadata, IntegratedMDRecord, ProvenanceRecord
from mdmeta.models import MappingSegment, ValidationState
from mdmeta.pdbekb import (
    PDBeKBAnnotationGroup,
    PDBeKBEndpointResult,
    PDBeKBEnrichment,
    PDBeKBPartner,
    build_pdbekb_batch_report,
)
from mdmeta.storage import SQLiteRecordStore


ACCESSION = "Q14676"


def _record() -> IntegratedMDRecord:
    return IntegratedMDRecord(
        article=ArticleMetadata(
            document_id="DOC1",
            title="Graph export fixture",
            source_uri="https://example.org/articles/DOC1",
            full_text_sha256=hashlib.sha256(b"DOC1").hexdigest(),
        ),
        literature_facts=[],
        protocol_events=[],
        pdb_validations=[],
        mapping_discoveries=[],
        uniprot_validations=[],
        mapping_validations=[],
        residue_mappings=[
            MappingSegment(
                pdb_id="3UNN",
                uniprot_accession=ACCESSION,
                chain_id="B",
                pdb_start=1,
                pdb_end=20,
                uniprot_start=2,
                uniprot_end=21,
            )
        ],
        provenance=ProvenanceRecord(),
        completeness={"fixture": "complete"},
    )


def _enrichment() -> PDBeKBEnrichment:
    annotations = PDBeKBEndpointResult(
        state=ValidationState.VALIDATED,
        endpoint=f"https://www.ebi.ac.uk/pdbe/graph-api/uniprot/annotations/{ACCESSION}",
        reason="pdbekb_annotations_validated",
        http_status=200,
        response_sha256="a" * 64,
        attempts=1,
    )
    partners = PDBeKBEndpointResult(
        state=ValidationState.VALIDATED,
        endpoint=(
            "https://www.ebi.ac.uk/pdbe/graph-api/uniprot/"
            f"annotation_partners/{ACCESSION}"
        ),
        reason="pdbekb_partners_validated",
        http_status=200,
        response_sha256="b" * 64,
        attempts=1,
    )
    return PDBeKBEnrichment(
        accession=ACCESSION,
        state=ValidationState.VALIDATED,
        sequence_length=21,
        annotation_result=annotations,
        partner_result=partners,
        annotation_groups=[
            PDBeKBAnnotationGroup(
                name="Predicted ligand pocket",
                accession="p2rank",
                data_type="ANNOTATION",
                residue_range_count=1,
                covered_sequence_position_count=3,
                pdb_ids=["3UNN", "4XYZ"],
            )
        ],
        partners=[
            PDBeKBPartner(
                resource_name="p2rank",
                url="https://example.org/p2rank",
                annotation_category="predicted_ligand_binding_site",
            )
        ],
    )


def _database(path: Path) -> Path:
    store = SQLiteRecordStore(path)
    store.write(_record())
    store.checkpoint()
    report = build_pdbekb_batch_report(
        [_enrichment()],
        source_database=path,
        source_database_schema_version=2,
        source_article_count=1,
        generated_at=datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
    )
    store.import_pdbekb_report(report.model_dump(mode="json"))
    store.checkpoint()
    return path


def test_graph_export_is_deterministic_and_neo4j_ready(tmp_path: Path) -> None:
    database = _database(tmp_path / "records.sqlite")
    first = tmp_path / "first"
    second = tmp_path / "second"

    manifest = export_neo4j_graph(database, first)
    repeated = export_neo4j_graph(database, second)

    assert manifest == repeated
    assert (first / "nodes.csv").read_bytes() == (second / "nodes.csv").read_bytes()
    assert (first / "relationships.csv").read_bytes() == (
        second / "relationships.csv"
    ).read_bytes()
    assert manifest.source_article_count == 1
    assert manifest.source_pdbekb_report_count == 1
    assert manifest.node_label_counts == {
        "AnnotationPartner": 1,
        "Article": 1,
        "PDB": 2,
        "PDBeKBAnnotation": 1,
        "UniProt": 1,
    }
    assert manifest.relationship_type_counts == {
        "HAS_ANNOTATION_PARTNER": 1,
        "HAS_PDBEKB_ANNOTATION": 1,
        "LINKS_STRUCTURE": 2,
        "SIFTS_MAPS_TO": 1,
        "USES_STRUCTURE": 1,
    }
    with (first / "nodes.csv").open(newline="", encoding="utf-8") as handle:
        nodes = list(csv.DictReader(handle))
    with (first / "relationships.csv").open(newline="", encoding="utf-8") as handle:
        relationships = list(csv.DictReader(handle))
    assert nodes[0].keys() == {
        "node_id:ID",
        ":LABEL",
        "identifier",
        "name",
        "state",
        "source_uri",
        "properties_json",
    }
    assert relationships[0].keys() == {
        "relationship_id",
        ":START_ID",
        ":END_ID",
        ":TYPE",
        "source_document_id",
        "properties_json",
    }
    assert all("local_path" not in row["properties_json"] for row in nodes)
    committed = json.loads((first / "graph-manifest.json").read_text())
    assert GraphExportManifest.model_validate(committed) == manifest
    assert verify_neo4j_graph(first, database=database) == manifest


def test_graph_export_rejects_uncheckpointed_database(tmp_path: Path) -> None:
    database = _database(tmp_path / "records.sqlite")
    database.with_name(database.name + "-wal").write_bytes(b"sidecar")

    with pytest.raises(RuntimeError, match="checkpointed database"):
        export_neo4j_graph(database, tmp_path / "graph")


def test_graph_manifest_rejects_tampered_commitment(tmp_path: Path) -> None:
    manifest = export_neo4j_graph(
        _database(tmp_path / "records.sqlite"), tmp_path / "graph"
    )
    payload = manifest.model_dump(mode="json")
    payload["nodes_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="graph_commitment_sha256"):
        GraphExportManifest.model_validate(payload)


def test_graph_verification_rejects_tampered_csv(tmp_path: Path) -> None:
    graph = tmp_path / "graph"
    export_neo4j_graph(_database(tmp_path / "records.sqlite"), graph)
    with (graph / "nodes.csv").open("ab") as handle:
        handle.write(b"tampered\n")

    with pytest.raises(ValueError, match="nodes.csv SHA-256"):
        verify_neo4j_graph(graph)
