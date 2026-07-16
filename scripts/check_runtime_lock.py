#!/usr/bin/env python3
"""Validate the exact production runtime constraint set without installing it."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import re
import sys
import tomllib
from email.parser import BytesParser
from pathlib import Path
from zipfile import BadZipFile, ZipFile


EXACT_PIN = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9_.-]*)=="
    r"(?P<version>[A-Za-z0-9][A-Za-z0-9.!+_-]*)$"
)
REQUIREMENT_NAME = re.compile(r"^\s*(?P<name>[A-Za-z0-9][A-Za-z0-9_.-]*)")


def canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def read_exact_constraints(path: Path) -> dict[str, tuple[str, str]]:
    pins: dict[str, tuple[str, str]] = {}
    errors: list[str] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        match = EXACT_PIN.fullmatch(line)
        if match is None:
            errors.append(f"{path}:{line_number}: expected one exact name==version pin")
            continue
        display_name = match.group("name")
        name = canonical_name(display_name)
        if name in pins:
            errors.append(f"{path}:{line_number}: duplicate constraint for {display_name}")
            continue
        pins[name] = (display_name, match.group("version"))
    if not pins:
        errors.append(f"{path}: no constraints found")
    if errors:
        raise ValueError("\n".join(errors))
    return pins


def project_api_profile(path: Path) -> tuple[str, str, set[str]]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    project = data.get("project", {})
    project_name = project.get("name")
    if not isinstance(project_name, str) or not project_name.strip():
        raise ValueError(f"{path}: project.name is missing")
    project_version = project.get("version")
    if not isinstance(project_version, str) or not project_version.strip():
        raise ValueError(f"{path}: project.version is missing")
    requirements = list(project.get("dependencies", []))
    requirements.extend(project.get("optional-dependencies", {}).get("api", []))
    names: set[str] = set()
    for requirement in requirements:
        match = REQUIREMENT_NAME.match(requirement)
        if match is None:
            raise ValueError(f"{path}: cannot parse runtime requirement {requirement!r}")
        names.add(canonical_name(match.group("name")))
    if not names:
        raise ValueError(f"{path}: no API runtime requirements found")
    return canonical_name(project_name), project_version, names


def wheel_identity(path: Path) -> tuple[str, str, str]:
    try:
        with ZipFile(path) as archive:
            metadata_paths = [
                member
                for member in archive.namelist()
                if member.endswith(".dist-info/METADATA")
            ]
            if len(metadata_paths) != 1:
                raise ValueError(
                    f"{path}: expected one .dist-info/METADATA, found {len(metadata_paths)}"
                )
            metadata = BytesParser().parsebytes(archive.read(metadata_paths[0]))
    except BadZipFile as error:
        raise ValueError(f"{path}: invalid wheel archive: {error}") from error

    display_name = metadata.get("Name")
    version = metadata.get("Version")
    if not display_name or not version:
        raise ValueError(f"{path}: wheel METADATA omits Name or Version")
    name = canonical_name(display_name)
    filename_name = canonical_name(path.name.split("-", 1)[0])
    if filename_name != name:
        raise ValueError(
            f"{path}: wheel filename identifies {filename_name}, METADATA identifies {name}"
        )
    return name, display_name, version


def check_wheelhouse(
    wheel_dir: Path,
    pins: dict[str, tuple[str, str]],
    project_name: str,
    project_version: str,
) -> list[str]:
    wheels = sorted(wheel_dir.glob("*.whl"))
    if not wheels:
        return [f"{wheel_dir}: no wheels found"]
    identities: dict[str, list[tuple[str, str, Path]]] = {}
    errors: list[str] = []
    for wheel in wheels:
        try:
            name, display_name, version = wheel_identity(wheel)
        except ValueError as error:
            errors.append(str(error))
            continue
        identities.setdefault(name, []).append((display_name, version, wheel))

    names = set(identities)
    expected = set(pins)
    unexpected = sorted(names - expected - {project_name})
    missing = sorted(expected - names)
    if project_name not in names:
        errors.append(f"wheelhouse omits project wheel: {project_name}")
    if unexpected:
        errors.append("wheelhouse contains unconstrained distributions: " + ", ".join(unexpected))
    if missing:
        errors.append("runtime constraints have no wheel: " + ", ".join(missing))

    for name, entries in sorted(identities.items()):
        if len(entries) != 1:
            paths = ", ".join(str(entry[2]) for entry in entries)
            errors.append(f"wheelhouse contains duplicate distribution {name}: {paths}")
            continue
        display_name, actual_version, _ = entries[0]
        if name in pins:
            expected_version = pins[name][1]
            if actual_version != expected_version:
                errors.append(
                    f"wheel version drift: {display_name}=={actual_version}, "
                    f"expected {expected_version}"
                )
        elif name == project_name and actual_version != project_version:
            errors.append(
                f"project wheel version drift: {actual_version}, expected {project_version}"
            )
    return errors


def check_installed(pins: dict[str, tuple[str, str]]) -> list[str]:
    errors: list[str] = []
    for _, (display_name, expected) in sorted(pins.items()):
        try:
            actual = importlib.metadata.version(display_name)
        except importlib.metadata.PackageNotFoundError:
            errors.append(f"locked runtime package is not installed: {display_name}=={expected}")
            continue
        if actual != expected:
            errors.append(
                f"installed runtime version drift: {display_name}=={actual}, expected {expected}"
            )
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--constraints", type=Path, default=Path("constraints/runtime.txt"))
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--check-installed", action="store_true")
    parser.add_argument("--wheel-dir", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        pins = read_exact_constraints(args.constraints)
        project_name, project_version, declared = project_api_profile(args.pyproject)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as error:
        print(error, file=sys.stderr)
        return 1

    errors: list[str] = []
    missing = sorted(declared - pins.keys())
    if missing:
        errors.append("runtime constraints omit project/API dependencies: " + ", ".join(missing))
    if args.check_installed:
        errors.extend(check_installed(pins))
    if args.wheel_dir is not None:
        errors.extend(check_wheelhouse(args.wheel_dir, pins, project_name, project_version))
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1

    digest = hashlib.sha256(args.constraints.read_bytes()).hexdigest()
    print(f"runtime constraints: {len(pins)} exact pins, sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
