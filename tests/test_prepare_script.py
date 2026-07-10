import json
import subprocess
import sys

from mdmeta.benchmark import CandidateArticle


def write_candidates(path, n=80):
    articles = [
        CandidateArticle(
            document_id=f"PMC{i:06d}",
            title=f"Article {i}",
            source_uri=f"https://example.org/{i}",
            software_family="gromacs",
            year=2018,
        ).model_dump(mode="json")
        for i in range(n)
    ]
    path.write_text(json.dumps({"articles": articles}))


def test_locked_plan_enforces_minimum_exclusion_count(tmp_path) -> None:
    candidates = tmp_path / "candidates.json"
    excluded = tmp_path / "excluded.txt"
    output = tmp_path / "plan.json"
    write_candidates(candidates)
    excluded.write_text("\n".join(f"PMC{i:06d}" for i in range(15)))
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/prepare_confirmatory_benchmark.py",
            "--candidates",
            str(candidates),
            "--excluded-ids",
            str(excluded),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "at least 30" in completed.stderr


def test_temporal_plan_requires_explicit_year_rules_and_is_provisional(tmp_path) -> None:
    candidates = tmp_path / "candidates.json"
    output = tmp_path / "plan.json"
    write_candidates(candidates)
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/prepare_confirmatory_benchmark.py",
            "--candidates",
            str(candidates),
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
    assert completed.returncode == 0, completed.stderr
    plan = json.loads(output.read_text())
    assert plan["study_status"] == "provisional_temporal_isolation"
    assert plan["eligibility_rules"]["publication_year_max"] == 2020
