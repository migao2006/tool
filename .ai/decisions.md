# Stable Engineering Decisions

These cross-module decisions must not change during ordinary tasks. To replace one, first document impact, migration, rollback, and tests.

## Models and data

1. The rank model is the only stock-ordering source. Direction and quantiles are trading gates, market models control total exposure, and volatility models control risk and position size.
2. `final_score_model.py` must not return as another weighted formula; a compatibility layer may only call `decision_policy`.
3. The formal path is an after-market decision, entry at the next executable trading-day open, and exit at the close after h trading days.
4. Financials, revenue, events, and overseas markets align by actual `available_at`, never by reporting period.
5. Evaluate TWSE (上市), TPEx (上櫃), and ETF separately; ETF uses independent models and costs.
6. Separate training, calibration, test, and locked holdout by time; fit preprocessing inside each fold.

## Storage and publication

1. Store multi-year raw history as compressed Parquet in private Cloudflare R2; raw objects are immutable by default.
2. Supabase stores tasks, manifests, audit metadata, Auth, and UI summaries, not duplicate raw historical rows.
3. Data without verified point-in-time identity, calendar, corporate actions, and trading state remains `RAW_LANDING_ONLY / RESEARCH_ONLY`.
4. GitHub is the only manual release entry point; Vercel Production is triggered only by an approved GitHub flow.
5. Version Production migrations, validate them in isolation, and confirm rollback; use expand-and-contract for high-risk changes.

## Security and tools

- Use least project-level privilege. Never request organization owner, billing, or cross-project access for convenience.
- Confirm secret names, environments, and presence only; never read back or output values.
- Frontend code uses only publishable keys; personal tables use RLS with `auth.uid()` ownership.
- Use uv, Ruff, basedpyright, pytest, pnpm, Biome, and Playwright as configured. CLI availability never bypasses release gates.
- Use system CAs on Windows. Never set `strict-ssl=false` or disable TLS verification.

## Records

Current completion belongs in `docs/current-status.md` and model cards. Never delete historical decisions, completed tasks, or provenance because they appear old; add a clear superseded marker and pointer when facts change.
