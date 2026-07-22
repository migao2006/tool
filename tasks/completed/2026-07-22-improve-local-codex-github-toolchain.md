# Improve the Local Codex and GitHub Development Toolchain
## Status
COMPLETE
## Goal
Audit, install, integrate, and verify the approved Windows development tools without changing production systems or remote repository state.
## Confirmed Context
- The repository worktree contained pre-existing tracked and untracked changes, which were preserved.
- GitHub CLI, Git, winget, uv, Python, PowerShell, Node.js, pnpm, Docker, ripgrep, fd, and fzf were functional before installation.
- zoxide, just, act, and zizmor were initially missing.
- GitHub CLI supported user-scoped Agent Skills, and the official `cli/cli` gh Skill was not installed.
## In Scope
- Install only approved missing tools from confirmed official or trusted package sources.
- Add a thin root justfile, a non-destructive local tool audit script, and local tool documentation.
- Inspect local GitHub Actions with zizmor and act without running remote-write or production jobs.
- Read-only inspection of GitHub security configuration for recommendations.
## Out of Scope
- Product behavior, model logic, data pipelines, production systems, secrets, remote settings, deployments, commits, pushes, and pull requests.
## Constraints
- Preserve all pre-existing changes and do not reinstall functional tools.
- Do not disable TLS, expose secrets, elevate privileges, or run unsafe act jobs.
- Keep root AGENTS.md within its existing line and size limits.
## Execution Plan
1. Record baseline tool, repository, GitHub, and Docker state.
2. Install and verify approved missing tools and the official gh Skill.
3. Integrate repository command and audit interfaces plus documentation.
4. Audit workflow safety and GitHub security configuration read-only.
5. Run declared verification, record results, archive this task, and reset the active task.
## Validation Commands
- `pwsh -File scripts/check_local_tools.ps1`
- `just --list`, `just status`, `just agents`, `just diff`, `just tools`, and `just actions-list`
- `python scripts/check_agents_length.py`
- `zizmor .github` and `zizmor --pedantic .github`
- `act -l` and a dry-run of the allowlisted Python job
- `pwsh -File scripts/verify-fast.ps1`
- `pwsh -File scripts/verify-full.ps1`
- Final Git status, diff, stat, name-status, and whitespace inspection
## Definition of Done
- Every approved installed tool is verified by a real command and every skipped item has a reason.
- Repository wrappers call existing scripts and do not expose production or destructive operations.
- The tool audit script and documentation are accurate, non-secret, and Windows-safe.
- Workflow and GitHub security findings are reported without changing remote settings.
- No unrelated file is modified and no commit, push, PR, deployment, or production operation occurs.
## Results
- Installed the official `cli/cli` gh Skill for Codex at user scope, zizmor 1.28.0 with uv, just 1.57.0, act 0.2.89, and zoxide 0.10.0 with winget, and the maintained third-party gh-dash 4.25.2 extension.
- Preserved working ripgrep 15.1.0, fd 10.4.2, and fzf 0.74.1 installations.
- Added a guarded current-user PowerShell zoxide initialization without replacing an existing profile.
- Added `.actrc`, `justfile`, `scripts/check_local_tools.ps1`, and `docs/local-development-tools.md`; extended the repository verification Skill with the just interface.
- `act -l` passed. The first dry-run exposed the expected first-run image selector; after repository configuration, the safe Python job graph dry-run passed. No workflow job was actually executed.
- Regular zizmor audit produced 114 findings: 87 high, 10 medium, and 17 low. Pedantic mode produced 143 findings including 21 informational items. No automatic fixes were applied.
- Fast verification passed. Full verification passed with 769 Python tests and 9 Playwright tests.
- Root AGENTS.md remained at 76 physical lines and 4,645 bytes; combined Agent instructions measured 21,316 bytes.
- Read-only GitHub inspection confirmed secret scanning and push protection enabled, CodeQL default setup not configured, Dependabot security updates and vulnerability alerts disabled, and no branch ruleset or main branch protection.
- No secret, production workflow, production data, remote setting, commit, push, pull request, or deployment was created or modified.
