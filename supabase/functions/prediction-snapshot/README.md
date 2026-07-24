# prediction-snapshot Edge Function

這個 Function 是 `prediction-snapshot.v1` 的唯讀發布層。主要讀取路徑透過
`market_data.get_prediction_snapshot_rows_v2(...)`，由單一 PostgREST RPC
組裝已保存的
`prediction_runs`、`stock_predictions`、`market_predictions`、data-quality、
decision-gate、validation、backtest 與經驗證交易日曆觀測
紀錄。它不訓練模型、不即時計算新分數，也不以 placeholder 補值。正式預設為
`rpc`，RPC 尚未安裝、資料庫錯誤或逾時時都會 fail closed；`legacy`
只保留為需明確設定的緊急回復路徑。

## HTTP 契約

```http
GET /functions/v1/prediction-snapshot?horizon=5
X-Alpha-Lens-Contract: prediction-snapshot.v1
```

- 只接受 `horizon=5`；其他值回 `422 UNSUPPORTED_HORIZON`。
- 沒有 `prediction_run` 時回 `200`、`RESEARCH_ONLY`、空陣列及
  `NO_PREDICTION_SNAPSHOT`，日期與版本維持 `null`。
- Stored snapshot 無法套用 request-time 研究設定；收到設定 query 時回 `422`，
  避免把未重新計算的資料冒充為新成本情境。
- Hard-fail 股票不會出現在 `predictions`，只會出現在 `excluded`。
- 具有完整研究警告標記的 `RESEARCH_ONLY` 列會公開為 `WARN`，維持 可稽核 reason
  codes；若缺少必要政策輸入，會公開為
  `decision_policy_status=MISSING_REQUIRED_DATA`、`decision=null`，不會被誤列為
  有效 `NO_TRADE` 或 hard fail。沒有研究警告標記的 legacy `FAIL` 仍會排除。
- `NO_TRADE` 只代表 `EVALUATED` 的完整政策評估決定不進場。 `decision_counts`
  分別統計三種動作、缺資料、驗證失敗與 hard fail，總和必須與 實際發布列一致。
- 個股排除不會把 envelope 的 `data_quality_hard_fail` 設為
  `true`；該欄位只保留給 無法形成整體快照的系統級品質失敗，而 manifest
  不一致會直接回 `409`。
- Validation 只有在同一 model bundle／horizon、於 prediction run 建立前完成，且
  可唯一識別時才會附加；缺少或有歧義時回空 validation 與
  `VALIDATION_SNAPSHOT_NOT_LINKED`。
- `watchlist` 目前回空陣列；Authorization header 保留給未來 user-owned watchlist
  擴充，但目前不會改變公開研究快照。
- 所有回應使用 `Cache-Control: no-store`。

## 交易日曆感知 freshness

快照過期判斷優先使用 `market_data.trading_calendar_observations`
中符合下列全部條件的 point-in-time 觀測：

- `calendar_verification_status=VERIFIED`
- `market_basis=SOURCE_ASSERTED`
- `usage_scope=POINT_IN_TIME_CALENDAR`
- `system_status=PASS`
- `available_at <= request observed_at`

Edge Function 必須取得連續日曆覆蓋，並以已完成的 `decision_data_cutoff_at`
找出最近應完成交易
session。週末、國定假日與來源明確標示的臨時休市均由日曆處理。若可信日曆不存在、缺日或尚未覆蓋必要日期，系統會明確加入
`PREDICTION_FRESHNESS_WALL_CLOCK_FALLBACK`，再採用
`PREDICTION_STALE_AFTER_HOURS` 的保守門檻；不得自行猜測休市日。

回應的 `freshness.method` 只會是 `TRADING_CALENDAR` 或
`WALL_CLOCK_FALLBACK`，並附帶覆蓋範圍、預期 session 與原因碼。

## 環境設定

Supabase 自動提供：

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

必須另設：

- `PREDICTION_ALLOWED_ORIGINS`：以逗號分隔的完整 origin allowlist，不支援 `*`。
- `PREDICTION_STALE_AFTER_HOURS`：可選，僅作日曆資料不可用時的保守
  fallback，預設 `72`。
- `PREDICTION_CALENDAR_READY_HOUR_TAIPEI`：可選，台北時間 0～23，預設 `17`。
- `PREDICTION_CALENDAR_LOOKBACK_DAYS`：可選，連續覆蓋天數 14～62，預設 `45`；RPC
  固定取回 63 個曆日，以涵蓋就緒時間前的最大 lookback 邊界。
- `PREDICTION_DATABASE_TIMEOUT_MS`：單次 PostgREST 呼叫上限，預設 `4000`。
- `PREDICTION_REQUEST_TIMEOUT_MS`：整體請求上限，預設 `10000`。
- `PREDICTION_SNAPSHOT_READ_MODE`：`rpc`（預設）或 `legacy`。必須先在目標環境
  依序套用並驗證基礎 RPC 與 calendar freshness v2 migration，再部署預設 `rpc` 的
  Function；`legacy` 只作經核准的 緊急回復，不得作為長期設定。

`SUPABASE_SERVICE_ROLE_KEY` 只由 Function 對 PostgREST 使用，不得傳入前端、
回應、URL 或 log。因公開快照允許未登入使用者讀取，本 Function 在
`supabase/config.toml` 設為 `verify_jwt=false`；CORS 不是存取控制，回應內容
因此必須永遠只包含可公開的研究摘要。

## 本機驗證

若本機沒有 Deno，可使用 Docker：

```powershell
docker run --rm -v "${PWD}:/workspace" -w /workspace/supabase/functions/prediction-snapshot denoland/deno:alpine deno task check
docker run --rm -v "${PWD}:/workspace" -w /workspace/supabase/functions/prediction-snapshot denoland/deno:alpine deno task test
```

## 發布

不得在工作站直接部署 Production。合併後由 GitHub Actions 的
`Deploy prediction Edge Function` workflow 手動選擇 `staging` 或 `production`。
對應 GitHub Environment 必須設定：

- Secret：`SUPABASE_ACCESS_TOKEN`
- Variable：`SUPABASE_PROJECT_REF`
- Variable：`SUPABASE_URL`
- Variable：`PREDICTION_ALLOWED_ORIGINS`
- Variable（可選）：`PREDICTION_STALE_AFTER_HOURS`
- Variable（可選）：`PREDICTION_CALENDAR_READY_HOUR_TAIPEI`
- Variable（可選）：`PREDICTION_CALENDAR_LOOKBACK_DAYS`
- Variable（可選）：`PREDICTION_DATABASE_TIMEOUT_MS`
- Variable（可選）：`PREDICTION_REQUEST_TIMEOUT_MS`
- Variable（可選）：`PREDICTION_SNAPSHOT_READ_MODE`（正式預設
  `rpc`；只有經核准的緊急回復才可暫設 `legacy`）

`production` 只能由 `main` 手動觸發；相同 commit 會先部署及 smoke-test Staging，
成功後才進入 Production environment。Production environment 應設定 required
reviewer，讓正式發布保留人工核准與可稽核紀錄。所有手動部署會使用同一個
concurrency group 依序執行；smoke test 會核對 project ref、專案 URL、契約與實際
UI origin 的 CORS 回應，避免 Staging 驗證被其他部署覆寫或測到錯誤專案。
