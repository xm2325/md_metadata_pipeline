from __future__ import annotations

from pathlib import Path
from typing import Any

from .file_backed import AA3_TO_1, ConsistencyAudit, MolecularCounts, md_protein_chains


def normalize_atom_name(name: str) -> str:
    """Normalise documented CHARMM/PSF versus PDB atom-name conventions."""

    normalized = "".join(character for character in name.upper() if character.isalnum())
    aliases = {"HN": "H", "OT1": "O", "OT2": "OXT"}
    normalized = aliases.get(normalized, normalized)
    leading_digits = ""
    while normalized and normalized[0].isdigit():
        leading_digits += normalized[0]
        normalized = normalized[1:]
    return normalized + leading_digits


def _finite_trajectory(universe: Any, np: Any) -> bool:
    for timestep in universe.trajectory:
        if not bool(np.isfinite(timestep.positions).all()):
            return False
    return True


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
    pdb_dynamic = mda.Universe(str(pdb_path), str(trajectory_path))
    psf_dynamic = mda.Universe(str(psf_path), str(trajectory_path))

    psf_atoms = int(psf.atoms.n_atoms)
    pdb_atoms = int(pdb.atoms.n_atoms)
    pdb_trajectory_atoms = int(pdb_dynamic.atoms.n_atoms)
    psf_trajectory_atoms = int(psf_dynamic.atoms.n_atoms)
    pdb_frame_count = len(pdb_dynamic.trajectory)
    psf_frame_count = len(psf_dynamic.trajectory)
    psf_residues = int(psf.residues.n_residues)
    pdb_residues = int(pdb.residues.n_residues)

    exact_match = 0
    normalized_match = 0
    segment_match = 0
    residue_partition_match = 0
    protein_scope_atoms = 0
    protein_identity_match = 0
    protein_mismatch_examples: list[dict[str, Any]] = []
    nonprotein_mismatch_examples: list[dict[str, Any]] = []

    for atom_index, (psf_atom, pdb_atom) in enumerate(
        zip(psf.atoms, pdb.atoms), start=1
    ):
        psf_name = str(psf_atom.name).strip()
        pdb_name = str(pdb_atom.name).strip()
        psf_resname = str(psf_atom.resname).strip().upper()
        pdb_resname = str(pdb_atom.resname).strip().upper()
        psf_resid = int(psf_atom.resid)
        pdb_resid = int(pdb_atom.resid)
        psf_segid = str(psf_atom.segid).strip()
        pdb_segid = str(pdb_atom.segid).strip()
        psf_resindex = int(psf_atom.resindex)
        pdb_resindex = int(pdb_atom.resindex)

        exact_psf = (psf_name, psf_resname, psf_resid, psf_segid)
        exact_pdb = (pdb_name, pdb_resname, pdb_resid, pdb_segid)
        if exact_psf == exact_pdb:
            exact_match += 1

        psf_letter = AA3_TO_1.get(psf_resname)
        pdb_letter = AA3_TO_1.get(pdb_resname)
        normalized_psf = (
            normalize_atom_name(psf_name),
            psf_letter or psf_resname,
            psf_resid,
            psf_segid,
        )
        normalized_pdb = (
            normalize_atom_name(pdb_name),
            pdb_letter or pdb_resname,
            pdb_resid,
            pdb_segid,
        )
        normalized_equal = normalized_psf == normalized_pdb
        if normalized_equal:
            normalized_match += 1

        if psf_segid == pdb_segid:
            segment_match += 1
        if psf_resindex == pdb_resindex:
            residue_partition_match += 1

        in_protein_scope = psf_letter is not None or pdb_letter is not None
        if in_protein_scope:
            protein_scope_atoms += 1
            if normalized_equal and psf_letter == pdb_letter:
                protein_identity_match += 1
            elif len(protein_mismatch_examples) < 30:
                protein_mismatch_examples.append(
                    {
                        "atom_index": atom_index,
                        "psf": {
                            "name": psf_name,
                            "normalized_name": normalized_psf[0],
                            "resname": psf_resname,
                            "one_letter": psf_letter,
                            "resid": psf_resid,
                            "resindex": psf_resindex,
                            "segid": psf_segid,
                        },
                        "pdb": {
                            "name": pdb_name,
                            "normalized_name": normalized_pdb[0],
                            "resname": pdb_resname,
                            "one_letter": pdb_letter,
                            "resid": pdb_resid,
                            "resindex": pdb_resindex,
                            "segid": pdb_segid,
                        },
                    }
                )
        elif not normalized_equal and len(nonprotein_mismatch_examples) < 30:
            nonprotein_mismatch_examples.append(
                {
                    "atom_index": atom_index,
                    "psf": {
                        "name": psf_name,
                        "normalized_name": normalized_psf[0],
                        "resname": psf_resname,
                        "resid": psf_resid,
                        "resindex": psf_resindex,
                        "segid": psf_segid,
                    },
                    "pdb": {
                        "name": pdb_name,
                        "normalized_name": normalized_pdb[0],
                        "resname": pdb_resname,
                        "resid": pdb_resid,
                        "resindex": pdb_resindex,
                        "segid": pdb_segid,
                    },
                }
            )

    psf_residue_atom_counts = [int(residue.atoms.n_atoms) for residue in psf.residues]
    pdb_residue_atom_counts = [int(residue.atoms.n_atoms) for residue in pdb.residues]
    paired_residues = min(len(psf_residue_atom_counts), len(pdb_residue_atom_counts))
    residue_atom_count_matches = sum(
        left == right
        for left, right in zip(psf_residue_atom_counts, pdb_residue_atom_counts)
    )

    pdb_coordinates_finite = _finite_trajectory(pdb_dynamic, np)
    psf_coordinates_finite = _finite_trajectory(psf_dynamic, np)
    coordinates_finite = pdb_coordinates_finite and psf_coordinates_finite

    failures: list[str] = []
    atom_counts = [psf_atoms, pdb_atoms, pdb_trajectory_atoms, psf_trajectory_atoms]
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
    segment_fraction = segment_match / denominator
    partition_fraction = residue_partition_match / denominator
    protein_identity_fraction = protein_identity_match / max(1, protein_scope_atoms)
    residue_atom_count_fraction = residue_atom_count_matches / max(1, paired_residues)

    if segment_fraction < 1.0:
        failures.append(f"segment_by_atom_fraction_below_1:{segment_fraction:.6f}")
    if partition_fraction < 1.0:
        failures.append(
            f"residue_partition_fraction_below_1:{partition_fraction:.6f}"
        )
    if residue_atom_count_fraction < 1.0:
        failures.append(
            "per_residue_atom_count_fraction_below_1:"
            f"{residue_atom_count_fraction:.6f}"
        )
    if protein_identity_fraction < 0.999:
        failures.append(
            "protein_atom_identity_fraction_below_0.999:"
            f"{protein_identity_fraction:.6f}"
        )
    if pdb_frame_count != expected_frames or psf_frame_count != expected_frames:
        failures.append(
            "trajectory_frame_count:"
            f"expected={expected_frames},pdb={pdb_frame_count},psf={psf_frame_count}"
        )
    if not coordinates_finite:
        failures.append(
            "trajectory_contains_non_finite_coordinates:"
            f"pdb={pdb_coordinates_finite},psf={psf_coordinates_finite}"
        )

    md_chains = md_protein_chains(pdb)
    counts = MolecularCounts(
        metadata_atoms=metadata_atom_count,
        psf_atoms=psf_atoms,
        pdb_atoms=pdb_atoms,
        trajectory_atoms=pdb_trajectory_atoms,
        psf_residues=psf_residues,
        pdb_residues=pdb_residues,
        protein_residues=sum(len(items) for items in md_chains.values()),
        chains=sorted(md_chains),
        trajectory_frames=pdb_frame_count,
    )
    consistency = ConsistencyAudit(
        atom_count_consistent=atom_consistent,
        residue_count_consistent=residue_consistent,
        atom_identity_match_count=protein_identity_match,
        atom_identity_mismatch_count=protein_scope_atoms - protein_identity_match,
        atom_identity_match_fraction=protein_identity_fraction,
        segment_identity_match_fraction=segment_fraction,
        coordinates_finite=coordinates_finite,
        expected_frame_count=expected_frames,
        observed_frame_count=pdb_frame_count,
        passed=not failures,
        failures=failures,
    )
    diagnostics = {
        "acceptance_basis": {
            "trajectory": (
                "the same XTC subset must load with both PSF and PDB topology, with identical "
                "atom and frame counts and finite coordinates"
            ),
            "index_partition": (
                "segment assignment, atom-to-residue partition and per-residue atom counts "
                "must agree exactly by atom index"
            ),
            "protein_identity": (
                "protein atom name, one-letter residue identity, residue id and segment must "
                "agree after documented CHARMM/PDB atom-name normalisation"
            ),
            "nonprotein_names": (
                "glycan and other non-protein chemical naming differences are reported but do "
                "not fail the gate when index partition and trajectory compatibility agree"
            ),
        },
        "topology_trajectory_readable": {
            "pdb_topology": True,
            "psf_topology": True,
        },
        "trajectory_atom_counts": {
            "pdb_topology": pdb_trajectory_atoms,
            "psf_topology": psf_trajectory_atoms,
        },
        "trajectory_frame_counts": {
            "pdb_topology": pdb_frame_count,
            "psf_topology": psf_frame_count,
        },
        "trajectory_coordinates_finite": {
            "pdb_topology": pdb_coordinates_finite,
            "psf_topology": psf_coordinates_finite,
        },
        "exact_all_atom_identity_match_count": exact_match,
        "exact_all_atom_identity_match_fraction": exact_fraction,
        "normalized_all_atom_identity_match_count": normalized_match,
        "normalized_all_atom_identity_match_fraction": normalized_fraction,
        "protein_scope_atom_count": protein_scope_atoms,
        "protein_atom_identity_match_count": protein_identity_match,
        "protein_atom_identity_match_fraction": protein_identity_fraction,
        "segment_by_atom_match_fraction": segment_fraction,
        "residue_partition_by_atom_match_fraction": partition_fraction,
        "per_residue_atom_count_match_fraction": residue_atom_count_fraction,
        "protein_mismatch_examples": protein_mismatch_examples,
        "nonprotein_naming_mismatch_examples": nonprotein_mismatch_examples,
    }
    return counts, consistency, pdb, diagnostics
