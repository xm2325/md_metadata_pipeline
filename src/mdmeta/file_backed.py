from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import httpx
from pydantic import BaseModel, ConfigDict, Field


AA3_TO_1 = {
    "ALA": "A",
    "ARG": "R",
    "ASN": "N",
    "ASP": "D",
    "CYS": "C",
    "GLN": "Q",
    "GLU": "E",
    "GLY": "G",
    "HIS": "H",
    "ILE": "I",
    "LEU": "L",
    "LYS": "K",
    "MET": "M",
    "PHE": "F",
    "PRO": "P",
    "SER": "S",
    "THR": "T",
    "TRP": "W",
    "TYR": "Y",
    "VAL": "V",
    "HSD": "H",
    "HSE": "H",
    "HSP": "H",
    "HID": "H",
    "HIE": "H",
    "HIP": "H",
    "CYX": "C",
    "CYM": "C",
    "MSE": "M",
}


class FileHash(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str
    filename: str
    source_uri: str
    local_path: str
    byte_size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_type: str | None = None
    retrieval_command: str


class WorkflowEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_uri: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    program: str | None = None
    version: str | None = None
    force_fields: list[str] = Field(default_factory=list)
    timestep_fs: float | None = None
    temperature_k: float | None = None
    ensemble: str | None = None
    standardized_input_status: str
    original_simulation_command_status: str
    original_simulation_command: str | None = None
    retrieval_command: str


class MolecularCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata_atoms: int | None = None
    psf_atoms: int
    pdb_atoms: int
    trajectory_atoms: int
    psf_residues: int
    pdb_residues: int
    protein_residues: int
    chains: list[str]
    trajectory_frames: int


class ConsistencyAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    atom_count_consistent: bool
    residue_count_consistent: bool
    atom_identity_match_count: int
    atom_identity_mismatch_count: int
    atom_identity_match_fraction: float = Field(ge=0, le=1)
    segment_identity_match_fraction: float = Field(ge=0, le=1)
    coordinates_finite: bool
    expected_frame_count: int
    observed_frame_count: int
    passed: bool
    failures: list[str] = Field(default_factory=list)


class ResidueRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chain_id: str
    sequence_index: int = Field(ge=1)
    residue_name: str
    one_letter: str
    residue_number: int | None = None
    author_residue_number: int | None = None
    insertion_code: str | None = None
    md_resid: int | None = None
    md_icode: str | None = None


class ChainAlignmentAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    md_chain_id: str
    pdb_chain_id: str
    assignment_method: str
    assignment_ambiguous: bool
    score: int
    matches: int
    mismatches: int
    md_insertions: int
    pdb_deletions: int
    pdb_residue_coverage: float = Field(ge=0, le=1)
    identity: float = Field(ge=0, le=1)


class ResidueMappingRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    md_chain_id: str
    md_resid: int
    md_insertion_code: str | None = None
    md_resname: str
    md_one_letter: str
    pdb_id: str
    pdb_chain_id: str
    pdb_residue_number: int
    pdb_author_residue_number: int | None = None
    pdb_author_insertion_code: str | None = None
    pdb_resname: str
    pdb_one_letter: str
    sequence_match: bool
    uniprot_accession: str | None = None
    uniprot_residue_number: int | None = None
    mapping_status: str


class ResidueMappingAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pdb_id: str
    expected_uniprot_accessions: list[str]
    chain_alignments: list[ChainAlignmentAudit]
    mapped_md_to_pdb: int
    mapped_md_to_pdb_to_uniprot: int
    sequence_mismatch_count: int
    ambiguous_chain_count: int
    md_protein_residue_count: int
    pdb_protein_residue_count: int
    pdb_mapping_coverage: float = Field(ge=0, le=1)
    uniprot_mapping_coverage: float = Field(ge=0, le=1)
    status: str


class FileBackedMDReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "file-backed-md-record-v1"
    case_id: str
    project_accession: str
    project_uri: str
    published: bool
    project_metadata_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    files_listing_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    public_file_names: list[str]
    assets: list[FileHash]
    workflow: WorkflowEvidence
    counts: MolecularCounts
    consistency: ConsistencyAudit
    residue_mapping: ResidueMappingAudit
    residue_mapping_rows_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    audit_command: str
    scientific_boundaries: list[str]


@dataclass(frozen=True)
class AlignmentResult:
    score: int
    pairs: list[tuple[int | None, int | None]]
    matches: int
    mismatches: int
    md_insertions: int
    pdb_deletions: int


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_public_file(
    client: httpx.Client,
    *,
    url: str,
    destination: Path,
    role: str,
    command: str,
    max_bytes: int = 2_000_000_000,
) -> FileHash:
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    content_type: str | None = None
    temporary = destination.with_suffix(destination.suffix + ".partial")
    try:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type")
            with temporary.open("wb") as handle:
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError(f"download exceeds max_bytes for {url}")
                    digest.update(chunk)
                    handle.write(chunk)
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return FileHash(
        role=role,
        filename=destination.name,
        source_uri=url,
        local_path=str(destination),
        byte_size=size,
        sha256=digest.hexdigest(),
        content_type=content_type,
        retrieval_command=command,
    )


def fitting_alignment(md_sequence: str, pdb_sequence: str) -> AlignmentResult:
    """Align the complete PDB chain to the best-fitting region of an MD chain.

    Prefix and suffix residues in the MD chain are free. Every PDB residue must
    participate in the alignment, making the result suitable for a prepared
    full-length MD system derived from a shorter experimental structure.
    """

    n = len(md_sequence)
    m = len(pdb_sequence)
    gap = -2
    match_score = 2
    mismatch_score = -1
    scores = [[0] * (m + 1) for _ in range(n + 1)]
    trace = [[""] * (m + 1) for _ in range(n + 1)]
    for j in range(1, m + 1):
        scores[0][j] = scores[0][j - 1] + gap
        trace[0][j] = "left"
    for i in range(1, n + 1):
        scores[i][0] = 0
        trace[i][0] = "up"

    for i in range(1, n + 1):
        md_letter = md_sequence[i - 1]
        for j in range(1, m + 1):
            pdb_letter = pdb_sequence[j - 1]
            diagonal = scores[i - 1][j - 1] + (
                match_score if md_letter == pdb_letter else mismatch_score
            )
            upward = scores[i - 1][j] + gap
            leftward = scores[i][j - 1] + gap
            best = max(diagonal, upward, leftward)
            scores[i][j] = best
            trace[i][j] = "diag" if diagonal == best else "up" if upward == best else "left"

    end_i = max(range(n + 1), key=lambda index: scores[index][m])
    score = scores[end_i][m]
    i = end_i
    j = m
    pairs: list[tuple[int | None, int | None]] = []
    while j > 0:
        direction = trace[i][j]
        if direction == "diag":
            pairs.append((i, j))
            i -= 1
            j -= 1
        elif direction == "up":
            pairs.append((i, None))
            i -= 1
        elif direction == "left":
            pairs.append((None, j))
            j -= 1
        else:
            raise ValueError(f"invalid alignment trace at {i},{j}: {direction!r}")
    pairs.reverse()

    matches = 0
    mismatches = 0
    md_insertions = 0
    pdb_deletions = 0
    for md_index, pdb_index in pairs:
        if md_index is None:
            pdb_deletions += 1
        elif pdb_index is None:
            md_insertions += 1
        elif md_sequence[md_index - 1] == pdb_sequence[pdb_index - 1]:
            matches += 1
        else:
            mismatches += 1
    return AlignmentResult(
        score=score,
        pairs=pairs,
        matches=matches,
        mismatches=mismatches,
        md_insertions=md_insertions,
        pdb_deletions=pdb_deletions,
    )


def _residue_chain_id(residue: Any) -> str:
    chain_ids = getattr(residue.atoms, "chainIDs", [])
    for chain_id in chain_ids:
        if str(chain_id).strip():
            return str(chain_id).strip()
    segid = str(getattr(residue, "segid", "")).strip()
    return segid or "_"


def md_protein_chains(universe: Any) -> dict[str, list[ResidueRecord]]:
    chains: dict[str, list[ResidueRecord]] = {}
    for residue in universe.residues:
        resname = str(residue.resname).upper()
        letter = AA3_TO_1.get(resname)
        if letter is None:
            continue
        chain_id = _residue_chain_id(residue)
        records = chains.setdefault(chain_id, [])
        icode = str(getattr(residue, "icode", "") or "").strip() or None
        records.append(
            ResidueRecord(
                chain_id=chain_id,
                sequence_index=len(records) + 1,
                residue_name=resname,
                one_letter=letter,
                md_resid=int(residue.resid),
                md_icode=icode,
            )
        )
    return chains


def pdbe_protein_chains(
    payload: dict[str, Any], pdb_id: str
) -> dict[str, list[ResidueRecord]]:
    root = payload[pdb_id.lower()]
    chains: dict[str, list[ResidueRecord]] = {}
    for molecule in root.get("molecules", []):
        for chain in molecule.get("chains", []):
            chain_id = str(chain.get("chain_id") or chain.get("struct_asym_id") or "_")
            records: list[ResidueRecord] = []
            for residue in chain.get("residues", []):
                resname = str(residue.get("residue_name") or "").upper()
                letter = AA3_TO_1.get(resname)
                if letter is None:
                    continue
                records.append(
                    ResidueRecord(
                        chain_id=chain_id,
                        sequence_index=len(records) + 1,
                        residue_name=resname,
                        one_letter=letter,
                        residue_number=int(residue["residue_number"]),
                        author_residue_number=(
                            int(residue["author_residue_number"])
                            if residue.get("author_residue_number") is not None
                            else None
                        ),
                        insertion_code=(
                            str(residue.get("author_insertion_code") or "").strip() or None
                        ),
                    )
                )
            if records:
                chains[chain_id] = records
    return chains


def _best_chain_assignments(
    md_chains: dict[str, list[ResidueRecord]],
    pdb_chains: dict[str, list[ResidueRecord]],
) -> list[tuple[str, str, AlignmentResult, bool, str]]:
    assignments: list[tuple[str, str, AlignmentResult, bool, str]] = []
    unused_pdb = set(pdb_chains)
    for md_chain in sorted(md_chains):
        md_sequence = "".join(item.one_letter for item in md_chains[md_chain])
        candidates: list[tuple[str, AlignmentResult]] = []
        for pdb_chain in sorted(pdb_chains):
            pdb_sequence = "".join(item.one_letter for item in pdb_chains[pdb_chain])
            candidates.append((pdb_chain, fitting_alignment(md_sequence, pdb_sequence)))
        if not candidates:
            continue
        best_score = max(result.score for _, result in candidates)
        tied = [(chain, result) for chain, result in candidates if result.score == best_score]
        same_name = [item for item in tied if item[0] == md_chain and item[0] in unused_pdb]
        unused = [item for item in tied if item[0] in unused_pdb]
        if same_name:
            chosen_chain, chosen_result = same_name[0]
            method = "sequence_score_then_same_chain_id_tiebreak"
        elif unused:
            chosen_chain, chosen_result = unused[0]
            method = "sequence_score_then_unused_chain_tiebreak"
        else:
            chosen_chain, chosen_result = tied[0]
            method = "sequence_score_lexical_tiebreak"
        unused_pdb.discard(chosen_chain)
        assignments.append((md_chain, chosen_chain, chosen_result, len(tied) > 1, method))
    return assignments


def _sifts_segments(mapping_payload: dict[str, Any], pdb_id: str) -> list[dict[str, Any]]:
    root = mapping_payload.get(pdb_id.lower(), {}).get("UniProt", {})
    segments: list[dict[str, Any]] = []
    for accession, entry in root.items():
        for item in entry.get("mappings", []):
            start = item.get("start") or {}
            end = item.get("end") or {}
            pdb_start = start.get("residue_number")
            pdb_end = end.get("residue_number")
            unp_start = item.get("unp_start")
            unp_end = item.get("unp_end")
            if None in (pdb_start, pdb_end, unp_start, unp_end):
                continue
            segments.append(
                {
                    "accession": accession,
                    "chain_id": str(
                        item.get("chain_id") or item.get("struct_asym_id") or ""
                    ),
                    "pdb_start": int(pdb_start),
                    "pdb_end": int(pdb_end),
                    "unp_start": int(unp_start),
                    "unp_end": int(unp_end),
                }
            )
    return segments


def compose_residue_mapping(
    *,
    md_chains: dict[str, list[ResidueRecord]],
    pdb_chains: dict[str, list[ResidueRecord]],
    mapping_payload: dict[str, Any],
    pdb_id: str,
    expected_uniprot_accessions: Iterable[str],
) -> tuple[ResidueMappingAudit, list[ResidueMappingRow]]:
    expected = sorted(set(expected_uniprot_accessions))
    segments = _sifts_segments(mapping_payload, pdb_id)
    rows: list[ResidueMappingRow] = []
    audits: list[ChainAlignmentAudit] = []
    for md_chain, pdb_chain, result, ambiguous, method in _best_chain_assignments(
        md_chains, pdb_chains
    ):
        md_records = md_chains[md_chain]
        pdb_records = pdb_chains[pdb_chain]
        aligned_pdb = 0
        for md_index, pdb_index in result.pairs:
            if md_index is None or pdb_index is None:
                continue
            md_residue = md_records[md_index - 1]
            pdb_residue = pdb_records[pdb_index - 1]
            aligned_pdb += 1
            sequence_match = md_residue.one_letter == pdb_residue.one_letter
            accession: str | None = None
            uniprot_number: int | None = None
            status = "md_to_pdb_sequence_mismatch" if not sequence_match else "md_to_pdb_only"
            if sequence_match and pdb_residue.residue_number is not None:
                matching = [
                    item
                    for item in segments
                    if item["chain_id"] == pdb_chain
                    and item["pdb_start"] <= pdb_residue.residue_number <= item["pdb_end"]
                    and (not expected or item["accession"] in expected)
                ]
                valid = [
                    item
                    for item in matching
                    if item["pdb_end"] - item["pdb_start"]
                    == item["unp_end"] - item["unp_start"]
                ]
                if len(valid) == 1:
                    segment = valid[0]
                    accession = segment["accession"]
                    uniprot_number = segment["unp_start"] + (
                        pdb_residue.residue_number - segment["pdb_start"]
                    )
                    status = "verified_md_to_pdb_to_uniprot"
                elif len(valid) > 1:
                    status = "ambiguous_sifts_segment"
                elif matching:
                    status = "sifts_segment_length_conflict"
                else:
                    status = "no_sifts_mapping_for_pdb_residue"
            rows.append(
                ResidueMappingRow(
                    md_chain_id=md_chain,
                    md_resid=int(md_residue.md_resid),
                    md_insertion_code=md_residue.md_icode,
                    md_resname=md_residue.residue_name,
                    md_one_letter=md_residue.one_letter,
                    pdb_id=pdb_id.upper(),
                    pdb_chain_id=pdb_chain,
                    pdb_residue_number=int(pdb_residue.residue_number),
                    pdb_author_residue_number=pdb_residue.author_residue_number,
                    pdb_author_insertion_code=pdb_residue.insertion_code,
                    pdb_resname=pdb_residue.residue_name,
                    pdb_one_letter=pdb_residue.one_letter,
                    sequence_match=sequence_match,
                    uniprot_accession=accession,
                    uniprot_residue_number=uniprot_number,
                    mapping_status=status,
                )
            )
        denominator = max(1, len(pdb_records))
        identity_denominator = max(1, result.matches + result.mismatches)
        audits.append(
            ChainAlignmentAudit(
                md_chain_id=md_chain,
                pdb_chain_id=pdb_chain,
                assignment_method=method,
                assignment_ambiguous=ambiguous,
                score=result.score,
                matches=result.matches,
                mismatches=result.mismatches,
                md_insertions=result.md_insertions,
                pdb_deletions=result.pdb_deletions,
                pdb_residue_coverage=aligned_pdb / denominator,
                identity=result.matches / identity_denominator,
            )
        )

    mapped_md_to_pdb = len(rows)
    mapped_uniprot = sum(
        row.mapping_status == "verified_md_to_pdb_to_uniprot" for row in rows
    )
    mismatch_count = sum(not row.sequence_match for row in rows)
    pdb_total = sum(len(items) for items in pdb_chains.values())
    md_total = sum(len(items) for items in md_chains.values())
    audit = ResidueMappingAudit(
        pdb_id=pdb_id.upper(),
        expected_uniprot_accessions=expected,
        chain_alignments=audits,
        mapped_md_to_pdb=mapped_md_to_pdb,
        mapped_md_to_pdb_to_uniprot=mapped_uniprot,
        sequence_mismatch_count=mismatch_count,
        ambiguous_chain_count=sum(item.assignment_ambiguous for item in audits),
        md_protein_residue_count=md_total,
        pdb_protein_residue_count=pdb_total,
        pdb_mapping_coverage=mapped_md_to_pdb / max(1, pdb_total),
        uniprot_mapping_coverage=mapped_uniprot / max(1, pdb_total),
        status=(
            "verified"
            if mapped_uniprot > 0 and mismatch_count == 0
            else "review"
            if mapped_uniprot > 0
            else "failed"
        ),
    )
    return audit, rows


def audit_molecular_files(
    *,
    psf_path: Path,
    pdb_path: Path,
    trajectory_path: Path,
    metadata_atom_count: int | None,
    expected_frames: int,
) -> tuple[MolecularCounts, ConsistencyAudit, Any]:
    try:
        import MDAnalysis as mda
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(
            "file-backed auditing requires the 'files' optional dependency"
        ) from exc

    psf = mda.Universe(str(psf_path))
    pdb = mda.Universe(str(pdb_path))
    dynamic = mda.Universe(str(pdb_path), str(trajectory_path))

    psf_atoms = int(psf.atoms.n_atoms)
    pdb_atoms = int(pdb.atoms.n_atoms)
    trajectory_atoms = int(dynamic.atoms.n_atoms)
    frame_count = len(dynamic.trajectory)
    psf_residues = int(psf.residues.n_residues)
    pdb_residues = int(pdb.residues.n_residues)

    atom_match = 0
    atom_mismatch = 0
    segment_match = 0
    for psf_atom, pdb_atom in zip(psf.atoms, pdb.atoms):
        basic_psf = (
            str(psf_atom.name).strip(),
            str(psf_atom.resname).strip(),
            int(psf_atom.resid),
        )
        basic_pdb = (
            str(pdb_atom.name).strip(),
            str(pdb_atom.resname).strip(),
            int(pdb_atom.resid),
        )
        if basic_psf == basic_pdb:
            atom_match += 1
        else:
            atom_mismatch += 1
        if str(psf_atom.segid).strip() == str(pdb_atom.segid).strip():
            segment_match += 1

    coordinates_finite = True
    for timestep in dynamic.trajectory:
        if not bool(np.isfinite(timestep.positions).all()):
            coordinates_finite = False
            break

    failures: list[str] = []
    atom_counts = [psf_atoms, pdb_atoms, trajectory_atoms]
    if metadata_atom_count is not None:
        atom_counts.append(int(metadata_atom_count))
    atom_consistent = len(set(atom_counts)) == 1
    if not atom_consistent:
        failures.append(f"atom_count_mismatch:{atom_counts}")
    residue_consistent = psf_residues == pdb_residues
    if not residue_consistent:
        failures.append(f"residue_count_mismatch:psf={psf_residues},pdb={pdb_residues}")
    if atom_mismatch:
        failures.append(f"atom_identity_mismatches:{atom_mismatch}")
    if frame_count != expected_frames:
        failures.append(
            f"trajectory_frame_count:expected={expected_frames},observed={frame_count}"
        )
    if not coordinates_finite:
        failures.append("trajectory_contains_non_finite_coordinates")

    md_chains = md_protein_chains(pdb)
    counts = MolecularCounts(
        metadata_atoms=metadata_atom_count,
        psf_atoms=psf_atoms,
        pdb_atoms=pdb_atoms,
        trajectory_atoms=trajectory_atoms,
        psf_residues=psf_residues,
        pdb_residues=pdb_residues,
        protein_residues=sum(len(items) for items in md_chains.values()),
        chains=sorted(md_chains),
        trajectory_frames=frame_count,
    )
    denominator = max(1, min(psf_atoms, pdb_atoms))
    consistency = ConsistencyAudit(
        atom_count_consistent=atom_consistent,
        residue_count_consistent=residue_consistent,
        atom_identity_match_count=atom_match,
        atom_identity_mismatch_count=atom_mismatch,
        atom_identity_match_fraction=atom_match / denominator,
        segment_identity_match_fraction=segment_match / denominator,
        coordinates_finite=coordinates_finite,
        expected_frame_count=expected_frames,
        observed_frame_count=frame_count,
        passed=not failures,
        failures=failures,
    )
    return counts, consistency, pdb


def write_mapping_rows(rows: list[ResidueMappingRow], path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(row.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        for row in rows
    ]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return sha256_file(path)
