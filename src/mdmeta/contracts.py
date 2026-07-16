from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from pydantic import BaseModel

from .file_backed import FileBackedMDReport
from .graph import GraphExportManifest
from .integration import IntegratedMDRecord
from .llm_adapter import LLMEventResponse, LLMEventResponseV2
from .pdbekb import PDBeKBBatchReport
from .release import ReleaseManifest


CONTRACTS: dict[str, type[BaseModel]] = {
    "file-backed-md-record-v1.schema.json": FileBackedMDReport,
    "mdmeta-graph-export-v1.schema.json": GraphExportManifest,
    "integrated-md-record-v1.schema.json": IntegratedMDRecord,
    "llm-event-response-v2.schema.json": LLMEventResponseV2,
    "llm-event-response-v3.schema.json": LLMEventResponse,
    "mdmeta-dataset-release-v1.schema.json": ReleaseManifest,
    "pdbekb-enrichment-batch-v1.schema.json": PDBeKBBatchReport,
}


def _render(model: type[BaseModel]) -> bytes:
    return (
        json.dumps(model.model_json_schema(), indent=2, sort_keys=True).encode("utf-8")
        + b"\n"
    )


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def export_contracts(output_dir: str | Path, *, check: bool = False) -> list[Path]:
    """Export or verify deterministic public JSON Schema artifacts."""

    root = Path(output_dir)
    expected_names = set(CONTRACTS)
    if check:
        candidates = list(root.glob("*.schema.json"))
        unsafe = sorted(
            path.name for path in candidates if path.is_symlink() or not path.is_file()
        )
        if unsafe:
            raise ValueError(
                "contract schema inventory contains unsafe paths: " + ", ".join(unsafe)
            )
        actual_names = {path.name for path in candidates}
        if actual_names != expected_names:
            missing = sorted(expected_names - actual_names)
            extra = sorted(actual_names - expected_names)
            raise ValueError(
                f"contract schema inventory mismatch; missing={missing}, extra={extra}"
            )
    outputs: list[Path] = []
    for filename, model in sorted(CONTRACTS.items()):
        destination = root / filename
        rendered = _render(model)
        if check:
            if not destination.is_file() or destination.read_bytes() != rendered:
                raise ValueError(f"contract schema artifact is out of date: {destination}")
        else:
            _atomic_write(destination, rendered)
        outputs.append(destination)
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export or verify the versioned MD metadata JSON Schema contracts."
    )
    parser.add_argument("--output-dir", type=Path, default=Path("schemas"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    outputs = export_contracts(args.output_dir, check=args.check)
    print(json.dumps({"schemas": [str(path) for path in outputs]}, indent=2))


if __name__ == "__main__":
    main()
