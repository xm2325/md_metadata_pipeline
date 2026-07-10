from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _manifest(path: Path, n: int = 70) -> None:
    path.write_text(
        json.dumps(
            {
                "articles": [
                    {
                        "document_id": f"PMC{i:06d}",
                        "title": f"Article {i}",
                        "source_uri": f"https://example.org/{i}",
                        "year": 2018 + (i % 3),
                        "software_family": ["gromacs", "amber", "namd"][i % 3],
                        "full_text_available": True,
                    }
                    for i in range(n)
                ]
            }
        ),
        encoding="utf-8",
    )


def test_locked_plan_refuses_incomplete_prior_registry(tmp_path: Path) -> None:
    manifest = tmp_path / "candidates.json"
    _manifest(manifest)
    excluded = tmp_path / "excluded.txt"
    excluded.write_text("PMC000000\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "scripts/prepare_confirmatory_benchmark.py",
            "--candidates",
            str(manifest),
            "--excluded-ids",
            str(excluded),
            "--output",
            str(tmp_path / "plan.json"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "at least 30" in (result.stdout + result.stderr)


def test_provisional_temporal_plan_requires_explicit_year_gate(tmp_path: Path) -> None:
    manifest = tmp_path / "candidates.json"
    _manifest(manifest)
    excluded = tmp_path / "excluded.txt"
    excluded.write_text("PMC000000\n", encoding="utf-8")
    output = tmp_path / "plan.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/prepare_confirmatory_benchmark.py",
            "--candidates",
            str(manifest),
            "--excluded-ids",
            str(excluded),
            "--output",
            str(output),
            "--study-status",
            "provisional_temporal_isolation",
            "--publication-year-max",
            "2020",
            "--require-known-year",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    plan = json.loads(output.read_text(encoding="utf-8"))
    assert plan["study_status"] == "provisional_temporal_isolation"
    assert plan["eligibility_rules"]["publication_year_max"] == 2020
