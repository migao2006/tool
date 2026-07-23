# Codex Continuity

This file is a concise cross-session handoff. It records state, not authorization,
and must not replace `tasks/active/TASK.md` or completed reports.

## Current Work Package

- Status: ACTIVE
- Outcome: Add persistent failure/misalignment reporting and bounded,
  current-main-only automatic recovery for daily import and research pipelines.
- Record: `tasks/active/TASK.md`.

## Current Branch

- `codex/add-daily-pipeline-recovery`
- Authoritative base: merged `origin/main` at
  `35bc3560359ebbcac85520b93a3120f4a630ca08`.

## Verified Production State

- PR #100 is merged at `35bc356`; Project tests, Vercel Production, GitHub
  Pages, and Edge CORS deployments passed.
- Scheduled old-SHA Daily run `30020254516` built both feature markets. TWSE
  Staging passed; TPEx correctly failed closed because old model run 14 was
  superseded by newer Staging run 15; Production was skipped.
- Current-main Daily run `30021481019` started automatically after the old
  concurrency holder completed and is under active observation.
- Production API remains on validated `2026-07-17` until a complete
  current-main Production publication passes.

## Completed Work

- Original stale-snapshot root cause is fixed and merged through PR #100.
- Read-only audit proved import mismatch currently retries four times in one job
  but has no persistent issue or workflow-level recovery.
- Official GitHub behavior was verified: full rerun uses Actions write,
  `run_attempt` increments, v4 artifacts are immutable, and a privileged
  `workflow_run` controller must not execute untrusted code/artifacts.
- Workflow audit found partial failed-job reruns unsafe for the current
  cross-job artifact DAG; full rerun with attempt-qualified names is required.

## Remaining Work

- Finish current-main Production Daily Research and API/page verification.
- Implement and test sanitized reports, trust/current-head guards, Issue
  deduplication, bounded full reruns, and attempt-qualified artifacts.
- Complete Fast/Full verification and independent review.
- Commit, push, open a PR, wait for green CI, then stop before updating `main`.

## Key Decisions

- Retry only the exact trusted workflows at the current default-branch SHA.
- Treat an old-SHA failure as superseded: report it, never rerun it.
- Use full workflow reruns, bounded attempts, and one immutable artifact
  generation per `run_attempt`; never overwrite or mix prior-attempt evidence.
- Preserve all point-in-time, venue/asset, horizon, ranking, and fail-closed
  contracts.

## Validation Already Passed

- Pre-implementation repository status and authoritative main SHA verified.
- Official recovery API, permission, attempt, artifact, and security semantics
  verified from GitHub documentation.
- Read-only workflow/retry architecture audit completed.

## Known Issues or Blockers

- Live 2026-07-23 sources remain misaligned: TPEx reports `2026-07-23`, TWSE
  reports `2026-07-22`; this is not a valid joint snapshot and must not publish.
- No implementation blocker.

## Commit and Pull Request References

- Base: `35bc3560359ebbcac85520b93a3120f4a630ca08`.
- Original Bug PR: https://github.com/migao2006/tool/pull/100
- Misaligned import: https://github.com/migao2006/tool/actions/runs/30010235104
- Superseded old-SHA Daily run:
  https://github.com/migao2006/tool/actions/runs/30020254516
- Current-main Daily run:
  https://github.com/migao2006/tool/actions/runs/30021481019

## Maintenance

- Replace stale state at meaningful handoffs; do not append logs or full history.
- Keep this file under 100 physical lines and 12 KiB.
