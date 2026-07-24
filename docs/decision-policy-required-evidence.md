# Decision Policy required-evidence matrix

Status: investigated against `main` at
`e2ba3f54e6086082b72775a326a5fef2f54b43fb` and read-only Production on
2026-07-24.

This document covers the three evidence categories that are required by the
horizon-5 Decision Policy but are not produced by the ranking model. It does
not authorize a fallback, default, present-day reconstruction, or cross-market
substitution. An unusable category remains `MISSING_REQUIRED_DATA` with
`action=null`.

## Evidence matrix

| Category | Authoritative source | Existing producer and storage | Existing consumer | Effective-date and availability semantics | Scope and history | Production finding and first root cause |
| --- | --- | --- | --- | --- | --- | --- |
| Tradability | Venue-published TWSE or TPEx security state for the exact session. TWSE describes the changed-trading-method dataset as a daily security/trading-method product and its rules require advance collection of funds or securities for changed-trading-method securities. TPEx publishes its own changed-trading and suspension state. | `SecuritySnapshotImporter` fetches separate MOPS, TWSE, and TPEx profile/restriction/suspension/attention/disposal payloads and writes one-day `market_data.security_history` `CURRENT_DAILY_SNAPSHOT` rows with the actual `available_at`, source ID/version, and revision hash. `market_data.historical_security_state_snapshots` is the immutable historical-manifest contract, but Production has no rows. | `DecisionPolicy` accepts a Boolean `tradable`; `TwseDailyResearchInference` never resolves `security_history` or supplies it. Gate attachments and the API therefore contain `FORMAL_TRADABILITY_INPUT_MISSING`. | Formal use requires an exact effective session, a venue match, a complete security-state field set, and `available_at <= decision_at`. A later observation is post-decision evidence and cannot be moved backward. A null state flag makes the evidence incomplete. | TWSE and TPEx are separate. Current snapshots are observations only and cannot be used as historical backfill. The historical manifest table is empty in Production. | Production has only a 2026-07-18 current snapshot, retrieved 2026-07-19, and no exact 2026-07-23 row. The scheduled importer has failed since 2026-07-20 because `resolve_coherent_profile_date` requires the two venue profile dates to match, so one lagging venue blocks both. Even a successful late-evening observation is after the 17:00 policy decision and must not be used for that decision. The current normalizer also leaves `full_cash_delivery_flag` null, so its rows are not yet complete formal evidence. The data exists only as partial, late evidence and was also dropped at the inference boundary. |
| Market exposure | A venue-specific, versioned market-model publication calculated only from decision-time-observable benchmark and breadth inputs. It must contain calibrated direction probabilities, regime, forecast market volatility, exposure cap, model version, training end date, effective date, and actual publication time. | The repository has `MarketDirectionModel`, `classify_market_regime`, `market_exposure_cap`, the public `MarketOutput` contract, and `market_data.market_predictions`. It has no training bundle, exact-date producer, or research publisher path that inserts a market prediction. | `DecisionPolicy` accepts `market_exposure_cap`; stock/API serializers already have nullable market fields, and the Edge function reads `market_predictions`. Daily inference never supplies a cap and the atomic research publisher never writes a market row. | The model artifact and all source inputs must have existed by `decision_at`; the publication must be for the exact venue, horizon, and effective session. A cap of zero is valid evidence and is an evaluated failing gate. Missing, stale, future, cross-venue, or unversioned output is not a defaultable cap. | TWSE and TPEx require separate benchmark/model publications. No historical market-prediction publication exists in Production. | `market_predictions` has zero Production rows. Components and consumers exist, but an authoritative producer and a publisher transport were never implemented. No trustworthy current or historical value is obtainable from the repository state. |
| Position limits | A versioned portfolio-policy publication plus the point-in-time portfolio/allocation state used to test the proposed security allocation. It must identify portfolio equity/state, proposed and resulting weights, industry assignment, liquidity participation, applicable limits, policy version, and publication time. | `config/five_day_mvp.toml` contains unversioned limit parameters and `allocate_inverse_volatility` can calculate weights when portfolio equity, forecast volatility, ADV, industry, market exposure, and candidates are supplied. There is no position/allocation evidence table, portfolio-state producer, or publication artifact. | `DecisionPolicy` accepts only an opaque Boolean `position_limits_pass`. Daily inference always supplies `None`; the Edge mapper always emits null maximum-single and maximum-industry fields. | Limits and portfolio state must be effective for the exact decision, available by `decision_at`, and tied to the proposed allocation. Configuration constants alone cannot establish that a row passed. A missing holding, equity, volatility, industry, turnover, or policy identity keeps the category missing. | Portfolio state and limits must be venue-scoped where applied; no TWSE/TPEx fallback is permitted. There is no historical point-in-time position evidence in Production. | The necessary evidence was never produced. Treating config defaults, a zero position, current holdings, or inferred volatility as a pass would manufacture evidence, so the category must remain explicitly missing until a real producer exists. |

Authoritative venue references:

- [TWSE changed-trading-method data product](https://eshop.twse.com.tw/zh/product/detail/036982f02fbb4d1a805024d5e72d7e17)
- [TWSE changed-trading-method rule](https://twse-regulation.twse.com.tw/TW/law/DAT0201.aspx?FLCODE=FL007123)
- [TWSE investor explanation of full-delivery securities](https://investoredu.twse.com.tw/pages/TWSE_InvestmentRisk6_1.aspx)
- [TPEx changed-trading-method securities](https://www.tpex.org.tw/web/stock/aftertrading/cmode/chtm.php?l=zh-tw)

## Required rejection and missing-data semantics

- `AVAILABLE` evidence must carry a source, venue, security identity when
  security-specific, exact effective date, timezone-aware `available_at`,
  publication identity, validation result, and the category-specific value and
  parameters.
- Evidence observed after `decision_at`, effective for a different session,
  resolved through a different venue, or attached to a different symbol is not
  usable.
- A structurally malformed or mixed-market evidence artifact is rejected as a
  whole. It is never partially trusted.
- An expected record that is absent, incomplete, stale, or post-decision is
  represented with an explicit missing reason and supplies no policy value.
- `market_exposure_cap=0` and `tradable=false` are valid values when supported
  by complete evidence. They cause an evaluated non-hard gate failure; they are
  not missing.
- Only a row with all required evidence and all existing policy inputs may
  become `EVALUATED`. Any non-`EVALUATED` row keeps `action=null`.

## Read-only Production baseline

For the latest TWSE horizon-5 run on 2026-07-23:

- policy-universe rows: 1,067
- `MISSING_REQUIRED_DATA`: 1,067
- `EVALUATED`, `VALIDATION_FAILED`, and `HARD_FAIL`: 0
- non-null actions: 0
- `market_predictions`: 0
- exact-date tradability snapshots: 0
- historical security-state manifests: 0
- `system_status`: `RESEARCH_ONLY`

TPEx is isolated in a separate 854-row run. Horizon 2 returns
`UNSUPPORTED_HORIZON`.

These counts are the comparison baseline. Candidate count is not a success
criterion.

## Implemented fail-closed path

The repository now defines `decision-policy-required-evidence.v1` as an immutable,
hashed artifact contract. Every record is either `AVAILABLE` or `MISSING` and
carries, where applicable, source, venue, security identity, exact effective date,
timezone-aware `available_at`, publication identity, validation result, reason,
and category-specific details.

The daily research workflow downloads the exact feature artifact first and uses its
historical `security_id` universe to export evidence. It never queries the current
security master to reconstruct historical membership. The same artifact is passed
to Staging inference and the byte-identical, Staging-verified snapshot is the only
object eligible for Production republication.

The category transport is:

| Category | Producer/normalizer | Formal transport and consumer |
| --- | --- | --- |
| Tradability | `SecuritySnapshotImporter` and `export_decision_policy_evidence` select only an exact-date `CURRENT_DAILY_SNAPSHOT` with a complete state, active authoritative source, and pre-decision availability. | The evidence artifact supplies the Boolean only after contract validation. The adapter attaches the complete evidence record to `tradability_gate`; Python, Edge, and frontend validators independently recheck it. |
| Market exposure | `export_decision_policy_evidence` selects an exact market/horizon run and `market_predictions` row only when both run and row existed by `decision_at` and the model publication is complete. | The publisher derives one canonical market row only when all evaluated stock rows carry the same available market evidence. The additive three-argument RPC persists that row atomically with the run and stocks. |
| Position limits | No authoritative producer currently exists. The exporter emits one explicit `POSITION_LIMIT_PRODUCER_UNAVAILABLE` record per exact feature-universe security. | The adapter supplies no Boolean and the public API exposes no position limit from missing evidence. A future available record must contain the versioned portfolio policy/state and all proposed/resulting limit measurements before it can be used. |

Direct raw `tradable`, `market_exposure_cap`, or `position_limits_pass` values are
not formal inputs. They are ignored unless backed by the matching, validated
`AVAILABLE` evidence record. An evaluated row must have all three required evidence
records, exact gate/source dates, matching venue and symbol, matching actual value,
and `available_at <= decision_at`; otherwise publication or public serialization is
rejected.

The gate envelope is versioned and backward-readable. Missing records remain
attached for audit but cannot populate public position-limit or market fields.
`RESEARCH_ONLY` no longer suppresses a valid policy action: it is a system-status
boundary. Thus a synthetic contract fixture with all real-shaped valid evidence can
exercise `EVALUATED`, including `CANDIDATE`, while actual Production rows remain
missing until trustworthy producers exist.

## Current obtainable evidence

- Tradability is only partially obtainable. Venue isolation is repaired so a
  delayed TPEx profile no longer blocks a valid TWSE observation (and vice versa),
  but current official observations are commonly later than the 17:00 decision and
  `full_cash_delivery_flag` is not independently sourced. Such rows remain missing.
- Market exposure has a complete schema, validation, atomic persistence, and
  consumer path, but no trained/versioned market-model producer or historical
  publication exists. It remains missing in current data.
- Position limits have a complete validation and transport contract, but no
  point-in-time portfolio/policy producer or historical state exists. They remain
  missing in current data.

No historical value backfill is authorized. The release and rollback sequence is
documented in
[`decision-policy-evidence-release.md`](decision-policy-evidence-release.md).
