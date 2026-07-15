from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from mdmeta.graph_export import build_graph, write_neo4j_csv
from mdmeta.integration import IntegratedMDRecord
from mdmeta.pdbe_kb import PDBeKBEnrichment


def _load_records(path: Path) -> list[IntegratedMDRecord]:
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and payload.get("schema_version") == "integrated-md-record-v1":
        return [IntegratedMDRecord.model_validate(payload)]
    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        return [IntegratedMDRecord.model_validate(row) for row in payload["records"]]
    if isinstance(payload, list):
        return [IntegratedMDRecord.model_validate(row) for row in payload]
    raise ValueError("records input must contain one IntegratedMDRecord or a records list")


def _load_pdbe_kb(path: Path | None) -> list[PDBeKBEnrichment]:
    if path is None:
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("enrichments") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("PDBe-KB input must contain an enrichments list")
    return [PDBeKBEnrichment.model_validate(row) for row in rows]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export integrated MD metadata as Neo4j bulk-import CSV files."
    )
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--pdbe-kb", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    nodes, edges = build_graph(_load_records(args.records), _load_pdbe_kb(args.pdbe_kb))
    manifest = write_neo4j_csv(args.output_dir, nodes, edges)
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
