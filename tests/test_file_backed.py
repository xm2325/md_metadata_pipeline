from __future__ import annotations

import hashlib
from pathlib import Path

from mdmeta.file_backed import (
    ResidueRecord,
    canonical_sha256,
    compose_residue_mapping,
    fitting_alignment,
    sha256_file,
)


def test_fitting_alignment_places_short_pdb_chain_inside_full_md_chain() -> None:
    result = fitting_alignment("XXABCDEYY", "ABCDE")
    aligned = [(md_index, pdb_index) for md_index, pdb_index in result.pairs if pdb_index]
    assert aligned == [(3, 1), (4, 2), (5, 3), (6, 4), (7, 5)]
    assert result.matches == 5
    assert result.mismatches == 0
    assert result.score == 10


def test_composes_md_pdb_and_length_consistent_sifts_segment() -> None:
    md_letters = "ABCDE"
    pdb_letters = "ABCDE"
    md_chains = {
        "A": [
            ResidueRecord(
                chain_id="A",
                sequence_index=index,
                residue_name="ALA",
                one_letter=letter,
                md_resid=19 + index,
            )
            for index, letter in enumerate(md_letters, start=1)
        ]
    }
    pdb_chains = {
        "A": [
            ResidueRecord(
                chain_id="A",
                sequence_index=index,
                residue_name="ALA",
                one_letter=letter,
                residue_number=index,
                author_residue_number=99 + index,
            )
            for index, letter in enumerate(pdb_letters, start=1)
        ]
    }
    mapping_payload = {
        "1abc": {
            "UniProt": {
                "P12345": {
                    "mappings": [
                        {
                            "chain_id": "A",
                            "unp_start": 10,
                            "unp_end": 14,
                            "start": {"residue_number": 1},
                            "end": {"residue_number": 5},
                        }
                    ]
                }
            }
        }
    }

    audit, rows = compose_residue_mapping(
        md_chains=md_chains,
        pdb_chains=pdb_chains,
        mapping_payload=mapping_payload,
        pdb_id="1ABC",
        expected_uniprot_accessions=["P12345"],
    )

    assert audit.status == "verified"
    assert audit.mapped_md_to_pdb == 5
    assert audit.mapped_md_to_pdb_to_uniprot == 5
    assert audit.pdb_mapping_coverage == 1
    assert audit.uniprot_mapping_coverage == 1
    assert [row.uniprot_residue_number for row in rows] == [10, 11, 12, 13, 14]
    assert {row.mapping_status for row in rows} == {"verified_md_to_pdb_to_uniprot"}


def test_does_not_compose_length_inconsistent_sifts_segment() -> None:
    md_chains = {
        "A": [
            ResidueRecord(
                chain_id="A",
                sequence_index=1,
                residue_name="ALA",
                one_letter="A",
                md_resid=1,
            )
        ]
    }
    pdb_chains = {
        "A": [
            ResidueRecord(
                chain_id="A",
                sequence_index=1,
                residue_name="ALA",
                one_letter="A",
                residue_number=1,
                author_residue_number=27,
            )
        ]
    }
    mapping_payload = {
        "1abc": {
            "UniProt": {
                "P12345": {
                    "mappings": [
                        {
                            "chain_id": "A",
                            "unp_start": 10,
                            "unp_end": 12,
                            "start": {"residue_number": 1},
                            "end": {"residue_number": 1},
                        }
                    ]
                }
            }
        }
    }

    audit, rows = compose_residue_mapping(
        md_chains=md_chains,
        pdb_chains=pdb_chains,
        mapping_payload=mapping_payload,
        pdb_id="1ABC",
        expected_uniprot_accessions=["P12345"],
    )

    assert audit.status == "failed"
    assert rows[0].mapping_status == "sifts_segment_length_conflict"
    assert rows[0].uniprot_residue_number is None


def test_file_and_canonical_hashes_are_reproducible(tmp_path: Path) -> None:
    path = tmp_path / "asset.bin"
    path.write_bytes(b"abc")
    assert sha256_file(path) == hashlib.sha256(b"abc").hexdigest()
    assert canonical_sha256({"b": 2, "a": 1}) == canonical_sha256({"a": 1, "b": 2})
