from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .storage import SQLiteRecordStore


class GraphExportManifest(BaseModel):
    """Content-bound manifest for a deterministic Neo4j bulk-import export."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["mdmeta-graph-export-v1"] = "mdmeta-graph-export-v1"
    source_database_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_database_schema_version: Literal[2]
    source_article_count: int = Field(ge=0)
    source_pdbekb_report_count: int = Field(ge=0)
    node_count: int = Field(ge=0)
    relationship_count: int = Field(ge=0)
    node_label_counts: dict[str, int]
    relationship_type_counts: dict[str, int]
    nodes_file: Literal["nodes.csv"] = "nodes.csv"
    nodes_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    relationships_file: Literal["relationships.csv"] = "relationships.csv"
    relationships_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    graph_commitment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_commitment(self) -> "GraphExportManifest":
        for label, count in self.node_label_counts.items():
            if not label or isinstance(count, bool) or count < 1:
                raise ValueError("node_label_counts must contain positive integer counts")
        for relationship_type, count in self.relationship_type_counts.items():
            if not relationship_type or isinstance(count, bool) or count < 1:
                raise ValueError(
                    "relationship_type_counts must contain positive integer counts"
                )
        if sum(self.node_label_counts.values()) != self.node_count:
            raise ValueError("node_label_counts do not sum to node_count")
        if sum(self.relationship_type_counts.values()) != self.relationship_count:
            raise ValueError(
                "relationship_type_counts do not sum to relationship_count"
            )
        body = self.model_dump(mode="json", exclude={"graph_commitment_sha256"})
        if self.graph_commitment_sha256 != _canonical_sha256(body):
            raise ValueError("graph_commitment_sha256 does not match manifest content")
        return self


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write(path: Path, content: bytes) -> None:
    if path.is_symlink():
        raise ValueError(f"refusing to replace symlink: {path}")
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _node_id(label: str, identifier: str) -> str:
    return f"{label.casefold()}:{identifier}"


def _content_node_id(label: str, content: object) -> str:
    return _node_id(label, _canonical_sha256(content))


def _relationship_id(
    start: str,
    relationship_type: str,
    end: str,
    properties: dict[str, object],
) -> str:
    return "relationship:" + _canonical_sha256(
        {
            "start": start,
            "type": relationship_type,
            "end": end,
            "properties": properties,
        }
    )


def _csv_bytes(header: list[str], rows: list[list[str]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def export_neo4j_graph(
    database: str | Path,
    output_dir: str | Path,
) -> GraphExportManifest:
    """Export a verified schema-v2 snapshot as deterministic Neo4j import CSVs."""

    database_path = Path(database)
    for suffix in ("-wal", "-shm"):
        if database_path.with_name(database_path.name + suffix).exists():
            raise RuntimeError("graph export requires a checkpointed database without sidecars")
    store = SQLiteRecordStore(database_path, read_only=True)
    if store.schema_version() != 2:
        raise RuntimeError("graph export requires database schema version 2")

    root = Path(output_dir)
    if root.is_symlink():
        raise ValueError("graph output directory must not be a symlink")
    root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise ValueError("graph output path is not a directory")

    nodes: dict[str, dict[str, str]] = {}
    relationships: dict[str, dict[str, str]] = {}

    def add_node(
        node_id: str,
        label: str,
        *,
        identifier: str = "",
        name: str = "",
        state: str = "",
        source_uri: str = "",
        properties: dict[str, object] | None = None,
    ) -> None:
        row = {
            "node_id": node_id,
            "label": label,
            "identifier": identifier,
            "name": name,
            "state": state,
            "source_uri": source_uri,
            "properties_json": _canonical_json(properties or {}),
        }
        previous = nodes.setdefault(node_id, row)
        if previous != row:
            raise ValueError(f"graph node identity collision: {node_id}")

    def add_relationship(
        start: str,
        relationship_type: str,
        end: str,
        *,
        source_document_id: str = "",
        properties: dict[str, object] | None = None,
    ) -> None:
        relationship_properties = properties or {}
        relationship_id = _relationship_id(
            start, relationship_type, end, relationship_properties
        )
        row = {
            "relationship_id": relationship_id,
            "start": start,
            "end": end,
            "type": relationship_type,
            "source_document_id": source_document_id,
            "properties_json": _canonical_json(relationship_properties),
        }
        previous = relationships.setdefault(relationship_id, row)
        if previous != row:
            raise ValueError(f"graph relationship identity collision: {relationship_id}")

    article_rows = store.verification_rows()
    for stored in article_rows:
        record = json.loads(str(stored["record_json"]))
        article = record["article"]
        document_id = str(article["document_id"])
        article_id = _node_id("Article", document_id)
        add_node(
            article_id,
            "Article",
            identifier=document_id,
            name=str(article["title"]),
            source_uri=str(article["source_uri"]),
            properties={
                "doi": article.get("doi"),
                "full_text_sha256": article["full_text_sha256"],
            },
        )

        for fact in record["literature_facts"]:
            if fact["field"] != "starting_pdb_id":
                continue
            pdb_id = str(fact["value"]).upper()
            pdb_node = _node_id("PDB", pdb_id)
            add_node(pdb_node, "PDB", identifier=pdb_id)
            evidence = fact["evidence"]
            add_relationship(
                article_id,
                "MENTIONS_STRUCTURE",
                pdb_node,
                source_document_id=document_id,
                properties={
                    "context_sha256": evidence["context_sha256"],
                    "paragraph_id": evidence["paragraph_id"],
                    "start_char": evidence["start_char"],
                    "end_char": evidence["end_char"],
                },
            )

        for event in record["protocol_events"]:
            event_content = {
                key: value
                for key, value in event.items()
                if key not in {"evidence"}
            }
            event_id = _node_id(
                "ProtocolEvent", f"{document_id}:{event['event_id']}"
            )
            add_node(
                event_id,
                "ProtocolEvent",
                identifier=str(event["event_id"]),
                name=str(event["event_type"]),
                properties=event_content,
            )
            evidence_bindings = [
                {
                    key: evidence[key]
                    for key in (
                        "paragraph_id",
                        "start_char",
                        "end_char",
                        "context_sha256",
                    )
                }
                for evidence in event["evidence"]
            ]
            add_relationship(
                article_id,
                "HAS_PROTOCOL_EVENT",
                event_id,
                source_document_id=document_id,
                properties={"evidence_bindings": evidence_bindings},
            )

        for mapping in record["residue_mappings"]:
            pdb_id = str(mapping["pdb_id"]).upper()
            accession = str(mapping["uniprot_accession"]).upper()
            pdb_node = _node_id("PDB", pdb_id)
            uniprot_node = _node_id("UniProt", accession)
            add_node(pdb_node, "PDB", identifier=pdb_id)
            add_node(uniprot_node, "UniProt", identifier=accession)
            mapping_properties = {
                "chain_id": mapping["chain_id"],
                "pdb_start": mapping["pdb_start"],
                "pdb_end": mapping["pdb_end"],
                "uniprot_start": mapping["uniprot_start"],
                "uniprot_end": mapping["uniprot_end"],
                "source_document_id": document_id,
            }
            add_relationship(
                article_id,
                "USES_STRUCTURE",
                pdb_node,
                source_document_id=document_id,
                properties={"chain_id": mapping["chain_id"]},
            )
            add_relationship(
                pdb_node,
                "SIFTS_MAPS_TO",
                uniprot_node,
                source_document_id=document_id,
                properties=mapping_properties,
            )

        for asset in record["provenance"]["assets"]:
            public_asset = {
                key: asset.get(key)
                for key in (
                    "role",
                    "identifier",
                    "availability",
                    "source_uri",
                    "sha256",
                    "media_type",
                    "reason",
                )
            }
            asset_id = _content_node_id(
                "MDAsset", {"document_id": document_id, **public_asset}
            )
            add_node(
                asset_id,
                "MDAsset",
                identifier=str(asset.get("identifier") or asset.get("sha256") or ""),
                name=str(asset["role"]),
                state=str(asset["availability"]),
                source_uri=str(asset.get("source_uri") or ""),
                properties=public_asset,
            )
            add_relationship(
                article_id,
                "HAS_MD_ASSET",
                asset_id,
                source_document_id=document_id,
            )

    enrichment_rows = store.list_pdbekb_enrichments()
    report_commitments: set[str] = set()
    for stored in enrichment_rows:
        report_commitment = str(stored["report_commitment_sha256"])
        report_commitments.add(report_commitment)
        enrichment = stored["enrichment"]
        if not isinstance(enrichment, dict):
            raise ValueError("stored PDBe-KB enrichment is not an object")
        accession = str(enrichment["accession"]).upper()
        uniprot_node = _node_id("UniProt", accession)
        add_node(uniprot_node, "UniProt", identifier=accession)
        for group in enrichment["annotation_groups"]:
            group_identity = {"uniprot_accession": accession, **group}
            annotation_node = _content_node_id("PDBeKBAnnotation", group_identity)
            add_node(
                annotation_node,
                "PDBeKBAnnotation",
                identifier=str(group["accession"]),
                name=str(group["name"]),
                properties={
                    "data_type": group["data_type"],
                    "residue_range_count": group["residue_range_count"],
                    "covered_sequence_position_count": group[
                        "covered_sequence_position_count"
                    ],
                    "resource_urls": group["resource_urls"],
                    "confidence_classifications": group[
                        "confidence_classifications"
                    ],
                },
            )
            add_relationship(
                uniprot_node,
                "HAS_PDBEKB_ANNOTATION",
                annotation_node,
                properties={
                    "report_commitment_sha256": report_commitment,
                    "enrichment_state": enrichment["state"],
                },
            )
            for pdb_id_value in group["pdb_ids"]:
                pdb_id = str(pdb_id_value).upper()
                pdb_node = _node_id("PDB", pdb_id)
                add_node(pdb_node, "PDB", identifier=pdb_id)
                add_relationship(
                    annotation_node,
                    "LINKS_STRUCTURE",
                    pdb_node,
                    properties={"report_commitment_sha256": report_commitment},
                )

        for partner in enrichment["partners"]:
            partner_identity = {
                "resource_name": partner["resource_name"],
                "url": partner["url"],
                "annotation_category": partner["annotation_category"],
            }
            partner_node = _content_node_id("AnnotationPartner", partner_identity)
            add_node(
                partner_node,
                "AnnotationPartner",
                identifier=str(partner["resource_name"]),
                name=str(partner["annotation_category"]),
                source_uri=str(partner["url"]),
                properties=partner_identity,
            )
            add_relationship(
                uniprot_node,
                "HAS_ANNOTATION_PARTNER",
                partner_node,
                properties={"report_commitment_sha256": report_commitment},
            )

    node_rows = [
        [
            row["node_id"],
            row["label"],
            row["identifier"],
            row["name"],
            row["state"],
            row["source_uri"],
            row["properties_json"],
        ]
        for row in sorted(nodes.values(), key=lambda item: item["node_id"])
    ]
    relationship_rows = [
        [
            row["relationship_id"],
            row["start"],
            row["end"],
            row["type"],
            row["source_document_id"],
            row["properties_json"],
        ]
        for row in sorted(
            relationships.values(), key=lambda item: item["relationship_id"]
        )
    ]
    nodes_content = _csv_bytes(
        [
            "node_id:ID",
            ":LABEL",
            "identifier",
            "name",
            "state",
            "source_uri",
            "properties_json",
        ],
        node_rows,
    )
    relationships_content = _csv_bytes(
        [
            "relationship_id",
            ":START_ID",
            ":END_ID",
            ":TYPE",
            "source_document_id",
            "properties_json",
        ],
        relationship_rows,
    )
    missing_endpoints = sorted(
        {
            endpoint
            for row in relationships.values()
            for endpoint in (row["start"], row["end"])
            if endpoint not in nodes
        }
    )
    if missing_endpoints:
        raise ValueError(f"graph relationships have missing endpoints: {missing_endpoints}")
    nodes_path = root / "nodes.csv"
    relationships_path = root / "relationships.csv"
    _atomic_write(nodes_path, nodes_content)
    _atomic_write(relationships_path, relationships_content)

    body: dict[str, Any] = {
        "schema_version": "mdmeta-graph-export-v1",
        "source_database_sha256": _file_sha256(database_path),
        "source_database_schema_version": 2,
        "source_article_count": len(article_rows),
        "source_pdbekb_report_count": len(report_commitments),
        "node_count": len(nodes),
        "relationship_count": len(relationships),
        "node_label_counts": dict(
            sorted(Counter(row["label"] for row in nodes.values()).items())
        ),
        "relationship_type_counts": dict(
            sorted(Counter(row["type"] for row in relationships.values()).items())
        ),
        "nodes_file": "nodes.csv",
        "nodes_sha256": hashlib.sha256(nodes_content).hexdigest(),
        "relationships_file": "relationships.csv",
        "relationships_sha256": hashlib.sha256(relationships_content).hexdigest(),
    }
    manifest = GraphExportManifest(
        **body,
        graph_commitment_sha256=_canonical_sha256(body),
    )
    _atomic_write(
        root / "graph-manifest.json",
        (json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )
    return manifest


def verify_neo4j_graph(
    output_dir: str | Path,
    *,
    database: str | Path | None = None,
) -> GraphExportManifest:
    """Verify hashes, counts, headers, identifiers and endpoints after transfer."""

    root = Path(output_dir)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("graph output must be a non-symlink directory")
    expected_names = {"nodes.csv", "relationships.csv", "graph-manifest.json"}
    candidates = list(root.iterdir())
    actual_names = {path.name for path in candidates}
    unsafe = sorted(path.name for path in candidates if path.is_symlink() or not path.is_file())
    if unsafe:
        raise ValueError("graph output contains unsafe paths: " + ", ".join(unsafe))
    if actual_names != expected_names:
        raise ValueError(
            "graph output inventory mismatch; "
            f"missing={sorted(expected_names - actual_names)}, "
            f"extra={sorted(actual_names - expected_names)}"
        )

    manifest = GraphExportManifest.model_validate_json(
        (root / "graph-manifest.json").read_text(encoding="utf-8")
    )
    nodes_path = root / manifest.nodes_file
    relationships_path = root / manifest.relationships_file
    if _file_sha256(nodes_path) != manifest.nodes_sha256:
        raise ValueError("nodes.csv SHA-256 does not match graph manifest")
    if _file_sha256(relationships_path) != manifest.relationships_sha256:
        raise ValueError("relationships.csv SHA-256 does not match graph manifest")
    if database is not None and _file_sha256(Path(database)) != manifest.source_database_sha256:
        raise ValueError("source database SHA-256 does not match graph manifest")

    with nodes_path.open(newline="", encoding="utf-8") as handle:
        node_reader = csv.DictReader(handle)
        if node_reader.fieldnames != [
            "node_id:ID",
            ":LABEL",
            "identifier",
            "name",
            "state",
            "source_uri",
            "properties_json",
        ]:
            raise ValueError("nodes.csv has an incompatible header")
        node_rows = list(node_reader)
    with relationships_path.open(newline="", encoding="utf-8") as handle:
        relationship_reader = csv.DictReader(handle)
        if relationship_reader.fieldnames != [
            "relationship_id",
            ":START_ID",
            ":END_ID",
            ":TYPE",
            "source_document_id",
            "properties_json",
        ]:
            raise ValueError("relationships.csv has an incompatible header")
        relationship_rows = list(relationship_reader)

    node_ids = [row["node_id:ID"] for row in node_rows]
    relationship_ids = [row["relationship_id"] for row in relationship_rows]
    if len(node_ids) != len(set(node_ids)) or any(not value for value in node_ids):
        raise ValueError("nodes.csv contains empty or duplicate node identifiers")
    if len(relationship_ids) != len(set(relationship_ids)) or any(
        not value for value in relationship_ids
    ):
        raise ValueError("relationships.csv contains empty or duplicate identifiers")
    for row in [*node_rows, *relationship_rows]:
        try:
            properties = json.loads(row["properties_json"])
        except json.JSONDecodeError as error:
            raise ValueError("graph row contains invalid properties_json") from error
        if not isinstance(properties, dict):
            raise ValueError("graph properties_json must contain an object")
    node_id_set = set(node_ids)
    missing_endpoints = sorted(
        {
            endpoint
            for row in relationship_rows
            for endpoint in (row[":START_ID"], row[":END_ID"])
            if endpoint not in node_id_set
        }
    )
    if missing_endpoints:
        raise ValueError(f"relationships.csv has missing endpoints: {missing_endpoints}")
    if len(node_rows) != manifest.node_count:
        raise ValueError("nodes.csv row count does not match graph manifest")
    if len(relationship_rows) != manifest.relationship_count:
        raise ValueError("relationships.csv row count does not match graph manifest")
    if dict(sorted(Counter(row[":LABEL"] for row in node_rows).items())) != (
        manifest.node_label_counts
    ):
        raise ValueError("nodes.csv label counts do not match graph manifest")
    if dict(sorted(Counter(row[":TYPE"] for row in relationship_rows).items())) != (
        manifest.relationship_type_counts
    ):
        raise ValueError("relationships.csv type counts do not match graph manifest")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Export or verify a Neo4j graph projection.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--database", type=Path, required=True)
    export_parser.add_argument("--output-dir", type=Path, required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--output-dir", type=Path, required=True)
    verify_parser.add_argument("--database", type=Path)
    args = parser.parse_args()
    if args.command == "export":
        manifest = export_neo4j_graph(args.database, args.output_dir)
    else:
        manifest = verify_neo4j_graph(args.output_dir, database=args.database)
    print(json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
