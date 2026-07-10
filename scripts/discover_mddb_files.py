from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import httpx


TOPOLOGY_EXTENSIONS = {".psf", ".prmtop", ".parm7", ".top", ".tpr", ".gro", ".pdb", ".cif"}
TRAJECTORY_EXTENSIONS = {".xtc", ".trr", ".dcd", ".nc", ".netcdf"}
WORKFLOW_EXTENSIONS = {".conf", ".namd", ".inp", ".in", ".yaml", ".yml", ".json", ".sh", ".log"}


def classify(filename: str) -> list[str]:
    lower = filename.lower()
    suffix = Path(lower).suffix
    roles: list[str] = []
    if suffix in TOPOLOGY_EXTENSIONS or "structure" in lower or "topolog" in lower:
        roles.append("topology_or_structure")
    if suffix in TRAJECTORY_EXTENSIONS or "trajectory" in lower:
        roles.append("trajectory")
    if suffix in WORKFLOW_EXTENSIONS or any(
        token in lower for token in ("config", "parameter", "workflow", "input", "command")
    ):
        roles.append("workflow_or_parameters")
    return roles or ["other"]


def compact_descriptor(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"raw_type": type(item).__name__, "value": str(item)}
    filename = str(item.get("filename") or item.get("name") or item.get("file") or "")
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return {
        "filename": filename,
        "roles": classify(filename),
        "length": item.get("length") or item.get("size"),
        "content_type": item.get("contentType") or item.get("content_type"),
        "metadata": metadata,
        "keys": sorted(item),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://irb.mddbr.eu/api/rest/current")
    parser.add_argument("--project", default="MCV1900193.2")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    project_url = f"{args.base_url.rstrip('/')}/projects/{args.project}"
    with httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": "md-metadata-pipeline/0.9"}) as client:
        project_response = client.get(project_url)
        project_response.raise_for_status()
        project = project_response.json()
        files_response = client.get(f"{project_url}/files")
        files_response.raise_for_status()
        files = files_response.json()

    descriptors = files if isinstance(files, list) else files.get("files", files)
    if isinstance(descriptors, dict):
        descriptors = [dict(value, logical_name=key) if isinstance(value, dict) else {"name": key, "value": value} for key, value in descriptors.items()]
    if not isinstance(descriptors, list):
        raise TypeError(f"unexpected files response type: {type(descriptors).__name__}")

    metadata = project.get("metadata", {}) if isinstance(project, dict) else {}
    result = {
        "project": args.project,
        "project_url": project_url,
        "published": project.get("published") if isinstance(project, dict) else None,
        "metadata": {
            key: metadata.get(key)
            for key in (
                "NAME", "PROGRAM", "VERSION", "LENGTH", "TIMESTEP", "SNAPSHOTS",
                "FF", "TEMP", "ENSEMBLE", "atomCount", "frameCount", "PDBIDS",
                "REFERENCES", "TOPOREF", "LICENSE", "CITATION",
            )
            if key in metadata
        },
        "descriptor_count": len(descriptors),
        "files": [compact_descriptor(item) for item in descriptors],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
