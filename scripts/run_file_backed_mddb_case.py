from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import sys
from pathlib import Path
from typing import Any

import httpx

from mdmeta import user_agent
from mdmeta.file_backed import (
    FileBackedMDReport,
    WorkflowEvidence,
    canonical_sha256,
    compose_residue_mapping,
    download_public_file,
    md_protein_chains,
    pdbe_protein_chains,
    write_mapping_rows,
)
from mdmeta.file_consistency import audit_molecular_files
from mdmeta.models import ValidationState
from mdmeta.validation import IdentifierValidator


def raw_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def curl_command(url: str, filename: str | None = None) -> str:
    output = f" --output {shlex.quote(filename)}" if filename else ""
    return f"curl --fail --location{output} {shlex.quote(url)}"


def get_json_bytes(client: httpx.Client, url: str) -> tuple[bytes, dict[str, Any]]:
    response = client.get(url)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise TypeError(f"expected JSON object from {url}")
    return response.content, payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mapping-output", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    base_url = manifest["api_base_url"].rstrip("/")
    project = manifest["project_accession"]
    project_url = f"{base_url}/projects/{project}"
    files_url = f"{project_url}/files"
    inputs_url = f"{project_url}/inputs?format=json"
    pdb_id = manifest["starting_pdb_ids"][0]
    expected_uniprot = manifest["expected_uniprot_accessions"]
    trajectory_request = manifest["trajectory_request"]
    trajectory_url = (
        f"{project_url}/files/trajectory"
        f"?frames={trajectory_request['frames']}&format={trajectory_request['format']}"
    )
    psf_url = f"{project_url}/files/topology.psf"
    pdb_url = f"{project_url}/files/structure.pdb"

    args.work_dir.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.cache_dir.mkdir(parents=True, exist_ok=True)

    client = httpx.Client(
        timeout=120,
        follow_redirects=True,
        headers={"User-Agent": user_agent("file-backed-mddb")},
    )
    try:
        project_bytes, project_payload = get_json_bytes(client, project_url)
        files_response = client.get(files_url)
        files_response.raise_for_status()
        files_bytes = files_response.content
        public_files = files_response.json()
        if not isinstance(public_files, list) or not all(
            isinstance(item, str) for item in public_files
        ):
            raise TypeError("MDDB /files response is not a list of filenames")
        required = {"topology.psf", "structure.pdb", "trajectory.xtc"}
        missing = sorted(required - set(public_files))
        if missing:
            raise ValueError(f"required public MDDB files are missing: {missing}")

        inputs_response = client.get(inputs_url)
        inputs_response.raise_for_status()
        inputs_bytes = inputs_response.content
        inputs_payload = inputs_response.json()
        if not isinstance(inputs_payload, dict):
            raise TypeError("MDDB /inputs response is not a JSON object")

        assets = [
            download_public_file(
                client,
                url=psf_url,
                destination=args.work_dir / "topology.psf",
                role="force_field_topology",
                command=curl_command(psf_url, "topology.psf"),
                max_bytes=250_000_000,
            ),
            download_public_file(
                client,
                url=pdb_url,
                destination=args.work_dir / "structure.pdb",
                role="coordinate_topology",
                command=curl_command(pdb_url, "structure.pdb"),
                max_bytes=250_000_000,
            ),
            download_public_file(
                client,
                url=trajectory_url,
                destination=args.work_dir / "trajectory_10_frames.xtc",
                role="trajectory_frame_subset",
                command=curl_command(trajectory_url, "trajectory_10_frames.xtc"),
                max_bytes=500_000_000,
            ),
        ]

        metadata = project_payload.get("metadata", {})
        if not isinstance(metadata, dict):
            raise TypeError("project metadata is not a JSON object")
        counts, consistency, pdb_universe, identity_diagnostics = audit_molecular_files(
            psf_path=args.work_dir / "topology.psf",
            pdb_path=args.work_dir / "structure.pdb",
            trajectory_path=args.work_dir / "trajectory_10_frames.xtc",
            metadata_atom_count=(
                int(metadata["atomCount"])
                if metadata.get("atomCount") is not None
                else None
            ),
            expected_frames=10,
        )
        identity_diagnostics_path = args.output.parent / "atom_identity_diagnostics.json"
        identity_diagnostics_path.write_text(
            json.dumps(identity_diagnostics, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        residue_url = (
            "https://www.ebi.ac.uk/pdbe/api/pdb/entry/residue_listing/"
            + pdb_id.lower()
        )
        mapping_url = "https://www.ebi.ac.uk/pdbe/api/mappings/uniprot/" + pdb_id.lower()
        _, residue_payload = get_json_bytes(client, residue_url)
        _, mapping_payload = get_json_bytes(client, mapping_url)
        md_chains = md_protein_chains(pdb_universe)
        pdb_chains = pdbe_protein_chains(residue_payload, pdb_id)
        mapping_audit, mapping_rows = compose_residue_mapping(
            md_chains=md_chains,
            pdb_chains=pdb_chains,
            mapping_payload=mapping_payload,
            pdb_id=pdb_id,
            expected_uniprot_accessions=expected_uniprot,
        )
        if (
            mapping_audit.status == "review"
            and mapping_audit.chain_alignments
            and min(item.identity for item in mapping_audit.chain_alignments) >= 0.95
            and mapping_audit.pdb_mapping_coverage >= 0.95
            and mapping_audit.uniprot_mapping_coverage >= 0.90
        ):
            mapping_audit.status = "verified_with_construct_variants"
        mapping_digest = write_mapping_rows(mapping_rows, args.mapping_output)

        validator = IdentifierValidator(cache_dir=args.cache_dir)
        pdb_validation = validator.validate_pdb(pdb_id)
        if pdb_validation.state is not ValidationState.VALIDATED:
            raise ValueError(f"PDB validation did not pass: {pdb_validation.state.value}")
        for accession in expected_uniprot:
            record = validator.validate_uniprot(accession)
            if record.state is not ValidationState.VALIDATED:
                raise ValueError(
                    f"UniProt validation did not pass for {accession}: "
                    f"{record.state.value}"
                )
            relation = validator.validate_mapping(pdb_id, accession)
            if relation.state is not ValidationState.VALIDATED:
                raise ValueError(
                    f"SIFTS mapping did not pass for {pdb_id}/{accession}: "
                    f"{relation.state.value}"
                )

        workflow = WorkflowEvidence(
            source_uri=inputs_url,
            sha256=raw_sha256(inputs_bytes),
            program=str(inputs_payload.get("program") or metadata.get("PROGRAM") or "") or None,
            version=str(inputs_payload.get("version") or metadata.get("VERSION") or "") or None,
            force_fields=[
                str(item) for item in (inputs_payload.get("ff") or metadata.get("FF") or [])
            ],
            timestep_fs=(
                float(inputs_payload.get("timestep") or metadata.get("TIMESTEP"))
                if (inputs_payload.get("timestep") or metadata.get("TIMESTEP"))
                is not None
                else None
            ),
            temperature_k=(
                float(inputs_payload.get("temp") or metadata.get("TEMP"))
                if (inputs_payload.get("temp") or metadata.get("TEMP")) is not None
                else None
            ),
            ensemble=str(inputs_payload.get("ensemble") or metadata.get("ENSEMBLE") or "")
            or None,
            standardized_input_status="validated_public_mddb_generated_input",
            original_simulation_command_status="not_provided_by_repository",
            original_simulation_command=None,
            retrieval_command=curl_command(inputs_url),
        )

        report = FileBackedMDReport(
            case_id=manifest["case_id"],
            project_accession=project,
            project_uri=project_url,
            published=bool(project_payload.get("published")),
            project_metadata_sha256=raw_sha256(project_bytes),
            files_listing_sha256=raw_sha256(files_bytes),
            public_file_names=sorted(public_files),
            assets=assets,
            workflow=workflow,
            counts=counts,
            consistency=consistency,
            residue_mapping=mapping_audit,
            residue_mapping_rows_sha256=mapping_digest,
            audit_command=" ".join(shlex.quote(item) for item in sys.argv),
            scientific_boundaries=[
                (
                    "topology.psf is a public force-field topology and structure.pdb is the "
                    "coordinate topology used to read the bounded XTC trajectory"
                ),
                (
                    "the MDDB /inputs endpoint is a standardized generated workflow input; "
                    "the original NAMD execution command or .conf file is not public"
                ),
                (
                    "PSF and PDB atom names are compared both exactly and after only documented "
                    "CHARMM/PDB hydrogen and terminal-atom normalisation"
                ),
                (
                    "MD-to-PDB correspondence is sequence-aligned and never inferred from "
                    "matching residue numbers alone"
                ),
                (
                    "PDB-to-UniProt residue positions are composed only from length-consistent "
                    "SIFTS segments for the expected accession"
                ),
                (
                    "construct substitutions and unresolved PDB residues remain explicit; "
                    "only sequence-matching aligned residues receive UniProt coordinates"
                ),
                (
                    "the trajectory audit downloads only the public first ten frames, not the "
                    "complete 5435-frame trajectory"
                ),
            ],
        )
        args.output.write_text(
            json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True),
            encoding="utf-8",
        )

        failures: list[str] = []
        if not report.published:
            failures.append("project_not_published")
        if not consistency.passed:
            failures.extend(consistency.failures)
        if not mapping_audit.status.startswith("verified"):
            failures.append(f"residue_mapping_not_verified:{mapping_audit.status}")
        if mapping_audit.pdb_mapping_coverage < 0.95:
            failures.append(
                "pdb_mapping_coverage_below_0.95:"
                f"{mapping_audit.pdb_mapping_coverage:.6f}"
            )
        if mapping_audit.uniprot_mapping_coverage < 0.90:
            failures.append(
                "uniprot_mapping_coverage_below_0.90:"
                f"{mapping_audit.uniprot_mapping_coverage:.6f}"
            )
        if failures:
            raise SystemExit("file-backed acceptance gate failed: " + "; ".join(failures))

        print(
            json.dumps(
                {
                    "case_id": report.case_id,
                    "project": report.project_accession,
                    "assets": {
                        asset.filename: {"bytes": asset.byte_size, "sha256": asset.sha256}
                        for asset in report.assets
                    },
                    "counts": report.counts.model_dump(mode="json"),
                    "consistency": report.consistency.model_dump(mode="json"),
                    "atom_identity_diagnostics": identity_diagnostics,
                    "workflow": report.workflow.model_dump(mode="json"),
                    "residue_mapping": report.residue_mapping.model_dump(mode="json"),
                    "report_sha256": canonical_sha256(report.model_dump(mode="json")),
                },
                indent=2,
                sort_keys=True,
            )
        )
    finally:
        client.close()


if __name__ == "__main__":
    main()
