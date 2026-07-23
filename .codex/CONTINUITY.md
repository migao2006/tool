# Codex Continuity

This file is a concise cross-session handoff. It records state, not authorization,
and must not replace `tasks/active/TASK.md` or completed reports.

## Current Work Package

- Status: ACTIVE
- Outcome: Refactor repository operating rules into a concise layered system.

## Current Branch

- `codex/refactor-repository-operating-rules`
- Based on `origin/main` at `a8b1cedb4cdfb96695d2fad42727b1cc6838a8b9`.

## Completed Work

- Verified the repository root, clean starting tree, base SHA, and GitHub CLI access.
- Inventoried root rules, task files, repository Skills, Codex configuration,
  governance tests, verification scripts, CI scope selection, and direct references.
- Confirmed executable policy enforcement makes this a HIGH-risk governance change.
- Refactored stable policy, task/template boundaries, continuity, direct Skills,
  README navigation, and governance contract coverage without product-code changes.
- Completed independent diff, authority, safety-boundary, and reference review.

## Remaining Work

- Create and push the focused implementation commit, then open the Draft PR.
- Archive the task, restore active state to `NONE`, and push the record-only commit.

## Key Decisions

- Keep `.ai/` as the authoritative product, architecture, and decision layer.
- Keep existing specialized Skills; align only those directly governing this flow.
- Add no speculative policy directory and make no product-code or workflow change.

## Validation Already Passed

- Instruction limits: 98/100 root lines, 6,882/16 KiB root, 24,343/28 KiB combined.
- Focused governance suite: 27 passed.
- Ruff: passed; basedpyright: 0 errors and 0 warnings.
- Markdown-link, live-reference, authority, and `git diff --check` audits: passed.
- Fast verification: passed.
- Full verification: 989 Python and 65 Playwright tests passed.

## Known Issues or Blockers

- None.

## Commit and Draft PR References

- No Work Package commit or Draft PR exists yet.

## Maintenance

- Replace stale state at meaningful handoffs; do not append logs or full history.
- Keep this file under 100 physical lines and 12 KiB.
