from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from mdmeta.integration import IntegratedMDRecord
from mdmeta.models import MappingSegment
from mdmeta.sifts_qa import SIFTSQAReport, audit_sifts_segments


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _load(path: Path) -> list[MappingSegment]:
    if path.suffix.lower() == ".jsonl":
        return [
            MappingSegment.model_validate(json.loads(line))
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and payload.get("schema_version") == "integrated-md-record-v1":
        return IntegratedMDRecord.model_validate(payload).residue_mappings
    if isinstance(payload, dict) and isinstance(payload.get("residue_mappings"), list):
        return [MappingSegment.model_validate(row) for row in payload["residue_mappings"]]
    if isinstance(payload, list):
        return [MappingSegment.model_validate(row) for row in payload]
    raise ValueError("input must be an IntegratedMDRecord, a mapping list, or JSONL segments")


def _markdown(report: SIFTSQAReport) -> str:
    lines = [
        "# SIFTS compatibility audit",
        "",
        f"- Segments: {report.segment_count}",
        f"- Complete ranges: {report.complete_range_count}",
        f"- Length-consistent ranges: {report.length_consistent_count}",
        f"- PDB-chain groups: {report.chain_count}",
        f"- Multi-accession chains: {report.multi_accession_chain_count}",
        "",
        "| Severity | Code | Segments | Message |",
        "|---|---|---|---|",
    ]
    for issue in report.issues:
        indexes = ", ".join(str(index) for index in issue.segment_indexes)
        lines.append(
            f"| {issue.severity} | `{issue.code}` | {indexes} | {issue.message} |"
        )
    if not report.issues:
        lines.append("| info | `none` |  | No compatibility issues detected. |")
    lines.extend(["", "## Interpretation", ""])
    lines.extend(f"- {item}" for item in report.interpretation)
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit SIFTS-derived mapping ranges before MD-residue composition."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()

    report = audit_sifts_segments(_load(args.input))
    _atomic_write(args.output, report.model_dump_json(indent=2) + "\n")
    if args.markdown is not None:
        _atomic_write(args.markdown, _markdown(report))
    print(
        json.dumps(
            {
                "segments": report.segment_count,
                "issues": len(report.issues),
                "errors": report.severity_counts.get("error", 0),
                "output": str(args.output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
