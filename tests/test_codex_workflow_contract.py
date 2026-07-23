from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT_NAMES = ("explorer", "reviewer", "tester")
TASK_SECTIONS = (
    "Status",
    "Authorization",
    "Primary Outcome",
    "Background",
    "Subtasks",
    "Allowed Scope",
    "Prohibited Changes",
    "Public Contracts",
    "Risk Classification",
    "Validation Plan",
    "Stop Conditions",
    "Definition of Done",
    "Results",
)
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
    if active_text != "# No active task\n## Status\nNONE\n":
        assert "## Status\nACTIVE" in active_text
        for section in TASK_SECTIONS:
            assert f"## {section}\n" in active_text

    template = (ROOT / "tasks" / "TASK_TEMPLATE.md").read_text(encoding="utf-8")
    assert template.startswith("# Work Package Template — Not Executable\n")
    assert "## Status\nTEMPLATE" in template
    assert "## Status\nACTIVE" not in template
    for section in TASK_SECTIONS:
        assert f"## {section}\n" in template

    completed_tasks = tuple((ROOT / "tasks" / "completed").glob("*.md"))
    assert completed_tasks
    assert all(
        re.fullmatch(r"\d{4}-\d{2}-\d{2}-[a-z0-9-]+\.md", path.name)
        for path in completed_tasks
    )


def test_continuity_is_bounded_state_not_authority() -> None:
    path = ROOT / ".codex" / "CONTINUITY.md"
    content = path.read_text(encoding="utf-8")

    assert len(content.splitlines()) <= 100
    assert path.stat().st_size <= 12 * 1024
    assert "records state, not authorization" in content
    assert "must not replace `tasks/active/TASK.md`" in content
    for section in (
        "Current Work Package",
        "Current Branch",
        "Completed Work",
        "Remaining Work",
        "Key Decisions",
        "Validation Already Passed",
        "Known Issues or Blockers",
        "Commit and Draft PR References",
        "Maintenance",
    ):
        assert f"## {section}\n" in content


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
        ".codex/CONTINUITY.md",
        "tasks/README.md",
        "tasks/TASK_TEMPLATE.md",
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


def test_agent_rules_define_work_package_authority_and_protected_operations() -> None:
    rules = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    normalized_rules = " ".join(rules.split())

    assert "`FULL_LOCAL_AND_DRAFT_PR`" in normalized_rules
    assert "Without repeated approval" in normalized_rules
    assert "push only to `codex/*`" in normalized_rules
    assert "create or update a Draft Pull" in normalized_rules
    assert (
        "Separate explicit user authorization is always required" in normalized_rules
    )
    assert (
        "Before edits verify repository root, branch, worktree status, and diff"
        in normalized_rules
    )
    assert "only the primary agent writes" in normalized_rules
    assert "Use read-only subagents only when explicitly requested" in normalized_rules
    for protected_operation in (
        "protected-branch push",
        "merge or auto-merge",
        "Preview, Staging, or Production deployment",
        "production workflow",
        "production data, schema, infrastructure, DNS, billing, or settings",
        "destructive migration",
        "secret access, output, rotation, or modification",
        "destructive remote deletion",
        "repository-wide core dependency upgrade or removal",
        "real trading",
    ):
        assert protected_operation in normalized_rules
    assert (
        "proactively request approval to create a pull request"
        not in normalized_rules
    )


def test_task_workflow_separates_template_active_archive_and_session_state() -> None:
    workflow = (ROOT / "tasks" / "README.md").read_text(encoding="utf-8")

    assert "`tasks/active/TASK.md`: exactly one actual current Work Package" in workflow
    assert "`tasks/TASK_TEMPLATE.md`: a non-executable checklist" in workflow
    assert "never copy an unfilled template into the active slot" in workflow
    assert "exactly `COMPLETE`, `PARTIAL`, or `BLOCKED`" in workflow
    assert "does not require a new Codex session" in workflow
    assert "below 100 physical lines and 12 KiB" in workflow


def test_layered_instruction_references_resolve() -> None:
    for relative_path in (
        ".ai/product.md",
        ".ai/architecture.md",
        ".ai/decisions.md",
        ".ai/code-review.md",
        ".ai/known-issues.md",
        ".agents/skills/repository-verification/SKILL.md",
        ".codex/CONTINUITY.md",
        "docs/current-status.md",
        "model_card.md",
        "tasks/active/TASK.md",
        "tasks/README.md",
        "tasks/TASK_TEMPLATE.md",
    ):
        assert (ROOT / relative_path).exists(), relative_path

    rules = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "UNSUPPORTED_HORIZON" not in rules
    assert "P10/P50/P90" not in rules


def test_local_quality_rules_require_pinned_go() -> None:
    rules = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    normalized_rules = " ".join(rules.split())
    audit = (ROOT / "scripts" / "check_local_tools.ps1").read_text(encoding="utf-8")
    docs = (ROOT / "docs" / "local-development-tools.md").read_text(
        encoding="utf-8"
    )
    versions = (ROOT / "config" / "quality-tools.env").read_text(encoding="utf-8")

    assert "Go and Deno are required for `just quality`" in normalized_rules
    assert '@{ Name = "go"; Command = "go"; Arguments = @("version"); Required = $true }' in audit
    assert "| Go | Required |" in docs
    assert "GO_VERSION=1.26.5" in versions


def test_windows_python_quality_paths_use_lf_stdout() -> None:
    quality_script = (
        ROOT / "scripts" / "run_quality_security_checks.sh"
    ).read_text(encoding="utf-8")

    assert 'sys.stdout.reconfigure(newline="\\n")' in quality_script
