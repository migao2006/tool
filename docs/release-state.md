# Release 與部署證據狀態

> 此文件完全由 `release-manifest.json` 產生；請勿直接修改。
> 最後核對日期：2026-07-20（Asia/Taipei）。
> 證據基準：`UPLOADED_REPOSITORY_AND_RECORDED_WORKFLOW_EVIDENCE`。

## 模型與研究快照

| 項目 | Manifest 記錄 |
| --- | --- |
| 系統狀態 | `RESEARCH_ONLY` |
| Model version | `twse-price-research-h5-v1` |
| Prediction run | `4` |
| Snapshot workflow | `29701335309` |
| Snapshot commit | 未記錄於目前可用證據（不得推測） |
| Evaluation scope | `RETROSPECTIVE_RESEARCH_INFERENCE` |
| Prediction count | `1068` |

## Migration 證據邊界

Repository 目前共有 **36** 個 migration 檔案。
本修補新增、且仍須在隔離環境驗證後才能部署：

- `20260720170000_prediction_snapshot_rate_limit.sql`
- `20260720190000_prediction_snapshot_read_rpc.sql`

Staging 已記錄：`31` 個，最後為 `20260719152201_publish_research_snapshot_atomically.sql`，證據狀態 `DOCUMENTED_NOT_REVERIFIED_BY_THIS_PATCH`。
Production 已記錄：`31` 個，最後為 `20260719152201_publish_research_snapshot_atomically.sql`，證據狀態 `DOCUMENTED_NOT_REVERIFIED_BY_THIS_PATCH`。

已記錄遠端最新 migration 之後的 Repository 檔案：

- `20260720051630_tpex_price_index_ohlc_queue.sql`
- `20260720061143_scope_prediction_runs_by_market.sql`
- `20260720064801_exclude_legacy_prediction_publisher_from_lint.sql`
- `20260720170000_prediction_snapshot_rate_limit.sql`
- `20260720190000_prediction_snapshot_read_rpc.sql`

上述檔案存在不等於已套用至任何遠端環境。

## P1 執行控制

### Prediction Snapshot

- 主要路徑：`market_data.get_prediction_snapshot_rows(integer,text,timestamptz)`。
- 正常 Edge→PostgREST 往返：`1` 次。
- 預設模式：`rpc`。
- 緊急回復模式：`legacy`。
- 靜默 fallback：禁止；契約為 `EXPLICIT_LEGACY_MODE_ONLY`。
- Migration：`20260720190000_prediction_snapshot_read_rpc.sql`。
- 遠端狀態：`REPOSITORY_ONLY_NOT_REMOTELY_VERIFIED`。

### CI 與供應鏈

- 品質工作 ID：`quality-security`。
- 彙總 gate ID：`test-gate`。
- Branch protection：`NOT_REVERIFIED_BY_THIS_PATCH`。
- Action pin policy：`config/github-actions-pins.json`。
- 工具版本來源：`config/quality-tools.env`。

| 工具 | 固定版本 |
| --- | --- |
| `actionlint` | `1.7.12` |
| `basedpyright` | `1.39.9` |
| `biome` | `2.4.16` |
| `deno` | `2.8.1` |
| `gitleaks` | `8.30.1` |
| `go` | `1.26.5` |
| `pip-audit` | `2.10.1` |
| `pre-commit` | `4.6.0` |
| `ruff` | `0.15.22` |
| `sqlfluff` | `4.2.2` |

### Vercel

- 設定檔：`vercel.json`。
- CSP enforcement：`true`。
- Inline script allowed：`false`。
- Inline style allowed：`false`。
- 正式站 response headers 已直接驗證：`false`。

## 部署限制

本次交付只修改 Repository。不得把下列事項描述為已完成：

- Staging／Production migration 已套用。
- Edge Function 已更新。
- Vercel Production 安全標頭已生效。
- GitHub branch protection 已要求新的彙總 gate。

部署時必須先套用並驗證 RPC migration，再部署預設 `rpc` 的 Edge Function。
