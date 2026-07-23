---
name: implement-feature
description: Implement a scoped repository feature after its outcome and contracts are defined; do not use for diagnosis-only requests, broad cleanup, or production operations.
---

# Implement Feature

Follow the complete Work Package lifecycle in root `AGENTS.md`; this Skill narrows the
implementation phase and does not grant additional authority.

1. Read `tasks/active/TASK.md`, continuity, and relevant product and architecture
   contracts.
2. Find the smallest coherent implementation boundary and confirm API, schema,
   model, and UI contracts.
3. Preserve unrelated changes and characterize behavior that must remain stable.
4. Implement the outcome, migrate direct callers, and add or update tests.
5. Run focused checks during development, then the repository's required Fast, Full,
   and independent review gates.
6. Continue through task/continuity updates, focused commits, an authorized
   `codex/*` push, and Draft PR creation; do not stop merely because code is complete.
7. Report contract impact, compatibility evidence, rollback, validation, and risks.

Never use this Skill for a protected operation or to broaden the active Work Package.
