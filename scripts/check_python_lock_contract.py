#!/usr/bin/env python3
"""Verify the exported Python requirements remain complete and exactly pinned."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = ROOT / "pyproject.toml"
UV_LOCK_PATH = ROOT / "uv.lock"
REQUIREMENTS_PATH = ROOT / "requirements.lock"
EXPECTED_HEADER = (
    "#    uv export --frozen --extra test --no-emit-project "
    "--format requirements.txt --no-hashes --output-file requirements.lock"
)
NAME_PATTERN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]+\])?")
PIN_PATTERN = re.compile(
    r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]+\])?==([^\s;]+)(?:\s*;.*)?$"
)


def canonicalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def dependency_name(requirement: str) -> str:
    match = NAME_PATTERN.match(requirement.strip())
    if match is None:
        raise ValueError(f"Unable to parse dependency declaration: {requirement!r}")
    return canonicalize_name(match.group(1))


def load_toml(path: Path) -> dict[str, object]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def parse_exported_requirements(text: str) -> Counter[tuple[str, str]]:
    pins: Counter[tuple[str, str]] = Counter()
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if raw_line[:1].isspace():
            continue
        match = PIN_PATTERN.fullmatch(line)
        if match is None:
            raise ValueError(
                f"requirements.lock:{line_number} must be an exact == pin: {raw_line!r}"
            )
        pins[(canonicalize_name(match.group(1)), match.group(2))] += 1
    return pins


def parse_locked_packages(lock_data: dict[str, object]) -> Counter[tuple[str, str]]:
    packages = lock_data.get("package")
    if not isinstance(packages, list):
        raise ValueError("uv.lock does not contain a [[package]] array")

    pins: Counter[tuple[str, str]] = Counter()
    for package in packages:
        if not isinstance(package, dict):
            raise ValueError("uv.lock contains a malformed package entry")
        source = package.get("source")
        if isinstance(source, dict) and "editable" in source:
            continue
        name = package.get("name")
        version = package.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            raise ValueError("uv.lock package entries must include string name and version")
        pins[(canonicalize_name(name), version)] += 1
    return pins


def declared_dependency_names(pyproject: dict[str, object]) -> set[str]:
    project = pyproject.get("project")
    if not isinstance(project, dict):
        raise ValueError("pyproject.toml is missing [project]")

    declarations: list[str] = []
    dependencies = project.get("dependencies")
    if isinstance(dependencies, list):
        declarations.extend(item for item in dependencies if isinstance(item, str))

    optional = project.get("optional-dependencies")
    if isinstance(optional, dict):
        test_dependencies = optional.get("test")
        if isinstance(test_dependencies, list):
            declarations.extend(item for item in test_dependencies if isinstance(item, str))

    return {dependency_name(item) for item in declarations}


def format_counter(counter: Counter[tuple[str, str]]) -> str:
    return ", ".join(
        f"{name}=={version}" + (f" (x{count})" if count > 1 else "")
        for (name, version), count in sorted(counter.items())
    )


def main() -> int:
    try:
        pyproject = load_toml(PYPROJECT_PATH)
        lock_data = load_toml(UV_LOCK_PATH)
        requirements_text = REQUIREMENTS_PATH.read_text(encoding="utf-8")
        if EXPECTED_HEADER not in requirements_text.splitlines()[:3]:
            raise ValueError(
                "requirements.lock was not generated with the reviewed uv export command"
            )

        exported_pins = parse_exported_requirements(requirements_text)
        locked_pins = parse_locked_packages(lock_data)
        if exported_pins != locked_pins:
            missing = locked_pins - exported_pins
            extra = exported_pins - locked_pins
            details: list[str] = []
            if missing:
                details.append(f"missing from requirements.lock: {format_counter(missing)}")
            if extra:
                details.append(f"not present in uv.lock: {format_counter(extra)}")
            raise ValueError("; ".join(details))

        exported_names = {name for name, _ in exported_pins}
        missing_direct = declared_dependency_names(pyproject) - exported_names
        if missing_direct:
            raise ValueError(
                "direct/test dependencies missing from requirements.lock: "
                + ", ".join(sorted(missing_direct))
            )
    except (OSError, ValueError, tomllib.TOMLDecodeError) as error:
        print(f"Python lock contract check failed: {error}", file=sys.stderr)
        return 1

    print(
        "Python lock contract check passed: "
        f"{sum(exported_pins.values())} exact package-version pins cover uv.lock and project/test dependencies."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
