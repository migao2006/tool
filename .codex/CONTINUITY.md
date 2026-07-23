# Codex Continuity

This file is a concise cross-session handoff. It records state, not authorization,
and must not replace `tasks/active/TASK.md` or completed reports.

## Current Work Package

- Status: COMPLETE
- Outcome: Repository operating rules were refactored into a layered system.
- Record: `tasks/completed/2026-07-23-refactor-repository-operating-rules.md`.

## Current Branch

- `codex/refactor-repository-operating-rules`
- Based on `origin/main` at `a8b1cedb4cdfb96695d2fad42727b1cc6838a8b9`.

## Completed Work

- Separated stable root policy, actual task state, continuity, specialized rules,
  and historical reports.
- Made the empty Work Package template explicitly non-executable.
- Added contract coverage for autonomy, protected operations, task structure,
  continuity bounds, and references.
- Updated direct Skills and README navigation without product or workflow changes.

## Remaining Work

- GitHub-hosted PR checks and human review.
- Merge remains a separately authorized protected operation.

## Key Decisions

- `.ai/` remains authoritative for product, architecture, and stable decisions.
- Default autonomy ends at a `codex/*` push and Draft PR.
- Historical task wording remains unchanged as audit evidence.

## Validation Already Passed

- Focused governance suite: 27 passed.
- Ruff passed; basedpyright reported 0 errors and 0 warnings.
- Instruction limits, links, references, authority, scope, whitespace, and staged
  Gitleaks checks passed.
- Fast verification passed.
- Full verification passed: 989 Python and 65 Playwright tests.

## Known Issues or Blockers

- None for this Work Package.

## Commit and Draft PR References

- Core commit: `1e80fd837e662752682a3480148c778ddbfc572b`.
- Terminal task record is committed on this branch after the core commit.
- Draft PR #98: https://github.com/migao2006/tool/pull/98

## Maintenance

- Replace stale state at meaningful handoffs; do not append logs or full history.
- Keep this file under 100 physical lines and 12 KiB.
