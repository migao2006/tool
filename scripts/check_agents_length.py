from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT_LINE_LIMIT = 100
ROOT_SIZE_LIMIT = 16 * 1024
COMBINED_SIZE_LIMIT = 28 * 1024
EXCLUDED_PARTS = {".git", ".venv", "node_modules"}


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
    if path.name == "AGENTS.md":
        return True
    if relative.parts and relative.parts[0] == ".ai" and path.suffix == ".md":
        return True
    return (
        len(relative.parts) >= 4
        and relative.parts[:2] == (".agents", "skills")
        and path.name == "SKILL.md"
    )


def instruction_files(root: Path) -> tuple[Path, ...]:
    candidates: set[Path] = set()
    root_agents = root / "AGENTS.md"
    if root_agents.is_file():
        candidates.add(root_agents)
    for directory in (root / ".ai", root / ".agents" / "skills"):
        if directory.is_dir():
            candidates.update(
                path
                for path in directory.rglob("*.md")
                if path.is_file() and _is_repository_instruction(path, root)
            )
    return tuple(sorted(candidates, key=lambda path: path.as_posix()))


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
        errors.append(
            f"Root AGENTS.md exceeds {ROOT_LINE_LIMIT} physical lines."
        )
    if metrics.root_size_bytes > ROOT_SIZE_LIMIT:
        errors.append("Root AGENTS.md exceeds 16 KiB.")
    if metrics.combined_size_bytes > COMBINED_SIZE_LIMIT:
        errors.append("Combined agent instructions exceed 28 KiB.")
    return tuple(errors)


def output_lines(metrics: InstructionMetrics) -> Iterable[str]:
    yield f"Root AGENTS.md line count: {metrics.root_line_count}/100"
    yield f"Root AGENTS.md size: {metrics.root_size_bytes}/16 KiB"
    yield (
        "Combined agent instruction size: "
        f"{metrics.combined_size_bytes}/28 KiB"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args(argv)
    metrics = measure(args.root)
    for line in output_lines(metrics):
        print(line)
    errors = validation_errors(metrics)
    for error in errors:
        print(f"ERROR: {error}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
