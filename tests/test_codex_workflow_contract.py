from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT_NAMES = ("explorer", "reviewer", "tester")
SKILL_NAMES = (
    "ci-triage",
    "fix-bug",
    "implement-feature",
    "repository-verification",
    "review-change",
    "safe-db-migration",
)


def load_toml(path: Path) -> dict[str, object]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def test_single_active_task_structure() -> None:
    assert (ROOT / "tasks" / "README.md").is_file()
    assert (ROOT / "tasks" / "TASK_TEMPLATE.md").is_file()
    active_files = tuple((ROOT / "tasks" / "active").glob("*"))
    assert active_files == (ROOT / "tasks" / "active" / "TASK.md",)
    active_text = active_files[0].read_text(encoding="utf-8")
    assert "## Status\nACTIVE" in active_text or active_text == (
        "# No active task\n## Status\nNONE\n"
    )
    completed_tasks = tuple((ROOT / "tasks" / "completed").glob("*.md"))
    assert completed_tasks
    assert all(
        re.fullmatch(r"\d{4}-\d{2}-\d{2}-[a-z0-9-]+\.md", path.name)
        for path in completed_tasks
    )


def test_codex_agent_config_is_bounded_and_read_only() -> None:
    config = load_toml(ROOT / ".codex" / "config.toml")
    agents = config["agents"]
    assert isinstance(agents, dict)
    assert agents["max_depth"] == 1
    assert 1 <= agents["max_threads"] <= 3

    for name in AGENT_NAMES:
        agent = load_toml(ROOT / ".codex" / "agents" / f"{name}.toml")
        assert agent["name"] == name
        assert agent["sandbox_mode"] == "read-only"
        assert isinstance(agent["description"], str) and agent["description"]
        assert isinstance(agent["developer_instructions"], str)
        instructions = agent["developer_instructions"]
        assert "Do not modify" in instructions or "without modifying" in instructions


def test_repository_skills_have_required_frontmatter() -> None:
    for name in SKILL_NAMES:
        path = ROOT / ".agents" / "skills" / name / "SKILL.md"
        content = path.read_text(encoding="utf-8")
        match = re.match(
            r"\A---\nname: ([a-z0-9-]+)\ndescription: (.+)\n---\n",
            content,
        )
        assert match is not None, path
        assert match.group(1) == name
        assert match.group(2).strip()


def test_required_agent_documents_and_ci_paths_exist() -> None:
    for relative_path in (
        ".ai/architecture.md",
        ".ai/product.md",
        ".ai/decisions.md",
        ".ai/code-review.md",
        ".ai/known-issues.md",
    ):
        assert (ROOT / relative_path).is_file(), relative_path

    workflow = (ROOT / ".github" / "workflows" / "project-tests.yml").read_text(
        encoding="utf-8"
    )
    for expected_path in (
        "AGENTS.override.md",
        "*/AGENTS.md",
        "*/AGENTS.override.md",
        ".ai/*",
        ".agents/*",
        ".codex/*",
        "tasks/*",
        "scripts/*.ps1",
    ):
        assert expected_path in workflow


def test_agent_rules_require_proactive_remote_handoff_approval() -> None:
    rules = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "proactively request approval" in rules
    assert "create a pull request" in rules
    assert "merge it into `main`" in rules
    assert "align any legacy local `main`" in rules


def test_local_quality_rules_require_pinned_go() -> None:
    rules = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    audit = (ROOT / "scripts" / "check_local_tools.ps1").read_text(encoding="utf-8")
    docs = (ROOT / "docs" / "local-development-tools.md").read_text(
        encoding="utf-8"
    )
    versions = (ROOT / "config" / "quality-tools.env").read_text(encoding="utf-8")

    assert "Go and Deno are required for `just quality`" in rules
    assert '@{ Name = "go"; Command = "go"; Arguments = @("version"); Required = $true }' in audit
    assert "| Go | Required |" in docs
    assert "GO_VERSION=1.26.5" in versions


def test_windows_python_quality_paths_use_lf_stdout() -> None:
    quality_script = (
        ROOT / "scripts" / "run_quality_security_checks.sh"
    ).read_text(encoding="utf-8")

    assert 'sys.stdout.reconfigure(newline="\\n")' in quality_script
