# Repository Agent Rules

Build the Taiwan equity research system in coherent, reviewable units. Preserve point-in-time correctness, fail-closed behavior, public contracts, and user work. Split only to reduce coupling and improve testability.

## Instruction precedence

Apply, in order: safety and protected-branch limits; the user's request and explicit authorization; the nearest `AGENTS.md`; the active Work Package; `.ai/` contracts; continuity state. Nested Agent files add
local rules and cannot weaken higher constraints. Continuity records state only and grants no authority.

## Work Package and task model

A Work Package is one natural, complete outcome. It may include analysis, characterization, implementation,
caller migration, related fixes, tests, verification, documentation, focused commits, a `codex/*` push, and
Pull Request readiness. Do not stop after a subtask unless a stop condition is reached. Before edits, create
one populated `tasks/active/TASK.md` with status `ACTIVE`. An empty prompt, placeholder, example, or
`tasks/TASK_TEMPLATE.md` is not executable. Never create one active task per subtask.

## Default Work Package authorization

Unless the user gives narrower authorization, an actual Work Package has `FULL_AUTONOMY_UNTIL_MAIN_UPDATE`
authority. Without repeated approval, inspect the repository; change in-scope code, callers, tests, fixtures,
docs, and related CI; fix related defects; install or synchronize dependencies; use local Docker or isolated
services; verify; change migrations, schemas, workflows, deployment configuration, and infrastructure; use
existing task-required secrets without displaying or leaking them; run Preview, Staging, or Production
workflows, migrations and deployments and verify their outcomes; prepare releases; update task/continuity; commit; push non-protected feature
branches, normally `codex/*`; and create, update, or mark Pull Requests ready.

## Final protected-branch authorization

The only operation that requires additional user authorization is one that updates `main` or another
protected branch: a direct push, Pull Request merge or auto-merge, rebase, fast-forward, or other protected
reference change. Immediately before it, report the protected branch, commit or Pull Request, validation and
CI results, deployment and migration status, known risks, and rollback procedure, then ask once. Never force-push or
arrange an asynchronous protected-branch update without that final authorization.

## Context, evidence, and scope

Start with applicable instructions, the active task, continuity, relevant contracts, public entry points,
existing tests, and direct callers. Verify references with repository search and expand scope only when
evidence requires it. Avoid broad exploration, rereading unchanged files, and loading generated artifacts
or large logs. Separate confirmed facts, evidence-based inference, and unresolved uncertainty.
Before edits verify repository root, branch, worktree status, and diff; isolate unrelated changes. Without
an isolated worktree only the primary agent writes. Use read-only subagents only when explicitly requested.
Keep one primary component or tightly connected data flow. Fix related problems autonomously only when they
preserve public contracts unless the active Work Package explicitly changes them, avoid protected-branch
updates, prefer reversible and minimal-impact operations, remain verifiable, and are necessary for the outcome or confidence. Do not combine another major
feature or unrelated cleanup. File and line counts are review indicators, not excuses to leave a coherent
outcome incomplete; explain and organize large diffs, run Full verification, and obtain independent review.

## Validation and repair

Validate in layers: focused affected tests; relevant lint and type checks; `git diff --check`; Fast
verification; risk- or scope-required Full verification; then independent final review. Full is required
for shared contracts, data or point-in-time logic, models, decision policy, authentication, schema or
migrations, release paths, multiple caller migrations, executable governance changes, and Pull Request
readiness. Run `python scripts/check_agents_length.py` for instruction changes. Go and Deno are required
for `just quality`; missing required tools are blockers.
Never claim an unexecuted check passed or behavioral equivalence without checkable evidence. Do not rerun
an expensive successful suite after a later change that cannot affect its coverage. On failure, identify
the first actionable cause, make the smallest justified repair, and rerun the smallest affected check.
Stop and report `PARTIAL` or `BLOCKED` after three materially different failed attempts at one root cause.
Never delete valid tests, weaken assertions without contract evidence, add broad ignores or skips, swallow
errors, fabricate data, or lower quality gates.

## Git and Pull Request policy

Preserve and isolate unrelated changes. Use explicit-path staging; never use `git add .`, `git add -A`, or
`git commit -am`. Never force-push, update a protected branch without final authorization, run
`git reset --hard` or `git clean -fd`, or discard unrelated work. Before commit, require applicable
validation and `git diff --check` to pass, no secrets or unexplained behavior difference, and accurate
task/documentation state. Pull Requests must state outcome, contract impact, validation,
deployment/migration results, limitations, risks, and that no protected branch was updated.

## Tasks, continuity, and sessions

Follow `tasks/README.md`. Archive only terminal `COMPLETE`, `PARTIAL`, or `BLOCKED` tasks under
`tasks/completed/`, then restore the active file to its exact `NONE` state. Keep
`.codex/CONTINUITY.md` concise and current; do not copy logs or task history into it. Archival does not
require a new session. Continue the same session for the same Work Package; use a new one for a separate
package or genuinely independent review.

## Stop conditions and definition of done

Stop when completion requires an unauthorized contract change, an actual protected-branch update, unrelated
major subsystem, unresolved destructive action, unsafe mixing of user changes, unavailable external
validation, or a material unexplained behavior difference. Also stop for a confirmed security leak,
look-ahead bias, or survivorship bias. Do not stop for reversible local design choices or in-scope repair.
Complete the primary outcome and direct callers; preserve contracts; pass required validation; resolve
independent-review findings; update task, continuity, and direct documentation; commit and push the `codex/*`
branch; take the Pull Request through readiness; stop immediately before a protected-branch update; and
report exact results, failures, branch/commit/PR state, deployment/migration status, risks, and rollback.
Secret values must never be printed in output, records, documentation, commits, Pull Requests, or reports. Product
status is governed by authoritative contracts.

## References and instruction size

Product/display: `.ai/product.md`; architecture: `.ai/architecture.md`; decisions: `.ai/decisions.md`; review: `.ai/code-review.md`; known issues: `.ai/known-issues.md`; tasks: `tasks/README.md`; verification:
`.agents/skills/repository-verification/SKILL.md`; current evidence: `docs/current-status.md`, `model_card.md`.
Root `AGENTS.md` stays within 100 lines and 16 KiB; all agent instructions stay within 28 KiB. Never evade
limits with hidden, generated, unreadable, translated, or duplicated content.
