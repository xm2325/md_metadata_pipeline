from __future__ import annotations

from pathlib import Path
from typing import Any

from .file_backed import ConsistencyAudit, MolecularCounts, md_protein_chains


def normalize_atom_name(name: str) -> str:
    """Normalise common CHARMM/PSF versus PDB hydrogen and terminal atom names."""

    normalized = "".join(character for character in name.upper() if character.isalnum())
    aliases = {"HN": "H", "OT1": "O", "OT2": "OXT"}
    normalized = aliases.get(normalized, normalized)
    leading_digits = ""
    while normalized and normalized[0].isdigit():
        leading_digits += normalized[0]
        normalized = normalized[1:]
    return normalized + leading_digits


def audit_molecular_files(
    *,
    psf_path: Path,
    pdb_path: Path,
    trajectory_path: Path,
    metadata_atom_count: int | None,
    expected_frames: int,
) -> tuple[MolecularCounts, ConsistencyAudit, Any, dict[str, Any]]:
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

    exact_match = 0
    normalized_match = 0
    residue_identity_match = 0
    segment_match = 0
    mismatch_examples: list[dict[str, Any]] = []
    for atom_index, (psf_atom, pdb_atom) in enumerate(
        zip(psf.atoms, pdb.atoms), start=1
    ):
        psf_name = str(psf_atom.name).strip()
        pdb_name = str(pdb_atom.name).strip()
        psf_resname = str(psf_atom.resname).strip()
        pdb_resname = str(pdb_atom.resname).strip()
        psf_resid = int(psf_atom.resid)
        pdb_resid = int(pdb_atom.resid)
        psf_segid = str(psf_atom.segid).strip()
        pdb_segid = str(pdb_atom.segid).strip()

        exact_psf = (psf_name, psf_resname, psf_resid)
        exact_pdb = (pdb_name, pdb_resname, pdb_resid)
        if exact_psf == exact_pdb:
            exact_match += 1

        normalized_psf = (normalize_atom_name(psf_name), psf_resname, psf_resid)
        normalized_pdb = (normalize_atom_name(pdb_name), pdb_resname, pdb_resid)
        if normalized_psf == normalized_pdb:
            normalized_match += 1
        elif len(mismatch_examples) < 30:
            mismatch_examples.append(
                {
                    "atom_index": atom_index,
                    "psf": {
                        "name": psf_name,
                        "normalized_name": normalized_psf[0],
                        "resname": psf_resname,
                        "resid": psf_resid,
                        "segid": psf_segid,
                    },
                    "pdb": {
                        "name": pdb_name,
                        "normalized_name": normalized_pdb[0],
                        "resname": pdb_resname,
                        "resid": pdb_resid,
                        "segid": pdb_segid,
                    },
                }
            )
        if (psf_resname, psf_resid, psf_segid) == (
            pdb_resname,
            pdb_resid,
            pdb_segid,
        ):
            residue_identity_match += 1
        if psf_segid == pdb_segid:
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
        failures.append(
            f"residue_count_mismatch:psf={psf_residues},pdb={pdb_residues}"
        )

    denominator = max(1, min(psf_atoms, pdb_atoms))
    exact_fraction = exact_match / denominator
    normalized_fraction = normalized_match / denominator
    residue_fraction = residue_identity_match / denominator
    segment_fraction = segment_match / denominator
    if normalized_fraction < 0.99:
        failures.append(
            "normalized_atom_identity_fraction_below_0.99:"
            f"{normalized_fraction:.6f}"
        )
    if residue_fraction < 0.999:
        failures.append(
            f"residue_identity_fraction_below_0.999:{residue_fraction:.6f}"
        )
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
    consistency = ConsistencyAudit(
        atom_count_consistent=atom_consistent,
        residue_count_consistent=residue_consistent,
        atom_identity_match_count=normalized_match,
        atom_identity_mismatch_count=denominator - normalized_match,
        atom_identity_match_fraction=normalized_fraction,
        segment_identity_match_fraction=segment_fraction,
        coordinates_finite=coordinates_finite,
        expected_frame_count=expected_frames,
        observed_frame_count=frame_count,
        passed=not failures,
        failures=failures,
    )
    diagnostics = {
        "comparison_basis": {
            "exact": "atom name, residue name, residue id",
            "normalized": (
                "common leading-digit hydrogen conventions and CHARMM terminal aliases "
                "normalised before comparing atom name, residue name and residue id"
            ),
        },
        "exact_atom_identity_match_count": exact_match,
        "exact_atom_identity_mismatch_count": denominator - exact_match,
        "exact_atom_identity_match_fraction": exact_fraction,
        "normalized_atom_identity_match_count": normalized_match,
        "normalized_atom_identity_mismatch_count": denominator - normalized_match,
        "normalized_atom_identity_match_fraction": normalized_fraction,
        "residue_identity_match_fraction": residue_fraction,
        "segment_identity_match_fraction": segment_fraction,
        "mismatch_examples": mismatch_examples,
    }
    return counts, consistency, pdb, diagnostics
