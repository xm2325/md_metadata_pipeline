from mdmeta.models import MappingSegment
from mdmeta.sifts_qa import audit_sifts_segments


def segment(
    *,
    pdb_id: str = "6VSB",
    accession: str = "P0DTC2",
    chain: str = "A",
    pdb_start: int | None = 1,
    pdb_end: int | None = 10,
    uniprot_start: int | None = 1,
    uniprot_end: int | None = 10,
) -> MappingSegment:
    return MappingSegment(
        pdb_id=pdb_id,
        uniprot_accession=accession,
        chain_id=chain,
        pdb_start=pdb_start,
        pdb_end=pdb_end,
        uniprot_start=uniprot_start,
        uniprot_end=uniprot_end,
    )


def test_clean_segments_have_no_issues() -> None:
    report = audit_sifts_segments(
        [
            segment(pdb_start=1, pdb_end=10, uniprot_start=11, uniprot_end=20),
            segment(pdb_start=11, pdb_end=20, uniprot_start=21, uniprot_end=30),
        ]
    )
    assert report.segment_count == 2
    assert report.length_consistent_count == 2
    assert report.issues == []


def test_incomplete_reversed_and_length_mismatch_are_distinguished() -> None:
    report = audit_sifts_segments(
        [
            segment(pdb_start=None),
            segment(pdb_start=10, pdb_end=1),
            segment(pdb_start=1, pdb_end=10, uniprot_start=1, uniprot_end=9),
        ]
    )
    assert report.issue_counts == {
        "incomplete_range": 1,
        "length_mismatch": 1,
        "overlapping_pdb_ranges": 1,
        "reversed_range": 1,
    }
    assert report.severity_counts["error"] == 1


def test_duplicate_overlap_and_multi_accession_chain_remain_auditable() -> None:
    first = segment(pdb_start=1, pdb_end=10)
    report = audit_sifts_segments(
        [
            first,
            first.model_copy(),
            segment(pdb_start=8, pdb_end=15, uniprot_start=8, uniprot_end=15),
            segment(
                accession="P0DTC2-2",
                pdb_start=16,
                pdb_end=20,
                uniprot_start=16,
                uniprot_end=20,
            ),
        ]
    )
    assert report.issue_counts["duplicate_segment"] == 1
    assert report.issue_counts["overlapping_pdb_ranges"] >= 1
    assert report.issue_counts["multi_accession_chain"] == 1
    assert report.multi_accession_chain_count == 1
    multi = next(issue for issue in report.issues if issue.code == "multi_accession_chain")
    assert multi.severity == "info"
    assert "must not be collapsed silently" in multi.message
