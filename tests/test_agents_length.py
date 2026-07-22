from __future__ import annotations

from pathlib import Path

from scripts.check_agents_length import (
    COMBINED_SIZE_LIMIT,
    ROOT_LINE_LIMIT,
    ROOT_SIZE_LIMIT,
    instruction_files,
    measure,
    output_lines,
    validation_errors,
)


def test_repository_agent_instructions_stay_within_limits() -> None:
    root = Path(__file__).resolve().parents[1]
    metrics = measure(root)

    assert metrics.root_line_count <= ROOT_LINE_LIMIT
    assert metrics.root_size_bytes <= ROOT_SIZE_LIMIT
    assert metrics.combined_size_bytes <= COMBINED_SIZE_LIMIT
    assert validation_errors(metrics) == ()
    assert list(output_lines(metrics)) == [
        f"Root AGENTS.md line count: {metrics.root_line_count}/100",
        f"Root AGENTS.md size: {metrics.root_size_bytes}/16 KiB",
        (
            "Combined agent instruction size: "
            f"{metrics.combined_size_bytes}/28 KiB"
        ),
    ]


def test_more_than_one_hundred_physical_lines_fails(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("rule\n" * 101, encoding="utf-8")

    metrics = measure(tmp_path)

    assert metrics.root_line_count == 101
    assert validation_errors(metrics) == (
        "Root AGENTS.md exceeds 100 physical lines.",
    )


def test_combined_size_includes_ai_and_skill_instructions(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("root\n", encoding="utf-8")
    ai_file = tmp_path / ".ai" / "architecture.md"
    skill_file = tmp_path / ".agents" / "skills" / "verify" / "SKILL.md"
    ai_file.parent.mkdir(parents=True)
    skill_file.parent.mkdir(parents=True)
    ai_file.write_text("architecture\n", encoding="utf-8")
    skill_file.write_text("skill\n", encoding="utf-8")

    metrics = measure(tmp_path)

    assert instruction_files(tmp_path) == tuple(
        sorted(
            (tmp_path / "AGENTS.md", ai_file, skill_file),
            key=lambda path: path.as_posix(),
        )
    )
    assert metrics.combined_size_bytes == sum(
        path.stat().st_size for path in metrics.files
    )
