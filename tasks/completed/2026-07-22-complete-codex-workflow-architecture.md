# Complete Codex Repository Workflow Architecture
## Status
COMPLETED
## Goal
Complete the missing repository-level Codex workflow architecture while preserving product behavior and all unrelated worktree changes.
## Confirmed Context
- The root `AGENTS.md` was 67 physical lines and 3,758 bytes before this task.
- `.ai/` already contained architecture, product, decisions, and code-review contracts.
- One repository verification Skill, instruction checks, fast/full scripts, CI checks, and a cleanup report already existed.
- `.ai/known-issues.md`, focused workflow Skills, `.codex/`, and the single-active-task structure were absent before this task.
- The worktree contained pre-existing tracked and untracked changes before this task.
## In Scope
- Repository instructions, task workflow, Skills, Codex subagent configuration, instruction validation, local verification, CI scope detection, and cleanup evidence.
## Out of Scope
- Product behavior, model logic, database data, cloud settings, deployment, commit, push, pull request, and production operations.
## Constraints
- Preserve `horizon=5`, `RESEARCH_ONLY`, point-in-time integrity, ranking authority, ETF separation, and all security boundaries.
- Only the primary agent may write; configured subagents are read-only.
- Do not delete an uncertain file or overwrite unrelated user changes.
## Execution Plan
1. Translate repository-level technical instructions and add task/issue documentation.
2. Add focused Skills and supported read-only Codex subagent definitions.
3. Expand instruction validation, tests, local verification, and CI path detection.
4. Re-audit cleanup candidates and record evidence.
5. Run validation, record real results, archive this task, and reset the active task.
## Validation Commands
- `python scripts/check_agents_length.py`
- `uv run --system-certs --extra test pytest -q tests/test_agents_length.py`
- `pwsh -File scripts/verify-fast.ps1`
- `pwsh -File scripts/verify-full.ps1`
- `git diff --check`
- `git status --short`
- `git diff --stat`
- `git diff --name-status`
- `git diff`
## Definition of Done
- All user-defined workflow architecture criteria are satisfied or truthfully reported as blocked.
- Required instruction limits and focused tests pass.
- No unrelated product behavior, production resource, or Git remote state changes.
- The completed task is archived and the active task is reset to `NONE`.
## Results
- Translated root `AGENTS.md`, `.ai/architecture.md`, `.ai/code-review.md`, `.ai/decisions.md`, and the repository verification Skill to English while retaining Traditional Chinese product terminology in `.ai/product.md`.
- Added the single-active-task workflow, `.ai/known-issues.md`, five focused workflow Skills, and three project-scoped read-only Codex agent definitions.
- Confirmed supported Codex fields from the current official Codex manual; the local `codex.exe` help command was blocked by WindowsApps access control.
- Expanded instruction discovery and added tests for limits, nested files, overrides, exclusions, duplicate prevention, and missing root instructions.
- Expanded fast verification with Ruff, basedpyright, Biome, Playwright discovery, focused contracts, and Git whitespace checks. Full verification reuses fast before full pytest and Playwright.
- Added CI scope detection for nested Agent files, `.ai/`, `.agents/`, `.codex/`, and `tasks/`.
- Re-audited eight cleanup candidates. Deleted no tracked files because repository-external compatibility evidence remains unavailable.
- Final measured instruction limits before archival: 76/100 root lines, 4,645/16 KiB root bytes, and 21,135/28 KiB combined bytes across 12 instruction files.
- Six Skill folders passed the official `quick_validate.py` check.
- Focused workflow tests passed: 21 tests.
- Fast verification passed.
- Full verification passed: 769 Python tests and 9 Playwright tests.
- The first full-verification attempt was interrupted by an incorrectly short outer command timeout and produced a Biome broken-pipe error; the complete rerun passed.
- No commit, push, pull request, deployment, production data change, or tracked-file deletion was performed.
