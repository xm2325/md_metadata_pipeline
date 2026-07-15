import csv

from mdmeta.graph_export import build_graph, write_neo4j_csv
from mdmeta.integration import (
    ArticleMetadata,
    IntegratedMDRecord,
    LiteratureFact,
    ProvenanceRecord,
)
from mdmeta.models import Evidence, EventType, MappingSegment, ProtocolEvent, ValidationState
from mdmeta.pdbe_kb import PDBeKBAnnotation, PDBeKBEnrichment


def evidence() -> Evidence:
    return Evidence(
        document_id="DOC1",
        section="Methods",
        paragraph_id="p1",
        quote="6VSB",
        start_char=0,
        end_char=4,
        context_sha256="a" * 64,
    )


def record() -> IntegratedMDRecord:
    return IntegratedMDRecord(
        article=ArticleMetadata(
            document_id="DOC1",
            title="MD study",
            doi="10.1/example",
            source_uri="https://example.org/article",
            full_text_sha256="b" * 64,
        ),
        literature_facts=[
            LiteratureFact(
                field="starting_pdb_id",
                value="6VSB",
                evidence=evidence(),
                extraction_method="test",
                confidence=1.0,
            )
        ],
        protocol_events=[
            ProtocolEvent(
                event_id="evt1",
                event_type=EventType.PRODUCTION,
                duration_ps=100_000,
                evidence=[evidence()],
                relation_method="test",
                confidence=1.0,
            )
        ],
        pdb_validations=[],
        mapping_discoveries=[],
        uniprot_validations=[],
        mapping_validations=[],
        residue_mappings=[
            MappingSegment(
                pdb_id="6VSB",
                uniprot_accession="P0DTC2",
                chain_id="A",
                pdb_start=1,
                pdb_end=10,
                uniprot_start=1,
                uniprot_end=10,
            )
        ],
        provenance=ProvenanceRecord(),
        completeness={},
    )


def enrichment() -> PDBeKBEnrichment:
    return PDBeKBEnrichment(
        pdb_id="6VSB",
        state=ValidationState.VALIDATED,
        endpoint="https://example.org/pdbe-kb",
        reason="pdbe_kb_annotations_projected",
        annotations=[
            PDBeKBAnnotation(
                annotation_id="1" * 16,
                pdb_id="6VSB",
                provider="M-CSA",
                annotation_type="catalytic_residue",
                label="Catalytic residue",
                chain_id="A",
                residue_start=5,
                residue_end=5,
                source_record_sha256="c" * 64,
            )
        ],
    )


def test_graph_contains_integrated_resource_relationships() -> None:
    nodes, edges = build_graph([record()], [enrichment()])
    labels = {node.labels for node in nodes}
    edge_types = {edge.edge_type for edge in edges}
    assert labels == {
        "Article",
        "FunctionalAnnotation",
        "Protein",
        "ProtocolEvent",
        "Structure",
    }
    assert edge_types == {
        "HAS_FUNCTIONAL_ANNOTATION",
        "MAPS_TO_PROTEIN",
        "MENTIONS_STRUCTURE",
        "REPORTS_EVENT",
    }
    assert sum(node.node_id == "pdb:6VSB" for node in nodes) == 1


def test_graph_csv_has_neo4j_bulk_import_headers_and_hashes(tmp_path) -> None:
    nodes, edges = build_graph([record()])
    manifest = write_neo4j_csv(tmp_path, nodes, edges)
    with (tmp_path / "nodes.csv").open(encoding="utf-8", newline="") as handle:
        header = next(csv.reader(handle))
    with (tmp_path / "relationships.csv").open(encoding="utf-8", newline="") as handle:
        relationship_header = next(csv.reader(handle))
    assert header[:2] == ["node_id:ID", ":LABEL"]
    assert relationship_header[:3] == [":START_ID", ":END_ID", ":TYPE"]
    assert manifest["node_count"] == len(nodes)
    assert len(manifest["files"]["nodes.csv"]) == 64
