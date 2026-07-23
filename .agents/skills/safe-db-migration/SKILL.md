---
name: safe-db-migration
description: Plan, implement, execute, or review an in-scope database migration with schema-history, compatibility, security, production verification, and rollback checks.
---

# Safe Database Migration

1. Inspect current schema, migration history, RLS/Auth policies, consumers, and data volume.
2. Assess data loss, lock duration, backfill cost, backward compatibility, deployment order, and rollback.
3. Prefer additive and expand-and-contract migrations with versioned, reviewable SQL.
4. Validate migration, rollback, constraints, RLS, and affected contracts in an isolated environment.
5. When required by the active Work Package, apply staged or production migrations,
   verify postconditions, and preserve a tested rollback or recovery procedure.
6. Report evidence, deployment state, residual risk, and the protected-branch handoff.

Use `FULL_AUTONOMY_UNTIL_MAIN_UPDATE` from root `AGENTS.md`. Never weaken RLS, Auth,
TLS, constraints, or audit controls, expose secret values, or run an irreversible
destructive migration without verified recovery and active-task justification.
