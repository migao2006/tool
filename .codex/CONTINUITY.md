# Codex Continuity

This file is a concise cross-session handoff. It records state, not authorization,
and must not replace `tasks/active/TASK.md` or completed reports.

## Current Work Package

- Status: ACTIVE.
- Outcome: repair Manual full update Production artifact handoff.
- Active record: `tasks/active/TASK.md`.
- Authorization: `FULL_AUTONOMY_UNTIL_MAIN_UPDATE`; protected branches remain
  unchanged.

## Current Branch

- Branch: `codex/repair-manual-update-artifacts`.
- Base: `main` at `47eceb1d7de5f42e0bd70668a3d025fcc4bf24c4`.
- Commit and Pull Request: pending.

## Completed Work

- Main run `30061633611` requested `dry_run=true` and
  `publish_production=false`; Production jobs correctly did not upload artifacts.
- Final summary nevertheless unconditionally attempted both Production downloads,
  producing the two reported `Artifact not found` errors.
- `workflow_call` artifacts use caller run ID/attempt; Import and resolution
  artifacts in the same run prove cross-workflow access and naming are correct.
- Daily reusable outputs now expose resolver/publication intent. Manual summary
  downloads only required market artifacts while preserving missing-required-
  artifact failure and strict evidence validation.

## Key Decisions

- Expose resolver and publication intent through backward-compatible reusable
  workflow outputs instead of changing artifact names or weakening validation.
- Skip only artifacts that the called workflow contract says cannot exist.

## Validation Already Passed

- Focused affected workflow, recovery, and summary tests: 95 passed.
- Quality/security: passed; Ruff, basedpyright, actionlint, Deno, secret and
  dependency checks all passed.
- Fast: passed.
- Full: passed with 1,115 Python and 66 Playwright tests.
- Independent read-only review: zero findings.
- `git diff --check`: passed.

## Remaining Work

- Commit and push the feature branch.
- Create/update the Pull Request, wait for CI green, then archive the task and
  restore `tasks/active/TASK.md` to `NONE`.
- Do not update `main` without additional authorization.

## Public Contracts

- Horizon 5, aligned-date resolution, fail-closed Production validation,
  deterministic artifacts, TWSE/TPEx isolation, `RESEARCH_ONLY`, and `HARD_FAIL`
  semantics are unchanged.

## Known Issues or Blockers

- No implementation blocker.
- Live verification of the repaired Manual workflow requires the change on
  `main`, because preflight intentionally rejects feature branches.

## Commit and Pull Request References

- Failure evidence: https://github.com/migao2006/tool/actions/runs/30061633611
- Feature commit and Pull Request: pending.

## Maintenance

- Replace stale state at meaningful handoffs; do not append logs or full history.
- Keep this file under 100 physical lines and 12 KiB.
