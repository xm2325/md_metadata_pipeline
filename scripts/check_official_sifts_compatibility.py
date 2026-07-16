from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from mdmeta.sifts_official import (
    PDBE_SIFTS_1CBS_RESIDUE_SHA256,
    PDBE_SIFTS_1CBS_SEGMENT_SHA256,
    PDBE_SIFTS_COMMIT,
    build_compatibility_report,
    parse_official_residue_csv,
    parse_official_segment_csv,
    sha256_file,
    to_mapping_segments,
)


def _official_residue_mapping_count(data: dict) -> int:
    return sum(
        len(rows)
        for entity in data.values()
        for chain in entity.values()
        for rows in chain.values()
    )


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("refusing to replace a symlinked compatibility report")
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def check_official_sifts_compatibility(
    official_source: str | Path,
    output: str | Path,
) -> dict[str, object]:
    source = Path(official_source).resolve(strict=True)
    commit = subprocess.run(  # noqa: S603
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if commit != PDBE_SIFTS_COMMIT:
        raise ValueError(f"official SIFTS source commit mismatch: {commit}")
    segment_path = source / "tests" / "data" / "sifts_csv" / "1cbs_seg.csv.gz"
    residue_path = source / "tests" / "data" / "sifts_csv" / "1cbs_res.csv.gz"
    if sha256_file(segment_path) != PDBE_SIFTS_1CBS_SEGMENT_SHA256:
        raise ValueError("official SIFTS segment fixture hash mismatch")
    if sha256_file(residue_path) != PDBE_SIFTS_1CBS_RESIDUE_SHA256:
        raise ValueError("official SIFTS residue fixture hash mismatch")

    segments = parse_official_segment_csv(segment_path, expected_entry_id="1cbs")
    residues = parse_official_residue_csv(residue_path, expected_entry_id="1cbs")
    sys.path.insert(0, str(source / "src"))
    try:
        from pdbe_sifts.sifts_to_mmcif.read_sifts_csv import (
            get_unp_segments,
            get_unpres_mapping,
        )

        official_segments, _ = get_unp_segments("1cbs", segment_path, None)
        official_residues, _ = get_unpres_mapping("1cbs", residue_path, None)
    finally:
        sys.path.pop(0)

    official_segment_count = len(official_segments[0])
    official_residue_count = _official_residue_mapping_count(official_residues)
    mappings = to_mapping_segments(segments)
    if official_segment_count != len(mappings):
        raise ValueError("official and mdmeta segment counts differ")
    mapped_residue_count = sum(
        residue.best_mapping
        and residue.accession is not None
        and residue.uniprot_sequence_id is not None
        for residue in residues
    )
    if mapped_residue_count != official_residue_count:
        raise ValueError("official and mdmeta mapped residue counts differ")
    if len(mappings) != 1 or mappings[0].model_dump() != {
        "pdb_id": "1CBS",
        "uniprot_accession": "P29373",
        "chain_id": "A",
        "pdb_start": 1,
        "pdb_end": 137,
        "uniprot_start": 2,
        "uniprot_end": 138,
    }:
        raise ValueError("1CBS mapping differs from the pinned official fixture")

    report = build_compatibility_report(
        segment_path=segment_path,
        residue_path=residue_path,
        segments=segments,
        residues=residues,
        official_reader_segment_count=official_segment_count,
        official_reader_mapped_residue_count=official_residue_count,
    )
    destination = Path(output)
    payload = report.model_dump(mode="json")
    _atomic_json(destination, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check mdmeta against a pinned official PDBe-SIFTS release."
    )
    parser.add_argument("--official-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            check_official_sifts_compatibility(args.official_source, args.output),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
