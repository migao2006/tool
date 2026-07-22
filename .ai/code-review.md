# Code Review and Safe Cleanup

## Review order

1. Confirm the request, inputs, outputs, time semantics, and affected boundary.
2. Check correctness, data leakage, permissions, secrets, RLS, error handling, and irreversible actions.
3. Check dependency direction, duplicate logic, public contracts, and backward compatibility.
4. Check failure, empty, stale, hard-fail, and unsupported-horizon coverage.
5. Check the diff, untracked files, generated output, accidental deletion, and documentation consistency.

Classify observations as `Confirmed defect`, `Risk`, or `Suggestion`, ordered by severity. A confirmed issue must include a path and useful location.

## Financial and data review

- `available_at <= decision_at` must be auditable; naive datetimes cannot enter alignment.
- Keep each decision-date cross-section within one fold and purge overlapping label entry/exit windows.
- Rank queries group complete date cross-sections, never symbols.
- Costs include both commissions, minimum fees, sell tax, spread, slippage, impact, and capacity.
- Hard failures cannot enter formal recommendations; research output cannot be presented as formal performance.

## Deletion evidence

Before deleting a tracked file, inspect applicable imports, text links, configuration, package scripts, commands, workflows, deployment settings, tests, migrations, schedules, runtime entry points, globs, directory scans, dynamic imports, naming conventions, Git history, and replacement behavior.

Delete only when reasonable evidence proves the file is no longer required. Retain uncertain, historical, protected, externally compatible, or dynamically loaded files and record the missing evidence and next check. Never use broad recursive deletion.

Protect entry points, migrations, schemas, lockfiles, legal/security files, production configuration, workflows, environment templates, model/data artifacts, provenance, historical decisions, completed tasks, and unresolved user work unless a verified replacement and explicit justification exist.

## Migration review

Treat table locks, `NOT NULL`, unique/foreign keys, type conversion, large backfill, RLS/Auth changes, and operations without safe rollback as high risk. Inspect migration history, isolated-environment results, backward compatibility, and rollback. Prefer additive expand-and-contract changes.

## Cleanup reporting

For each deletion record path, reason, reference checks, replacement, and validation. For each retained candidate record possible obsolescence, why deletion is unsafe, missing evidence, and the next check. Report actual file/directory deletion counts, `.gitignore` changes, and retained candidates.
