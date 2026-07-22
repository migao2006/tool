# Enforce Deno Line Endings and Approval Handoffs
## Status
COMPLETED
## Goal
Keep Deno Edge Function sources on LF checkouts and make remote Git handoff approvals proactive.
## Confirmed Context
- Deno 2.8.1 reported 23 files under `supabase/functions/prediction-snapshot/` as differing only by line endings.
- The Git index stored LF while the Windows worktree used CRLF because no matching attribute existed.
- The user requested proactive approval prompts before PR creation, main merge, and legacy-main alignment.
## In Scope
- `.gitattributes`, repository agent approval rules, focused contract tests, and task records.
## Out of Scope
- Product behavior, model logic, deployment, production data, secrets, or remote Git operations.
## Constraints
- Preserve existing behavior and unrelated files; do not commit, push, create a PR, or merge without separate explicit approval.
## Execution Plan
1. Add failing repository contracts for LF attributes and proactive approval handoffs.
2. Add the smallest scoped attributes and agent-rule update.
3. Normalize the affected working-tree files and verify Deno quality checks.
4. Run repository verification, inspect the diff, archive this task, and reset the active slot.
## Validation Commands
- `uv run --system-certs pytest tests/test_repository_line_endings.py tests/test_codex_workflow_contract.py -q`
- `deno fmt --check`
- `deno task check`
- `deno lint`
- `deno task test`
- `just quality`
- `just fast`
- `python scripts/check_agents_length.py`
- `git diff --check`
## Definition of Done
- Deno-formatted TypeScript, Deno JSON, and scoped Markdown check out as LF.
- The repository directs agents to request approval proactively at each remote handoff.
- Focused and fast verification pass without unrelated changes.
## Results
- Added scoped LF attributes for Supabase Edge Function TypeScript, `deno.json`, and README files.
- Added regression coverage for Git attributes and the proactive approval handoff rule; six focused tests passed after first proving both contracts failed.
- Normalized all 23 `prediction-snapshot` files to LF without logical source changes.
- Deno format, type check, lint, and 47 tests passed.
- Fast verification passed with 17 focused tests. Agent instructions remain within all limits and `git diff --check` passed.
- `just quality` passed all checks through Deno, then stopped because the required `go` executable is not installed; no quality failure was hidden.
- No commit, push, PR, merge, deployment, production data, or remote setting change was performed.
