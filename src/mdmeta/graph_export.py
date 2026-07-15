from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .integration import IntegratedMDRecord
from .pdbe_kb import PDBeKBEnrichment


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    labels: str
    name: str
    properties: dict[str, Any]


@dataclass(frozen=True)
class GraphEdge:
    start_id: str
    end_id: str
    edge_type: str
    properties: dict[str, Any]


def _stable_id(prefix: str, value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"{prefix}:{hashlib.sha256(encoded).hexdigest()[:16]}"


def build_graph(
    records: list[IntegratedMDRecord],
    pdbe_kb: list[PDBeKBEnrichment] | None = None,
) -> tuple[list[GraphNode], list[GraphEdge]]:
    nodes: dict[str, GraphNode] = {}
    edges: dict[tuple[str, str, str, str], GraphEdge] = {}

    def add_node(node: GraphNode) -> None:
        existing = nodes.get(node.node_id)
        if existing is not None and existing != node:
            raise ValueError(f"graph node collision: {node.node_id}")
        nodes[node.node_id] = node

    def add_edge(edge: GraphEdge) -> None:
        property_key = json.dumps(edge.properties, sort_keys=True, separators=(",", ":"))
        edges[(edge.start_id, edge.end_id, edge.edge_type, property_key)] = edge

    for record in records:
        document_id = record.article.document_id
        article_id = f"article:{document_id}"
        add_node(
            GraphNode(
                article_id,
                "Article",
                record.article.title or document_id,
                {
                    "document_id": document_id,
                    "doi": record.article.doi,
                    "source_uri": record.article.source_uri,
                    "source_sha256": record.article.full_text_sha256,
                },
            )
        )

        pdb_ids = {
            str(fact.value).upper()
            for fact in record.literature_facts
            if fact.field == "starting_pdb_id"
        } | {segment.pdb_id.upper() for segment in record.residue_mappings}
        for pdb_id in sorted(pdb_ids):
            structure_id = f"pdb:{pdb_id}"
            add_node(GraphNode(structure_id, "Structure", pdb_id, {"pdb_id": pdb_id}))
            add_edge(
                GraphEdge(
                    article_id,
                    structure_id,
                    "MENTIONS_STRUCTURE",
                    {"document_id": document_id},
                )
            )

        for segment in record.residue_mappings:
            structure_id = f"pdb:{segment.pdb_id.upper()}"
            protein_id = f"uniprot:{segment.uniprot_accession}"
            add_node(
                GraphNode(
                    structure_id,
                    "Structure",
                    segment.pdb_id.upper(),
                    {"pdb_id": segment.pdb_id.upper()},
                )
            )
            add_node(
                GraphNode(
                    protein_id,
                    "Protein",
                    segment.uniprot_accession,
                    {"uniprot_accession": segment.uniprot_accession},
                )
            )
            add_edge(
                GraphEdge(
                    structure_id,
                    protein_id,
                    "MAPS_TO_PROTEIN",
                    {
                        "chain_id": segment.chain_id,
                        "pdb_start": segment.pdb_start,
                        "pdb_end": segment.pdb_end,
                        "uniprot_start": segment.uniprot_start,
                        "uniprot_end": segment.uniprot_end,
                        "document_id": document_id,
                    },
                )
            )

        for event in record.protocol_events:
            event_id = f"event:{event.event_id}"
            add_node(
                GraphNode(
                    event_id,
                    "ProtocolEvent",
                    event.event_type.value,
                    event.model_dump(mode="json", exclude={"evidence"}),
                )
            )
            add_edge(
                GraphEdge(
                    article_id,
                    event_id,
                    "REPORTS_EVENT",
                    {"document_id": document_id},
                )
            )

        for index, asset in enumerate(record.provenance.assets):
            asset_id = _stable_id(
                "asset",
                [document_id, asset.role, asset.identifier, asset.source_uri, index],
            )
            add_node(
                GraphNode(
                    asset_id,
                    "MDAsset",
                    asset.identifier or asset.role,
                    asset.model_dump(mode="json"),
                )
            )
            add_edge(
                GraphEdge(
                    article_id,
                    asset_id,
                    "HAS_MD_ASSET",
                    {"role": asset.role, "document_id": document_id},
                )
            )

    for enrichment in pdbe_kb or []:
        structure_id = f"pdb:{enrichment.pdb_id}"
        add_node(
            GraphNode(
                structure_id,
                "Structure",
                enrichment.pdb_id,
                {"pdb_id": enrichment.pdb_id},
            )
        )
        for annotation in enrichment.annotations:
            annotation_id = f"pdbe-kb:{annotation.annotation_id}"
            add_node(
                GraphNode(
                    annotation_id,
                    "FunctionalAnnotation",
                    annotation.label or annotation.annotation_type,
                    annotation.model_dump(mode="json"),
                )
            )
            add_edge(
                GraphEdge(
                    structure_id,
                    annotation_id,
                    "HAS_FUNCTIONAL_ANNOTATION",
                    {
                        "provider": annotation.provider,
                        "chain_id": annotation.chain_id,
                        "residue_start": annotation.residue_start,
                        "residue_end": annotation.residue_end,
                    },
                )
            )

    return [nodes[key] for key in sorted(nodes)], [edges[key] for key in sorted(edges)]


def write_neo4j_csv(
    output_dir: str | Path,
    nodes: list[GraphNode],
    edges: list[GraphEdge],
) -> dict[str, Any]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    nodes_path = root / "nodes.csv"
    edges_path = root / "relationships.csv"

    with nodes_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["node_id:ID", ":LABEL", "name", "properties_json"])
        for node in nodes:
            writer.writerow(
                [
                    node.node_id,
                    node.labels,
                    node.name,
                    json.dumps(node.properties, sort_keys=True, separators=(",", ":")),
                ]
            )

    with edges_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([":START_ID", ":END_ID", ":TYPE", "properties_json"])
        for edge in edges:
            writer.writerow(
                [
                    edge.start_id,
                    edge.end_id,
                    edge.edge_type,
                    json.dumps(edge.properties, sort_keys=True, separators=(",", ":")),
                ]
            )

    manifest = {
        "schema_version": "neo4j-csv-export-v1",
        "node_count": len(nodes),
        "relationship_count": len(edges),
        "node_label_counts": dict(
            sorted(
                {
                    label: sum(node.labels == label for node in nodes)
                    for label in {node.labels for node in nodes}
                }.items()
            )
        ),
        "relationship_type_counts": dict(
            sorted(
                {
                    edge_type: sum(edge.edge_type == edge_type for edge in edges)
                    for edge_type in {edge.edge_type for edge in edges}
                }.items()
            )
        ),
        "files": {
            "nodes.csv": hashlib.sha256(nodes_path.read_bytes()).hexdigest(),
            "relationships.csv": hashlib.sha256(edges_path.read_bytes()).hexdigest(),
        },
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest
