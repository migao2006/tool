from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_agents_length import (
    COMBINED_SIZE_LIMIT,
    ROOT_LINE_LIMIT,
    ROOT_SIZE_LIMIT,
    instruction_files,
    main,
    measure,
    output_lines,
    validation_errors,
)


def write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text(content, encoding="utf-8")
    return path.resolve()


def test_repository_agent_instructions_stay_within_limits() -> None:
    metrics = measure(Path(__file__).resolve().parents[1])

    assert metrics.root_line_count <= ROOT_LINE_LIMIT
    assert metrics.root_size_bytes <= ROOT_SIZE_LIMIT
    assert metrics.combined_size_bytes <= COMBINED_SIZE_LIMIT
    assert validation_errors(metrics) == ()
    assert list(output_lines(metrics)) == [
        f"Root AGENTS.md line count: {metrics.root_line_count}/100",
        f"Root AGENTS.md size: {metrics.root_size_bytes}/16 KiB",
        f"Combined agent instruction size: {metrics.combined_size_bytes}/28 KiB",
        f"Instruction files checked: {len(metrics.files)}",
    ]


def test_more_than_one_hundred_physical_lines_fails(tmp_path: Path) -> None:
    _ = write(tmp_path / "AGENTS.md", "rule\n" * 101)

    metrics = measure(tmp_path)

    assert metrics.root_line_count == 101
    assert validation_errors(metrics) == ("AGENTS.md: exceeds 100 physical lines.",)


def test_root_larger_than_sixteen_kib_fails(tmp_path: Path) -> None:
    _ = write(tmp_path / "AGENTS.md", "x" * (ROOT_SIZE_LIMIT + 1))

    assert validation_errors(measure(tmp_path)) == (
        f"AGENTS.md: exceeds {ROOT_SIZE_LIMIT} bytes (16 KiB).",
    )


def test_combined_size_larger_than_twenty_eight_kib_fails(tmp_path: Path) -> None:
    _ = write(tmp_path / "AGENTS.md", "root\n")
    _ = write(tmp_path / ".ai" / "large.md", "x" * COMBINED_SIZE_LIMIT)

    errors = validation_errors(measure(tmp_path))

    assert len(errors) == 1
    assert errors[0].startswith("Combined agent instructions exceed 28672 bytes")
    assert ".ai/large.md" in errors[0]


def test_nested_agents_and_override_are_discovered(tmp_path: Path) -> None:
    root_agents = write(tmp_path / "AGENTS.md", "root\n")
    nested_agents = write(tmp_path / "src" / "AGENTS.md", "nested\n")
    nested_override = write(
        tmp_path / "src" / "feature" / "AGENTS.override.md", "override\n"
    )

    assert instruction_files(tmp_path) == (
        root_agents,
        nested_agents,
        nested_override,
    )


@pytest.mark.parametrize(
    "excluded_directory",
    [
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "dist",
        "build",
        "coverage",
        "playwright-report",
        "artifacts",
        "__pycache__",
    ],
)
def test_excluded_directories_are_not_counted(
    tmp_path: Path, excluded_directory: str
) -> None:
    root_agents = write(tmp_path / "AGENTS.md", "root\n")
    _ = write(tmp_path / excluded_directory / "AGENTS.md", "ignored\n")
    _ = write(tmp_path / excluded_directory / ".ai" / "ignored.md", "ignored\n")

    assert instruction_files(tmp_path) == (root_agents,)


def test_instruction_discovery_prevents_duplicates(tmp_path: Path) -> None:
    root_agents = write(tmp_path / "AGENTS.md", "root\n")
    overlapping = write(tmp_path / ".ai" / "AGENTS.md", "one file, two rules\n")
    skill = write(tmp_path / ".agents" / "skills" / "verify" / "SKILL.md", "skill\n")

    files = instruction_files(tmp_path)

    assert files == (skill, overlapping, root_agents)
    assert len(files) == len(set(files))


def test_missing_root_agents_fails_with_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--root", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert "ERROR: Missing root AGENTS.md:" in output
    assert str(tmp_path / "AGENTS.md") in output
