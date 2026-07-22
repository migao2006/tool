# Repository Task Workflow

The task system gives Codex one explicit source of truth for the current repository change. It supplements, but never overrides, `AGENTS.md`, `.ai/` contracts, or the user's current request.

## Single active task

Only `tasks/active/TASK.md` may represent active work. Do not create competing files such as `current-task.md`, `todo-now.md`, or numbered active task files.

## Start a task

1. Confirm that `tasks/active/TASK.md` has status `NONE`.
2. Copy the structure from `tasks/TASK_TEMPLATE.md` into `tasks/active/TASK.md`.
3. Record verified context, scope, constraints, exact validation commands, and objective completion criteria.
4. Keep the active task narrower than the repository-wide rules in `AGENTS.md` and the contracts in `.ai/`.

## Complete and archive a task

1. Run the declared validation and record actual results, including failures or skipped commands.
2. Complete the `Results` section without inventing outcomes.
3. Move the completed content to `tasks/completed/YYYY-MM-DD-kebab-case-title.md`.
4. Preserve historical completed tasks; do not rewrite them to match current status.
5. Reset `tasks/active/TASK.md` to the standard `No active task` state.

Completed task names use an ISO date followed by a concise kebab-case outcome. Existing reports remain in place unless their references and historical purpose make a move demonstrably safe.
