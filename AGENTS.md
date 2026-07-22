# Repository Agent Rules

Keep architecture separated by responsibility. Splitting must reduce coupling and improve testability; do not create giant files or pass-through-only pseudo-layers.

## Scope and precedence

This repository builds a Taiwan equity 2-10 trading-day research system. The only formal product scope is the five-trading-day MVP, and model status remains `RESEARCH_ONLY` until all data and out-of-sample gates pass.

Apply rules in this order: safety and point-in-time correctness; the user's current request; product and architecture contracts; preservation of valid unrelated work; speed and convenience.

## Required reading order

Read only the minimum relevant material, in this order:

1. Root `AGENTS.md`.
2. `tasks/active/TASK.md`.
3. `.ai/product.md`.
4. `.ai/architecture.md`.
5. `.ai/decisions.md`.
6. Relevant code, tests, schemas, workflows, `.ai/known-issues.md`, and applicable Skills.

## Mandatory preflight

Before edits, run `git status --short --branch`, `git rev-parse --show-toplevel`, and `git diff --name-status`. Inspect relevant files and distinguish pre-existing changes from task changes. Do not read the entire repository by default.

## Single active task

Only `tasks/active/TASK.md` may represent active work. Follow `tasks/README.md`; archive completed tasks under `tasks/completed/` and never rewrite historical task records as current status.

## Project invariants

- Only `horizon=5` is formally supported; other values return `UNSUPPORTED_HORIZON`.
- ETF data stays separate from ordinary stock candidates and training data.
- The rank model is the only stock-ordering source; direction, quantile, market, and volatility outputs are gates or exposure controls only.
- `decision_policy` must not create a second weighted ranking.
- Enforce `available_at <= decision_at`; prevent look-ahead and survivorship bias.
- Never present fake data, placeholders, exact future prices, guaranteed returns, or unvalidated performance as real.
- A hard failure cannot produce a formal candidate. Formal output remains traceable to data, labels, features, costs, calibration, model, and Git versions.

## Change discipline

- Preserve valid behavior and unrelated user changes; make the smallest reversible change.
- UI must not contain model, SQL, R2, or database logic. External systems use clients, adapters, or repositories.
- Keep rank, direction, quantile, volatility, market, labels, decision, validation, and backtest modules separate.
- Avoid cycles, cross-layer shortcuts, duplicate shared logic, and cosmetic file fragmentation.
- Do not delete uncertain files. Apply the evidence rules in `.ai/code-review.md`.

## Testing and verification

Run focused tests, `python scripts/check_agents_length.py`, `git diff --check`, and the applicable fast/full verification. Report only commands actually run, including failures, skips, and environmental blockers. Inspect final status, untracked files, accidental deletions, generated output, and possible secrets.

Use versions pinned in `config/quality-tools.env`; Go and Deno are required for `just quality`, and missing required tools are blockers rather than skipped checks.

## Subagent policy

Without separate Git worktrees, only the primary agent may write. Subagents must use read-only roles from `.codex/agents/`, remain within delegated scope, return evidence-based summaries, and never expose secrets. Use delegation only when the user or an applicable instruction explicitly requests it.

## Security and approval boundaries

Never expose or commit secrets, tokens, passwords, private keys, or `service_role`; never disable TLS, RLS, Auth, or other controls. Without explicit task approval, do not commit, push, create or merge PRs, deploy, change production data/schema/settings, modify secrets/DNS/billing/branch protection, or perform destructive operations.

After local validation, proactively request approval to create a pull request; after CI passes, proactively request approval to merge it into `main` and then align any legacy local `main`. Each approval applies only to the named stage.

## Definition of done

The active task criteria are met; relevant verification has run; references resolve; no unrelated behavior changed; and known risks are reported. Until point-in-time, purged walk-forward, calibration, locked holdout, and full-cost backtest acceptance passes, status stays `RESEARCH_ONLY` or `FAIL`.

## Referenced documents

- Architecture: `.ai/architecture.md`
- Product: `.ai/product.md`
- Decisions: `.ai/decisions.md`
- Review and cleanup: `.ai/code-review.md`
- Known issues: `.ai/known-issues.md`
- Verification: `.agents/skills/repository-verification/SKILL.md`
- Current implementation status: `docs/current-status.md`, `model_card.md`

## Instruction size policy

Root `AGENTS.md` must remain at most 100 physical lines and 16 KiB; combined repository agent instructions must remain at most 28 KiB. Do not evade limits with hidden content, runtime generation, unreadable lines, or duplicated translations.
