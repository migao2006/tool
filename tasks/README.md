# Repository Work Package Workflow

This directory records one current Work Package and auditable terminal reports. It
does not override root `AGENTS.md`, the user's current request, or `.ai/` contracts.

## Responsibility boundaries

- `tasks/active/TASK.md`: exactly one actual current Work Package, or the canonical
  `NONE` state.
- `tasks/TASK_TEMPLATE.md`: a non-executable checklist with status `TEMPLATE`.
- `tasks/completed/`: immutable historical reports for terminal Work Packages.
- `.codex/CONTINUITY.md`: concise cross-session state, not authority or task history.

Do not create competing current-task, TODO, handoff, or per-subtask task files.

## Canonical no-task state

When no Work Package is active, `tasks/active/TASK.md` must contain exactly:

```text
# No active task
## Status
NONE
```

This state is not an executable task.

## Start one Work Package

1. Confirm the active file is in the canonical `NONE` state and preserve unrelated
   work.
2. Use `tasks/TASK_TEMPLATE.md` only as a checklist. Replace its generic title and
   `TEMPLATE` status; never copy an unfilled template into the active slot.
3. Set status to `ACTIVE` and populate every required section with actual task facts.
4. Keep one natural outcome across analysis, implementation, directly related fixes,
   validation, documentation, commits, a `codex/*` push, and Draft PR work.

An active task must include: Status, Authorization, Primary Outcome, Background,
Subtasks, Allowed Scope, Prohibited Changes, Public Contracts, Risk Classification,
Validation Plan, Stop Conditions, Definition of Done, and Results.

## Maintain task and continuity state

Record verified scope or outcome changes in the active task. Keep progress summaries,
branch state, decisions, passed validations, blockers, commits, and Draft PR
references in `.codex/CONTINUITY.md`. Do not paste command transcripts, full diffs,
or completed-task history there.

The continuity file should remain below 100 physical lines and 12 KiB. Replace stale
state instead of appending an activity log.

## Complete and archive

1. Set the task status to exactly `COMPLETE`, `PARTIAL`, or `BLOCKED`.
2. Fill Results with actual behavior, validation, repair, branch, commit, push, and
   Draft PR evidence; record failures and unexecuted checks truthfully.
3. Save the report as `tasks/completed/YYYY-MM-DD-kebab-case-outcome.md`.
4. Preserve existing completed reports. Historical `COMPLETED` spellings may remain;
   new reports use the three terminal statuses above.
5. Restore `tasks/active/TASK.md` to the canonical `NONE` state.
6. Update continuity to the latest concise handoff.

Task archival ends the Work Package record; it does not require a new Codex session.
