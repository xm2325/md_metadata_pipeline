from __future__ import annotations

import runpy
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


CHECKER = runpy.run_path(
    str(Path(__file__).parents[1] / "scripts" / "check_runtime_lock.py")
)
check_wheelhouse = CHECKER["check_wheelhouse"]


def write_wheel(
    directory: Path,
    filename: str,
    distribution: str,
    version: str,
) -> None:
    wheel = directory / filename
    metadata_dir = distribution.replace("-", "_")
    metadata = (
        "Metadata-Version: 2.4\n"
        f"Name: {distribution}\n"
        f"Version: {version}\n"
    )
    with ZipFile(wheel, "w", ZIP_DEFLATED) as archive:
        archive.writestr(f"{metadata_dir}-{version}.dist-info/METADATA", metadata)


def test_wheelhouse_accepts_canonical_names_and_exact_versions(tmp_path: Path) -> None:
    write_wheel(tmp_path, "alpha_lib-1.2.3-py3-none-any.whl", "Alpha.Lib", "1.2.3")
    write_wheel(tmp_path, "demo_project-0.11.0-py3-none-any.whl", "demo-project", "0.11.0")

    errors = check_wheelhouse(
        tmp_path,
        {"alpha-lib": ("alpha-lib", "1.2.3")},
        "demo-project",
        "0.11.0",
    )

    assert errors == []


def test_wheelhouse_rejects_drift_duplicates_and_unlocked_wheels(tmp_path: Path) -> None:
    write_wheel(tmp_path, "alpha_lib-1.2.4-py3-none-any.whl", "alpha-lib", "1.2.4")
    write_wheel(tmp_path, "alpha_lib-1.2.4-1-py3-none-any.whl", "alpha-lib", "1.2.4")
    write_wheel(tmp_path, "beta_lib-2.1.0-py3-none-any.whl", "beta-lib", "2.1.0")
    write_wheel(tmp_path, "rogue-9.0.0-py3-none-any.whl", "rogue", "9.0.0")
    write_wheel(tmp_path, "demo_project-0.10.0-py3-none-any.whl", "demo-project", "0.10.0")

    errors = check_wheelhouse(
        tmp_path,
        {
            "alpha-lib": ("alpha-lib", "1.2.3"),
            "beta-lib": ("beta-lib", "2.0.0"),
            "missing-lib": ("missing-lib", "2.0.0"),
        },
        "demo-project",
        "0.11.0",
    )

    combined = "\n".join(errors)
    assert "unconstrained distributions: rogue" in combined
    assert "runtime constraints have no wheel: missing-lib" in combined
    assert "duplicate distribution alpha-lib" in combined
    assert "wheel version drift: beta-lib==2.1.0, expected 2.0.0" in combined
    assert "project wheel version drift: 0.10.0, expected 0.11.0" in combined


def test_wheelhouse_reports_invalid_metadata_without_crashing(tmp_path: Path) -> None:
    (tmp_path / "broken-1.0.0-py3-none-any.whl").write_text("not a zip")

    errors = check_wheelhouse(
        tmp_path,
        {"broken": ("broken", "1.0.0")},
        "demo-project",
        "0.11.0",
    )

    combined = "\n".join(errors)
    assert "invalid wheel archive" in combined
    assert "runtime constraints have no wheel: broken" in combined
    assert "wheelhouse omits project wheel: demo-project" in combined
