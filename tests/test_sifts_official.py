from __future__ import annotations

import csv
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from mdmeta.sifts_official import (
    OfficialSIFTSCompatibilityReport,
    PDBE_SIFTS_1CBS_RESIDUE_SHA256,
    PDBE_SIFTS_1CBS_SEGMENT_SHA256,
    PDBE_SIFTS_COMMIT,
    PDBE_SIFTS_REPOSITORY,
    PDBE_SIFTS_VERSION,
    parse_official_residue_csv,
    parse_official_segment_csv,
    to_mapping_segments,
)


def _write(path: Path, rows: list[list[object]]) -> Path:
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        csv.writer(handle, lineterminator="\n").writerows(rows)
    return path


def _segment(**updates: object) -> list[object]:
    values: list[object] = [
        "1abc",
        1,
        1,
        "A",
        "A",
        "Q12345-2",
        "FIXTURE_HUMAN",
        3,
        10,
        1,
        14,
        5,
        -2,
        "A",
        2,
        "",
        0,
        1,
        "ABCDE",
        "ABCDE",
        1.0,
        100.0,
        1,
        0,
        "Q12345",
        1,
    ]
    indexes = {"best_mapping": 22, "chimera": 25, "entry_id": 0}
    for key, value in updates.items():
        values[indexes[key]] = value
    return values


def _residue(**updates: object) -> list[object]:
    values: list[object] = [
        "1abc",
        1,
        1,
        "A",
        "A",
        1,
        -2,
        "A",
        1,
        10,
        "N",
        "",
        "Q12345-2",
        "FIXTURE_HUMAN",
        "Insertion",
        "A",
        "A",
        "ALA",
        1,
        9606,
        0,
        "Q12345",
        1,
        "1abc_A_1",
    ]
    indexes = {"observed": 10, "entry_id": 0, "best_mapping": 22}
    for key, value in updates.items():
        values[indexes[key]] = value
    return values


def test_parses_isoform_chimera_insertion_and_unobserved_residue(tmp_path: Path) -> None:
    segments = parse_official_segment_csv(
        _write(tmp_path / "segments.csv.gz", [_segment()]),
        expected_entry_id="1ABC",
    )
    residues = parse_official_residue_csv(
        _write(tmp_path / "residues.csv.gz", [_residue()]),
        expected_entry_id="1abc",
    )

    assert segments[0].accession == "Q12345-2"
    assert segments[0].chimera is True
    assert segments[0].author_start == -2
    assert segments[0].author_start_insertion_code == "A"
    assert residues[0].observed == "N"
    assert residues[0].author_insertion_code == "A"
    assert to_mapping_segments(segments)[0].model_dump() == {
        "pdb_id": "1ABC",
        "uniprot_accession": "Q12345-2",
        "chain_id": "A",
        "pdb_start": 1,
        "pdb_end": 5,
        "uniprot_start": 10,
        "uniprot_end": 14,
    }


def test_non_best_mapping_is_preserved_but_not_projected(tmp_path: Path) -> None:
    segments = parse_official_segment_csv(
        _write(tmp_path / "segments.csv.gz", [_segment(best_mapping=0)])
    )

    assert segments[0].best_mapping is False
    assert to_mapping_segments(segments) == []


def test_compatibility_report_is_content_bound() -> None:
    body = {
        "schema_version": "mdmeta-pdbe-sifts-compatibility-v1",
        "upstream_repository": PDBE_SIFTS_REPOSITORY,
        "upstream_version": PDBE_SIFTS_VERSION,
        "upstream_commit": PDBE_SIFTS_COMMIT,
        "fixture_entry_id": "1cbs",
        "segment_fixture_sha256": PDBE_SIFTS_1CBS_SEGMENT_SHA256,
        "residue_fixture_sha256": PDBE_SIFTS_1CBS_RESIDUE_SHA256,
        "segment_row_count": 1,
        "residue_row_count": 1,
        "official_reader_segment_count": 1,
        "official_reader_mapped_residue_count": 1,
        "mapping_segment_count": 1,
        "mapped_best_residue_count": 1,
        "accession_counts": {"P29373": 1},
        "observed_state_counts": {"Y": 1},
        "insertion_code_count": 0,
        "isoform_segment_count": 0,
        "chimera_segment_count": 0,
        "raw_sequences_retained": False,
    }
    commitment = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    report = OfficialSIFTSCompatibilityReport(
        **body, content_commitment_sha256=commitment
    )

    assert report.mapping_segment_count == 1
    assert report.mapped_best_residue_count == 1
    payload = report.model_dump(mode="json")
    payload["content_commitment_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="content_commitment_sha256"):
        OfficialSIFTSCompatibilityReport.model_validate(payload)


def test_rejects_wrong_column_count_and_non_numeric_boolean(tmp_path: Path) -> None:
    short = _segment()[:-1]
    with pytest.raises(ValueError, match="25 columns; expected 26"):
        parse_official_segment_csv(_write(tmp_path / "short.csv.gz", [short]))

    invalid = _segment(best_mapping="true")
    with pytest.raises(ValueError, match="best_mapping must be encoded as 0 or 1"):
        parse_official_segment_csv(_write(tmp_path / "boolean.csv.gz", [invalid]))


def test_rejects_entry_mismatch_and_row_limit(tmp_path: Path) -> None:
    path = _write(tmp_path / "segments.csv.gz", [_segment(), _segment()])
    with pytest.raises(ValueError, match="expected_entry_id"):
        parse_official_segment_csv(path, expected_entry_id="2xyz")
    with pytest.raises(ValueError, match="row limit"):
        parse_official_segment_csv(path, max_rows=1)


def test_rejects_oversized_fields_and_invalid_gzip(tmp_path: Path) -> None:
    oversized = _write(tmp_path / "oversized.csv.gz", [_segment()])
    with pytest.raises(ValueError, match="field-size limit"):
        parse_official_segment_csv(oversized, max_field_chars=4)

    invalid = tmp_path / "invalid.csv.gz"
    invalid.write_bytes(b"not gzip")
    with pytest.raises(ValueError, match="valid UTF-8 gzip CSV"):
        parse_official_segment_csv(invalid)


def test_rejects_symlinked_input(tmp_path: Path) -> None:
    source = _write(tmp_path / "segments.csv.gz", [_segment()])
    link = tmp_path / "linked.csv.gz"
    try:
        link.symlink_to(source)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(ValueError, match="non-symlink"):
        parse_official_segment_csv(link)
