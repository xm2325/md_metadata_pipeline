from __future__ import annotations

import csv
import gzip
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Iterator, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import MappingSegment


PDBE_SIFTS_REPOSITORY = "https://github.com/PDBeurope/SIFTS"
PDBE_SIFTS_VERSION = "v1.0.4"
PDBE_SIFTS_COMMIT = "155a4258536078ff0251644f154e895b7da6c492"
PDBE_SIFTS_1CBS_SEGMENT_SHA256 = (
    "7c6421b6b7a029833787b63c3fbe8987ded16949e745a09c419718cb4f11976b"
)
PDBE_SIFTS_1CBS_RESIDUE_SHA256 = (
    "93f66ad23693474d332ed9d1418f3daabe2f0c78fc22c21c31dbe5a8a7f5dc55"
)
_PDB_ID = re.compile(r"^[0-9][a-z0-9]{3}$")
_UNIPROT_ACCESSION = re.compile(r"^[A-Z0-9]{6,10}(?:-[1-9][0-9]*)?$")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OfficialSIFTSegment(_StrictModel):
    entry_id: str
    entity_id: int = Field(ge=1)
    segment_id: int = Field(ge=1)
    auth_asym_id: str
    struct_asym_id: str
    accession: str | None = None
    name: str | None = None
    sequence_version: int | None = Field(default=None, ge=1)
    uniprot_start: int | None = Field(default=None, ge=1)
    pdb_start: int = Field(ge=1)
    uniprot_end: int | None = Field(default=None, ge=1)
    pdb_end: int = Field(ge=1)
    author_start: int
    author_start_insertion_code: str | None = Field(default=None, max_length=1)
    author_end: int
    author_end_insertion_code: str | None = Field(default=None, max_length=1)
    conflict_count: int | None = Field(default=None, ge=0)
    modification_count: int | None = Field(default=None, ge=0)
    uniprot_alignment: str | None = None
    pdb_alignment: str
    identity: float | None = Field(default=None, ge=0, le=1)
    score: float | None = None
    best_mapping: bool
    canonical_accession: bool
    reference_accession: str | None = None
    chimera: bool

    @model_validator(mode="after")
    def validate_ranges_and_identifiers(self) -> "OfficialSIFTSegment":
        if not _PDB_ID.fullmatch(self.entry_id):
            raise ValueError("entry_id is not a lower-case PDB identifier")
        if self.pdb_end < self.pdb_start:
            raise ValueError("PDB segment end precedes start")
        if not self.auth_asym_id and not self.struct_asym_id:
            raise ValueError("segment requires an author or structural chain identifier")
        if self.accession is not None:
            if not _UNIPROT_ACCESSION.fullmatch(self.accession):
                raise ValueError("segment has an invalid UniProt accession")
            if self.uniprot_start is None or self.uniprot_end is None:
                raise ValueError("mapped segment requires a complete UniProt range")
        if (self.uniprot_start is None) != (self.uniprot_end is None):
            raise ValueError("UniProt segment range must be complete or absent")
        if (
            self.uniprot_start is not None
            and self.uniprot_end is not None
            and self.uniprot_end < self.uniprot_start
        ):
            raise ValueError("UniProt segment end precedes start")
        return self


class OfficialSIFTSResidue(_StrictModel):
    entry_id: str
    entity_id: int = Field(ge=1)
    residue_ordinal: int = Field(ge=1)
    auth_asym_id: str
    struct_asym_id: str
    uniprot_segment_id: int = Field(ge=1)
    author_sequence_id: int | None = None
    author_insertion_code: str | None = Field(default=None, max_length=1)
    pdb_sequence_id: int = Field(ge=1)
    uniprot_sequence_id: int | None = Field(default=None, ge=1)
    observed: Literal["Y", "N"]
    database_entry_id: int | None = None
    accession: str | None = None
    name: str | None = None
    residue_type: str | None = None
    uniprot_one_letter_code: str | None = Field(default=None, max_length=1)
    pdb_one_letter_code: str
    chemical_component_id: str
    model_homologue_id: int | None = None
    taxonomy_id: int | None = Field(default=None, ge=1)
    canonical_accession: bool
    reference_accession: str | None = None
    best_mapping: bool
    residue_id: str

    @model_validator(mode="after")
    def validate_identifiers(self) -> "OfficialSIFTSResidue":
        if not _PDB_ID.fullmatch(self.entry_id):
            raise ValueError("entry_id is not a lower-case PDB identifier")
        if not self.auth_asym_id and not self.struct_asym_id:
            raise ValueError("residue requires an author or structural chain identifier")
        if self.accession is not None and not _UNIPROT_ACCESSION.fullmatch(
            self.accession
        ):
            raise ValueError("residue has an invalid UniProt accession")
        if self.accession is None and self.uniprot_sequence_id is not None:
            raise ValueError("unmapped residue cannot contain a UniProt position")
        return self


class OfficialSIFTSCompatibilityReport(_StrictModel):
    schema_version: Literal["mdmeta-pdbe-sifts-compatibility-v1"] = (
        "mdmeta-pdbe-sifts-compatibility-v1"
    )
    upstream_repository: Literal[PDBE_SIFTS_REPOSITORY]
    upstream_version: Literal[PDBE_SIFTS_VERSION]
    upstream_commit: Literal[PDBE_SIFTS_COMMIT]
    fixture_entry_id: Literal["1cbs"]
    segment_fixture_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    residue_fixture_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    segment_row_count: int = Field(ge=0)
    residue_row_count: int = Field(ge=0)
    official_reader_segment_count: int = Field(ge=0)
    official_reader_mapped_residue_count: int = Field(ge=0)
    mapping_segment_count: int = Field(ge=0)
    mapped_best_residue_count: int = Field(ge=0)
    accession_counts: dict[str, int]
    observed_state_counts: dict[str, int]
    insertion_code_count: int = Field(ge=0)
    isoform_segment_count: int = Field(ge=0)
    chimera_segment_count: int = Field(ge=0)
    raw_sequences_retained: Literal[False] = False
    content_commitment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_commitment(self) -> "OfficialSIFTSCompatibilityReport":
        if self.segment_fixture_sha256 != PDBE_SIFTS_1CBS_SEGMENT_SHA256:
            raise ValueError("segment fixture hash differs from pinned official fixture")
        if self.residue_fixture_sha256 != PDBE_SIFTS_1CBS_RESIDUE_SHA256:
            raise ValueError("residue fixture hash differs from pinned official fixture")
        if sum(self.accession_counts.values()) != self.segment_row_count:
            raise ValueError("accession_counts do not sum to segment_row_count")
        if sum(self.observed_state_counts.values()) != self.residue_row_count:
            raise ValueError("observed_state_counts do not sum to residue_row_count")
        if self.mapping_segment_count != self.official_reader_segment_count:
            raise ValueError("mapping count differs from the pinned official reader")
        if self.mapped_best_residue_count != self.official_reader_mapped_residue_count:
            raise ValueError("mapped residue count differs from the pinned official reader")
        body = self.model_dump(mode="json", exclude={"content_commitment_sha256"})
        if self.content_commitment_sha256 != _canonical_sha256(body):
            raise ValueError("content_commitment_sha256 does not match report content")
        return self


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _text(value: str) -> str:
    return value.strip()


def _optional_text(value: str) -> str | None:
    stripped = value.strip()
    return stripped or None


def _integer(value: str, *, field: str, optional: bool = False) -> int | None:
    stripped = value.strip()
    if optional and not stripped:
        return None
    try:
        return int(stripped)
    except ValueError as error:
        raise ValueError(f"{field} is not an integer") from error


def _float(value: str, *, field: str, optional: bool = False) -> float | None:
    stripped = value.strip()
    if optional and not stripped:
        return None
    try:
        return float(stripped)
    except ValueError as error:
        raise ValueError(f"{field} is not a float") from error


def _boolean(value: str, *, field: str) -> bool:
    stripped = value.strip()
    if stripped not in {"0", "1"}:
        raise ValueError(f"{field} must be encoded as 0 or 1")
    return stripped == "1"


def _rows(
    path: str | Path,
    *,
    expected_columns: int,
    max_rows: int,
    max_field_chars: int,
) -> Iterator[list[str]]:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError("SIFTS CSV must be a non-symlink regular file")
    if max_rows < 1:
        raise ValueError("max_rows must be positive")
    if max_field_chars < 1:
        raise ValueError("max_field_chars must be positive")
    previous_field_limit = csv.field_size_limit()
    csv.field_size_limit(max(previous_field_limit, max_field_chars))
    try:
        try:
            with gzip.open(source, mode="rt", encoding="utf-8", newline="") as handle:
                for row_number, row in enumerate(csv.reader(handle), start=1):
                    if row_number > max_rows:
                        raise ValueError("SIFTS CSV exceeds the configured row limit")
                    if len(row) != expected_columns:
                        raise ValueError(
                            f"SIFTS CSV row {row_number} has {len(row)} columns; "
                            f"expected {expected_columns}"
                        )
                    if any(len(value) > max_field_chars for value in row):
                        raise ValueError(
                            f"SIFTS CSV row {row_number} exceeds the field-size limit"
                        )
                    yield row
        except (OSError, EOFError, UnicodeDecodeError, csv.Error) as error:
            raise ValueError("SIFTS input is not a valid UTF-8 gzip CSV") from error
    finally:
        csv.field_size_limit(previous_field_limit)


def parse_official_segment_csv(
    path: str | Path,
    *,
    expected_entry_id: str | None = None,
    max_rows: int = 1_000_000,
    max_field_chars: int = 2_000_000,
) -> list[OfficialSIFTSegment]:
    segments: list[OfficialSIFTSegment] = []
    for row in _rows(
        path,
        expected_columns=26,
        max_rows=max_rows,
        max_field_chars=max_field_chars,
    ):
        segment = OfficialSIFTSegment(
            entry_id=_text(row[0]).lower(),
            entity_id=_integer(row[1], field="entity_id"),
            segment_id=_integer(row[2], field="segment_id"),
            auth_asym_id=_text(row[3]),
            struct_asym_id=_text(row[4]),
            accession=_optional_text(row[5]),
            name=_optional_text(row[6]),
            sequence_version=_integer(row[7], field="sequence_version", optional=True),
            uniprot_start=_integer(row[8], field="uniprot_start", optional=True),
            pdb_start=_integer(row[9], field="pdb_start"),
            uniprot_end=_integer(row[10], field="uniprot_end", optional=True),
            pdb_end=_integer(row[11], field="pdb_end"),
            author_start=_integer(row[12], field="author_start"),
            author_start_insertion_code=_optional_text(row[13]),
            author_end=_integer(row[14], field="author_end"),
            author_end_insertion_code=_optional_text(row[15]),
            conflict_count=_integer(row[16], field="conflicts", optional=True),
            modification_count=_integer(row[17], field="modifications", optional=True),
            uniprot_alignment=_optional_text(row[18]),
            pdb_alignment=_text(row[19]),
            identity=_float(row[20], field="identity", optional=True),
            score=_float(row[21], field="score", optional=True),
            best_mapping=_boolean(row[22], field="best_mapping"),
            canonical_accession=_boolean(row[23], field="canonical_accession"),
            reference_accession=_optional_text(row[24]),
            chimera=_boolean(row[25], field="chimera"),
        )
        if expected_entry_id is not None and segment.entry_id != expected_entry_id.lower():
            raise ValueError("SIFTS segment entry does not match expected_entry_id")
        segments.append(segment)
    return segments


def parse_official_residue_csv(
    path: str | Path,
    *,
    expected_entry_id: str | None = None,
    max_rows: int = 5_000_000,
    max_field_chars: int = 2_000_000,
) -> list[OfficialSIFTSResidue]:
    residues: list[OfficialSIFTSResidue] = []
    for row in _rows(
        path,
        expected_columns=24,
        max_rows=max_rows,
        max_field_chars=max_field_chars,
    ):
        residue = OfficialSIFTSResidue(
            entry_id=_text(row[0]).lower(),
            entity_id=_integer(row[1], field="entity_id"),
            residue_ordinal=_integer(row[2], field="residue_ordinal"),
            auth_asym_id=_text(row[3]),
            struct_asym_id=_text(row[4]),
            uniprot_segment_id=_integer(row[5], field="uniprot_segment_id"),
            author_sequence_id=_integer(
                row[6], field="author_sequence_id", optional=True
            ),
            author_insertion_code=_optional_text(row[7]),
            pdb_sequence_id=_integer(row[8], field="pdb_sequence_id"),
            uniprot_sequence_id=_integer(
                row[9], field="uniprot_sequence_id", optional=True
            ),
            observed=_text(row[10]).upper(),
            database_entry_id=_integer(
                row[11], field="database_entry_id", optional=True
            ),
            accession=_optional_text(row[12]),
            name=_optional_text(row[13]),
            residue_type=_optional_text(row[14]),
            uniprot_one_letter_code=_optional_text(row[15]),
            pdb_one_letter_code=_text(row[16]),
            chemical_component_id=_text(row[17]),
            model_homologue_id=_integer(
                row[18], field="model_homologue_id", optional=True
            ),
            taxonomy_id=_integer(row[19], field="taxonomy_id", optional=True),
            canonical_accession=_boolean(row[20], field="canonical_accession"),
            reference_accession=_optional_text(row[21]),
            best_mapping=_boolean(row[22], field="best_mapping"),
            residue_id=_text(row[23]),
        )
        if expected_entry_id is not None and residue.entry_id != expected_entry_id.lower():
            raise ValueError("SIFTS residue entry does not match expected_entry_id")
        residues.append(residue)
    return residues


def to_mapping_segments(segments: list[OfficialSIFTSegment]) -> list[MappingSegment]:
    mappings: dict[tuple[object, ...], MappingSegment] = {}
    for segment in segments:
        if (
            not segment.best_mapping
            or segment.accession is None
            or segment.uniprot_start is None
            or segment.uniprot_end is None
        ):
            continue
        chain_id = segment.auth_asym_id or segment.struct_asym_id
        mapping = MappingSegment(
            pdb_id=segment.entry_id.upper(),
            uniprot_accession=segment.accession,
            chain_id=chain_id,
            pdb_start=segment.pdb_start,
            pdb_end=segment.pdb_end,
            uniprot_start=segment.uniprot_start,
            uniprot_end=segment.uniprot_end,
        )
        key = (
            mapping.pdb_id,
            mapping.uniprot_accession,
            mapping.chain_id,
            mapping.pdb_start,
            mapping.pdb_end,
            mapping.uniprot_start,
            mapping.uniprot_end,
        )
        mappings[key] = mapping
    return [mappings[key] for key in sorted(mappings)]


def build_compatibility_report(
    *,
    segment_path: str | Path,
    residue_path: str | Path,
    segments: list[OfficialSIFTSegment],
    residues: list[OfficialSIFTSResidue],
    official_reader_segment_count: int,
    official_reader_mapped_residue_count: int,
) -> OfficialSIFTSCompatibilityReport:
    segment_digest = sha256_file(segment_path)
    residue_digest = sha256_file(residue_path)
    if segment_digest != PDBE_SIFTS_1CBS_SEGMENT_SHA256:
        raise ValueError("segment fixture hash differs from pinned official fixture")
    if residue_digest != PDBE_SIFTS_1CBS_RESIDUE_SHA256:
        raise ValueError("residue fixture hash differs from pinned official fixture")
    if {segment.entry_id for segment in segments} != {"1cbs"}:
        raise ValueError("compatibility report requires the pinned 1cbs segments")
    if {residue.entry_id for residue in residues} != {"1cbs"}:
        raise ValueError("compatibility report requires the pinned 1cbs residues")
    mappings = to_mapping_segments(segments)
    mapped_best_residue_count = sum(
        residue.best_mapping
        and residue.accession is not None
        and residue.uniprot_sequence_id is not None
        for residue in residues
    )
    body = {
        "schema_version": "mdmeta-pdbe-sifts-compatibility-v1",
        "upstream_repository": PDBE_SIFTS_REPOSITORY,
        "upstream_version": PDBE_SIFTS_VERSION,
        "upstream_commit": PDBE_SIFTS_COMMIT,
        "fixture_entry_id": "1cbs",
        "segment_fixture_sha256": segment_digest,
        "residue_fixture_sha256": residue_digest,
        "segment_row_count": len(segments),
        "residue_row_count": len(residues),
        "official_reader_segment_count": official_reader_segment_count,
        "official_reader_mapped_residue_count": official_reader_mapped_residue_count,
        "mapping_segment_count": len(mappings),
        "mapped_best_residue_count": mapped_best_residue_count,
        "accession_counts": dict(
            sorted(Counter(segment.accession or "unmapped" for segment in segments).items())
        ),
        "observed_state_counts": dict(
            sorted(Counter(residue.observed for residue in residues).items())
        ),
        "insertion_code_count": sum(
            residue.author_insertion_code is not None for residue in residues
        ),
        "isoform_segment_count": sum(
            segment.accession is not None and "-" in segment.accession
            for segment in segments
        ),
        "chimera_segment_count": sum(segment.chimera for segment in segments),
        "raw_sequences_retained": False,
    }
    return OfficialSIFTSCompatibilityReport(
        **body,
        content_commitment_sha256=_canonical_sha256(body),
    )
