# Update Main Authorization Policy
## Status
COMPLETE
## Authorization
FULL_AUTONOMY_UNTIL_MAIN_UPDATE
## Primary Outcome
The repository now grants complete in-scope Work Package autonomy until an operation
would update `main` or another protected branch. The layered instruction architecture
and all product contracts remain unchanged.
## Scope and Changes
- Replaced the prior default authorization in root `AGENTS.md`.
- Authorized dependencies, local services, CI fixes, migrations, deployments,
  production workflows, release preparation, feature pushes, and PR readiness without
  repeated approval.
- Retained one final authorization for direct push, merge/auto-merge, rebase,
  fast-forward, or another protected reference update.
- Required the final handoff to report target branch, commit/PR, validation and CI,
  deployment/migration state, risks, and rollback.
- Preserved no-force-push, no destructive Git cleanup, secret non-disclosure, scope,
  reversibility, validation, repair, and public-contract rules.
- Updated the task workflow/template and the implementation, migration, and repository
  verification Skills without modifying product or workflow code.
- Added governance regression coverage for the new authority and safety boundary.
## Changed Paths
The final PR changes only governance and its contract test:
- `AGENTS.md`
- `.agents/skills/implement-feature/SKILL.md`
- `.agents/skills/repository-verification/SKILL.md`
- `.agents/skills/safe-db-migration/SKILL.md`
- `.codex/CONTINUITY.md`
- `tasks/README.md`
- `tasks/TASK_TEMPLATE.md`
- this completed report
- `tests/test_codex_workflow_contract.py`
## Contract Impact
No product, API, persisted schema, data, model, ranking, horizon, point-in-time,
market, instrument, frontend, fail-closed, or `RESEARCH_ONLY` contract changed.
Historical completed reports retain their original wording as immutable evidence;
negative tests mention the retired name only to prevent its return.
## Validation
- Expected pre-policy regression evidence: 2 focused assertions failed against the
  old authority.
- Focused governance contracts: 11 passed.
- Final governance/state subset: 28 passed.
- Ruff: passed.
- basedpyright: 0 errors, 0 warnings.
- Agent instruction limits: root 100/100 lines; root and combined size passed.
- `just agents`: passed after loading registered user/machine tool paths.
- `git diff --check`: passed.
- Core changed-file Gitleaks scan: passed for 9 files.
- Fast verification: 17 passed.
- Full verification: 990 Python and 65 Playwright tests passed.
- GitHub Project tests for core commit `3d0f398698b871af218663ad9c0ffbd0aa24e958`
  passed; frontend/browser scope was legitimately skipped.
## Repair Rounds
Three focused repair rounds were used:
1. Replaced one overbroad test assertion that incorrectly rejected the required
   protected-branch final-authorization sentence.
2. Reduced root `AGENTS.md` from 105 to the enforced 100-line limit without removing
   policy requirements.
3. Investigated one transient WebKit/iPhone-13 viewport failure. The screenshot showed
   the navigation inside the viewport; the isolated test passed, and the subsequent
   unchanged Full run passed all 65 Playwright tests.
## Git and Pull Request
- Branch: `codex/update-main-authorization-policy`.
- Base `origin/main`: `7a7e431f4086eabbe458a4ad244c940ec8cac9ae`.
- Core commit: `3d0f398698b871af218663ad9c0ffbd0aa24e958`
  (`docs(governance): update main authorization policy`).
- The core commit was pushed to the non-protected feature branch.
- PR #99: https://github.com/migao2006/tool/pull/99
- PR #99 was marked Ready for review after its core checks passed.
- This terminal task record and the canonical active `NONE` state are committed after
  the core commit.
## Deployment and Migration Status
The existing Vercel Git integration automatically produced a successful Preview for
the feature branch. No manual deployment, migration, production workflow, release,
production-resource change, or secret operation was required or performed.
## Rollback
Before merge, close PR #99 or revert the feature-branch commits. No database,
infrastructure, production, or protected-branch rollback is required because none was
changed by this Work Package.
## Results
The requested policy is implemented, locally and remotely validated, pushed, and
ready for human review. No protected branch was updated. The only remaining approval
boundary is the operation that would update `main` or another protected branch.
