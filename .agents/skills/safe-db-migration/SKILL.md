---
name: safe-db-migration
description: Plan, implement, or review a database migration with schema-history, compatibility, security, and rollback checks; do not operate on production without explicit approval.
---

# Safe Database Migration

1. Inspect current schema, migration history, RLS/Auth policies, consumers, and data volume.
2. Assess data loss, lock duration, backfill cost, backward compatibility, deployment order, and rollback.
3. Prefer additive and expand-and-contract migrations with versioned, reviewable SQL.
4. Validate migration, rollback, constraints, RLS, and affected contracts in an isolated environment.
5. Report evidence, residual risk, and the exact approval required before production.

Never weaken RLS, Auth, TLS, constraints, or audit controls to make a migration pass. Never modify production without explicit approval.
