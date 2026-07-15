from __future__ import annotations

from collections import Counter, defaultdict
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import MappingSegment


class SIFTSQAIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: Literal["info", "warning", "error"]
    message: str
    segment_indexes: list[int] = Field(default_factory=list)


class SIFTSQAReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["sifts-compatibility-report-v1"] = "sifts-compatibility-report-v1"
    segment_count: int = Field(ge=0)
    complete_range_count: int = Field(ge=0)
    length_consistent_count: int = Field(ge=0)
    chain_count: int = Field(ge=0)
    multi_accession_chain_count: int = Field(ge=0)
    issue_counts: dict[str, int]
    severity_counts: dict[str, int]
    issues: list[SIFTSQAIssue]
    interpretation: list[str]


def _key(segment: MappingSegment) -> tuple[object, ...]:
    return (
        segment.pdb_id.upper(),
        segment.uniprot_accession,
        segment.chain_id,
        segment.pdb_start,
        segment.pdb_end,
        segment.uniprot_start,
        segment.uniprot_end,
    )


def audit_sifts_segments(segments: list[MappingSegment]) -> SIFTSQAReport:
    issues: list[SIFTSQAIssue] = []
    complete_range_count = 0
    length_consistent_count = 0

    duplicate_groups: dict[tuple[object, ...], list[int]] = defaultdict(list)
    by_mapping: dict[tuple[str, str, str], list[tuple[int, MappingSegment]]] = defaultdict(list)
    by_chain: dict[tuple[str, str], set[str]] = defaultdict(set)

    for index, segment in enumerate(segments):
        duplicate_groups[_key(segment)].append(index)
        mapping_key = (
            segment.pdb_id.upper(),
            segment.chain_id,
            segment.uniprot_accession,
        )
        by_mapping[mapping_key].append((index, segment))
        by_chain[(segment.pdb_id.upper(), segment.chain_id)].add(segment.uniprot_accession)

        values = (
            segment.pdb_start,
            segment.pdb_end,
            segment.uniprot_start,
            segment.uniprot_end,
        )
        if any(value is None for value in values):
            issues.append(
                SIFTSQAIssue(
                    code="incomplete_range",
                    severity="warning",
                    message=(
                        "The mapping lacks at least one PDB or UniProt boundary. Coverage and "
                        "length consistency cannot be verified from this segment alone."
                    ),
                    segment_indexes=[index],
                )
            )
            continue

        complete_range_count += 1
        assert segment.pdb_start is not None
        assert segment.pdb_end is not None
        assert segment.uniprot_start is not None
        assert segment.uniprot_end is not None
        if segment.pdb_end < segment.pdb_start or segment.uniprot_end < segment.uniprot_start:
            issues.append(
                SIFTSQAIssue(
                    code="reversed_range",
                    severity="error",
                    message="A mapping end precedes its start.",
                    segment_indexes=[index],
                )
            )
            continue

        pdb_length = segment.pdb_end - segment.pdb_start + 1
        uniprot_length = segment.uniprot_end - segment.uniprot_start + 1
        if pdb_length == uniprot_length:
            length_consistent_count += 1
        else:
            issues.append(
                SIFTSQAIssue(
                    code="length_mismatch",
                    severity="warning",
                    message=(
                        f"PDB span length {pdb_length} differs from UniProt span length "
                        f"{uniprot_length}; inspect gaps, engineered residues, numbering or "
                        "provider semantics before composing an MD-residue mapping."
                    ),
                    segment_indexes=[index],
                )
            )

    for indexes in duplicate_groups.values():
        if len(indexes) > 1:
            issues.append(
                SIFTSQAIssue(
                    code="duplicate_segment",
                    severity="warning",
                    message="An identical mapping segment appears more than once.",
                    segment_indexes=indexes,
                )
            )

    for mapping_key, rows in sorted(by_mapping.items()):
        complete = [
            (index, segment)
            for index, segment in rows
            if segment.pdb_start is not None and segment.pdb_end is not None
        ]
        complete.sort(key=lambda item: (item[1].pdb_start, item[1].pdb_end, item[0]))
        for left, right in zip(complete, complete[1:], strict=False):
            left_end = left[1].pdb_end
            right_start = right[1].pdb_start
            assert left_end is not None and right_start is not None
            if right_start <= left_end:
                issues.append(
                    SIFTSQAIssue(
                        code="overlapping_pdb_ranges",
                        severity="warning",
                        message=(
                            "Segments for the same PDB chain and UniProt accession overlap; "
                            "deduplicate or verify alternative mappings before residue projection."
                        ),
                        segment_indexes=[left[0], right[0]],
                    )
                )

    multi_accession_chain_count = 0
    for (pdb_id, chain_id), accessions in sorted(by_chain.items()):
        if len(accessions) > 1:
            multi_accession_chain_count += 1
            indexes = [
                index
                for index, segment in enumerate(segments)
                if segment.pdb_id.upper() == pdb_id and segment.chain_id == chain_id
            ]
            issues.append(
                SIFTSQAIssue(
                    code="multi_accession_chain",
                    severity="info",
                    message=(
                        f"PDB {pdb_id} chain {chain_id} maps to multiple UniProt accessions: "
                        f"{', '.join(sorted(accessions))}. This may represent a chimera, isoform, "
                        "construct boundary or ambiguous mapping and must not be collapsed silently."
                    ),
                    segment_indexes=indexes,
                )
            )

    issue_counts = dict(sorted(Counter(issue.code for issue in issues).items()))
    severity_counts = dict(sorted(Counter(issue.severity for issue in issues).items()))
    interpretation = [
        "Warnings identify records requiring review; they are not automatically biological errors.",
        "A length mismatch can be valid when the source mapping contains gaps or construct changes.",
        "The current MappingSegment model stores integer ranges only; author insertion codes and "
        "per-residue mutation identity require an official SIFTS residue-level compatibility run.",
    ]
    return SIFTSQAReport(
        segment_count=len(segments),
        complete_range_count=complete_range_count,
        length_consistent_count=length_consistent_count,
        chain_count=len(by_chain),
        multi_accession_chain_count=multi_accession_chain_count,
        issue_counts=issue_counts,
        severity_counts=severity_counts,
        issues=issues,
        interpretation=interpretation,
    )
