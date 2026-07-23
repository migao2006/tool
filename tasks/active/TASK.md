# Update Repository Authorization Rules
## Status
ACTIVE
## Authorization
FULL_AUTONOMY_UNTIL_MAIN_UPDATE
## Primary Outcome
Make the repository's Codex authorization rules consistently grant full Work Package
autonomy until an operation would update `main` or another protected branch.
## Background
The previous governance stopped autonomy at PR publication and separately protected
deployments, migrations, production workflows, release work, and secret access. The
user authorized a targeted policy update without redesigning the instruction system
or changing product code.
## Subtasks
1. Inventory direct authorization-policy sources and contract tests.
2. Update the root policy, task workflow/template, and directly related skills.
3. Add contract coverage for the new single protected-branch approval boundary.
4. Validate instruction limits, references, formatting, Fast, and required Full gates.
5. Archive this task, commit, push the feature branch, and create or update a PR.
## Allowed Scope
`AGENTS.md`, `.agents/skills/implement-feature/SKILL.md`,
`.agents/skills/repository-verification/SKILL.md`,
`.agents/skills/safe-db-migration/SKILL.md`, `.codex/CONTINUITY.md`,
`tasks/README.md`, `tasks/TASK_TEMPLATE.md`, `tasks/active/TASK.md`,
one completed task record, and `tests/test_codex_workflow_contract.py`.
## Prohibited Changes
Do not change product code, product contracts, dependencies, workflows, migrations,
runtime or production resources, unrelated documentation, or historical completed
task reports. Never force-push, use destructive Git cleanup, expose a secret, merge
the PR, or otherwise update a protected branch.
## Public Contracts
No product, API, schema, data, model, ranking, horizon, market, instrument, frontend,
point-in-time, fail-closed, or `RESEARCH_ONLY` contract changes are authorized.
## Risk Classification
MEDIUM. This changes future agent authority and safety boundaries but not executable
product behavior, workflow code, schema, dependencies, or infrastructure.
## Validation Plan
Run targeted repository searches; the focused governance contract tests; instruction
length, Markdown/reference, lint, type, and secret checks applicable through canonical
repository commands; `git diff --check`; Fast verification; policy-required Full
verification; and an independent final diff review.
## Stop Conditions
Stop for unresolved policy contradictions, secret exposure, an unrelated subsystem,
an unisolated user change, an external validation blocker, or immediately before any
operation that would update `main` or another protected branch.
## Definition of Done
The new authorization name and single final approval boundary are consistent; safety,
validation, public contracts, and secret non-disclosure remain intact; applicable
checks pass; the task is archived; the active file returns to `NONE`; changes are
committed and pushed on `codex/update-main-authorization-policy`; a PR is ready; and
no protected branch is updated.
## Results
In progress.
