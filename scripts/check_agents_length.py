from __future__ import annotations

import argparse
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

ROOT_LINE_LIMIT = 100
ROOT_SIZE_LIMIT = 16 * 1024
COMBINED_SIZE_LIMIT = 28 * 1024
EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "coverage",
    "playwright-report",
    "artifacts",
    "__pycache__",
}


@dataclass(frozen=True)
class InstructionMetrics:
    root_line_count: int
    root_size_bytes: int
    combined_size_bytes: int
    files: tuple[Path, ...]


def _is_repository_instruction(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if any(part in EXCLUDED_PARTS for part in relative.parts):
        return False
    if path.name in {"AGENTS.md", "AGENTS.override.md"}:
        return True
    if relative.parts[:1] == (".ai",) and path.suffix == ".md":
        return True
    return relative.parts[:2] == (".agents", "skills") and path.name == "SKILL.md"


def instruction_files(root: Path) -> tuple[Path, ...]:
    root = root.resolve()
    candidates: set[Path] = set()
    for directory, child_directories, filenames in os.walk(root):
        child_directories[:] = [
            name for name in child_directories if name not in EXCLUDED_PARTS
        ]
        directory_path = Path(directory)
        for filename in filenames:
            path = directory_path / filename
            if _is_repository_instruction(path, root):
                candidates.add(path)
    return tuple(sorted(candidates, key=lambda path: path.relative_to(root).as_posix()))


def measure(root: Path) -> InstructionMetrics:
    root = root.resolve()
    root_agents = root / "AGENTS.md"
    if not root_agents.is_file():
        raise FileNotFoundError(f"Missing root AGENTS.md: {root_agents}")
    raw = root_agents.read_bytes()
    files = instruction_files(root)
    return InstructionMetrics(
        root_line_count=len(raw.splitlines()),
        root_size_bytes=len(raw),
        combined_size_bytes=sum(path.stat().st_size for path in files),
        files=files,
    )


def validation_errors(metrics: InstructionMetrics) -> tuple[str, ...]:
    errors: list[str] = []
    if metrics.root_line_count > ROOT_LINE_LIMIT:
        errors.append(f"AGENTS.md: exceeds {ROOT_LINE_LIMIT} physical lines.")
    if metrics.root_size_bytes > ROOT_SIZE_LIMIT:
        errors.append(f"AGENTS.md: exceeds {ROOT_SIZE_LIMIT} bytes (16 KiB).")
    if metrics.combined_size_bytes > COMBINED_SIZE_LIMIT:
        paths = ", ".join(path.as_posix() for path in metrics.files)
        errors.append(f"Combined agent instructions exceed {COMBINED_SIZE_LIMIT} bytes (28 KiB); checked: {paths}")
    return tuple(errors)


def output_lines(metrics: InstructionMetrics) -> Iterable[str]:
    yield f"Root AGENTS.md line count: {metrics.root_line_count}/100"
    yield f"Root AGENTS.md size: {metrics.root_size_bytes}/16 KiB"
    yield f"Combined agent instruction size: {metrics.combined_size_bytes}/28 KiB"
    yield f"Instruction files checked: {len(metrics.files)}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args(argv)
    parsed_values: dict[str, object] = vars(args)
    root_value = parsed_values.get("root")
    if not isinstance(root_value, Path):
        raise TypeError("--root must resolve to a pathlib.Path")
    root = root_value
    try:
        metrics = measure(root)
    except FileNotFoundError as error:
        print(f"ERROR: {error}")
        return 1
    for line in output_lines(metrics):
        print(line)
    errors = validation_errors(metrics)
    for error in errors:
        print(f"ERROR: {error}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
