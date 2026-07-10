from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import httpx


def compact_residue(item: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "residue_number",
        "author_residue_number",
        "author_insertion_code",
        "residue_name",
        "observed_ratio",
    )
    return {key: item.get(key) for key in keys if key in item}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdb-id", default="6vxx")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    pdb_id = args.pdb_id.lower()
    residue_url = f"https://www.ebi.ac.uk/pdbe/api/pdb/entry/residue_listing/{pdb_id}"
    mapping_url = f"https://www.ebi.ac.uk/pdbe/api/mappings/uniprot/{pdb_id}"
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        residue_response = client.get(residue_url)
        residue_response.raise_for_status()
        residue_payload = residue_response.json()
        mapping_response = client.get(mapping_url)
        mapping_response.raise_for_status()
        mapping_payload = mapping_response.json()

    root = residue_payload[pdb_id]
    molecules = root.get("molecules", [])
    chain_rows: list[dict[str, Any]] = []
    for molecule in molecules:
        for chain in molecule.get("chains", []):
            residues = chain.get("residues", [])
            chain_rows.append(
                {
                    "entity_id": molecule.get("entity_id"),
                    "molecule_name": molecule.get("molecule_name"),
                    "chain_id": chain.get("chain_id"),
                    "struct_asym_id": chain.get("struct_asym_id"),
                    "residue_count": len(residues),
                    "first_residues": [compact_residue(item) for item in residues[:3]],
                    "last_residues": [compact_residue(item) for item in residues[-3:]],
                    "chain_keys": sorted(chain),
                    "residue_keys": sorted(residues[0]) if residues else [],
                }
            )

    uniprot = mapping_payload.get(pdb_id, {}).get("UniProt", {})
    mapping_rows: list[dict[str, Any]] = []
    for accession, entry in sorted(uniprot.items()):
        for item in entry.get("mappings", []):
            mapping_rows.append(
                {
                    "accession": accession,
                    "chain_id": item.get("chain_id"),
                    "struct_asym_id": item.get("struct_asym_id"),
                    "unp_start": item.get("unp_start"),
                    "unp_end": item.get("unp_end"),
                    "start": item.get("start"),
                    "end": item.get("end"),
                    "mapping_keys": sorted(item),
                }
            )

    result = {
        "pdb_id": pdb_id.upper(),
        "residue_url": residue_url,
        "mapping_url": mapping_url,
        "root_keys": sorted(root),
        "molecule_count": len(molecules),
        "chains": chain_rows,
        "mapping_segment_count": len(mapping_rows),
        "mapping_segments": mapping_rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
