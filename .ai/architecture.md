# Architecture and Dependency Rules

This file extends root `AGENTS.md`. Treat `docs/architecture.md` and the code as the implementation record; never describe a target layout as completed code.

## Dependency direction

```text
pages
  -> components / controllers
  -> services / use cases
  -> decision / models / calibration
  -> features / labels / validation / backtest
  -> data contracts / domain types
```

- Pages compose UI and must not call models, SQL, R2, or Supabase directly.
- Components must not depend on pages or construct database/model clients.
- Models, features, labels, and calibration must not depend on UI, routers, browser state, or database SDKs.
- External data enters through named clients, adapters, or repositories; domain logic must not depend on provider payloads.
- Prohibit cycles, cross-layer imports, deep modules mutating global UI state, and duplicated shared logic.

## Module responsibilities

- `src/data/`: provider clients, point-in-time contracts, normalization, repositories, and object storage.
- `src/features/`: auditable features built only from data available at the decision time.
- `src/labels/`: shared trading path, net returns, and labels.
- `src/models/`: separate rank, direction, quantile, market, and risk models.
- `src/calibration/`: direction probability and quantile interval calibration.
- `src/decision/`: gates, Top-K, capacity, and position limits; never reranking.
- `src/validation/`: purged walk-forward, temporal splits, and statistical evaluation.
- `src/backtest/`: execution, costs, limits, cohorts, cash, and holdings simulation.
- `src/pages/`, `src/components/`, `src/styles/`: presentation and interaction only.

## Data flow

```text
GitHub Actions / isolated runner
  -> provider clients
  -> ingestion and validation
  -> private R2 immutable Parquet
  -> Supabase queue / manifest / audit / UI summary
  -> canonical research dataset
  -> purged walk-forward research output
```

The frontend never accesses R2, provider credentials, or `service_role`. R2 clients own object I/O; Supabase repositories own database contracts.

## Splitting criteria

Split when a unit owns multiple primary responsibilities, changes for unrelated reasons, cannot be tested independently, shares excessive state, mixes UI/API/transformation, or combines model training and publication. File length is a warning, not a target. Do not produce tiny import, rename, or forwarding fragments.

Centralize artifact metadata, horizon validation, schema validation, and shared contracts while keeping model business logic separate.

## Cross-module contracts

- Version API, table, artifact, and reason-code schemas.
- Use timezone-aware timestamps: UTC internally and `Asia/Taipei` for Taiwan trading dates and UI.
- Bind horizon, label, feature schema, calibrator, cost profile, and model artifact versions.
- Treat globs, directory scans, dynamic imports, and filename conventions as dependencies during cleanup.
