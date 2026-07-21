# Alpha Lens 5 日預測 API 契約

> 2026-07-21 現況：`supabase/functions/prediction-snapshot` 已有唯讀實作，前端 `predictionApiBaseUrl` 已指向本專案 Supabase Edge Functions。Watchlist 持久化尚未上線，`watchlistPersistenceEnabled=false`，UI 必須停用寫入操作。限流 migration 已加入 repository，但在完成 Staging／Production migration 與環境設定前維持關閉。UI 不得使用示例資料冒充回應。

目前前端固定使用 `horizon=5`，並以 `market=TWSE|TPEX` 分別取得上市與上櫃資料集；契約版本為 `prediction-snapshot.v1`。缺省 `market` 時只查詢 `TWSE`，不得回傳跨市場混合資料。後端應使用 `src.api.PredictionSnapshotOutput` 產生回應，避免自行拼接欄位。

## 公開設定

在 `src/core/public-config.js` 設定：

```js
predictionApiBaseUrl: "https://<project-ref>.supabase.co/functions/v1/",
watchlistPersistenceEnabled: false,
```

Base URL 只能指向本專案實際的 HTTPS Edge Functions，不得保留 `example.com`。Watchlist table、RLS 與 PUT／DELETE 端點完成前，capability flag 必須保持 `false`；資料層也會以 `WATCHLIST_NOT_AVAILABLE` fail closed，不會讀取 session 或送出網路請求。前端逾時預設為 12 秒，所有 prediction 請求都帶有：

```http
Accept: application/json
X-Alpha-Lens-Contract: prediction-snapshot.v1
```

## GET prediction-snapshot

用途：取得今日總覽、候選股、個股詳情與目前登入者的自選清單。未登入時不帶權杖並回傳公開資料；已登入時前端會自動加入 `Authorization: Bearer <Supabase access token>`，後端才可回傳該使用者的 `watchlist`。

目前 Edge Function 先提供公開研究快照；`Authorization` header 只保留擴充點，
`watchlist` 固定為空陣列，直到 user-owned watchlist table、RLS 與契約完成。
Function 以 server-side `SUPABASE_SERVICE_ROLE_KEY` 讀取私有 schema，該 key
不得出現在前端設定、請求 URL、API 回應或 log。

必要 query：

- `horizon=5`

市場 query：

- `market=TWSE`：上市資料集。
- `market=TPEX`：上櫃資料集。
- 未提供時向後相容為 `TWSE`。
- `ALL`、空值、重複參數或其他值回 `422 UNSUPPORTED_MARKET`。

允許的研究設定 query：

- `commission_discount`
- `minimum_fee`
- `estimated_order_notional_ntd`
- `max_adv_participation`
- `cost_profile`
- `max_single_position`
- `max_industry_position`
- `max_market_exposure`

第一版唯讀 Function 不會在 request-time 重新計算模型或成本。若上述研究設定
已帶入 query，會回 `422 RESEARCH_SETTINGS_NOT_AVAILABLE_FOR_STORED_SNAPSHOT`，
不得靜默忽略後回傳基礎快照。後續只能在已保存對應設定的版本化 snapshot 後
才可開放。

回應 envelope：

| 欄位 | 說明 |
| --- | --- |
| `api_contract_version` | 固定 `prediction-snapshot.v1` |
| `as_of_date` | 資料交易日，ISO 日期 |
| `decision_at` | 含時區的決策時間 |
| `horizon` | 第一版固定 `5` |
| `market_scope` | 本快照唯一市場範圍：`TWSE` 或 `TPEX`；舊版未提供時前端僅可視為 `TWSE` |
| `system_status` | `PASS`、`RESEARCH_ONLY` 或 `FAIL` |
| `stale` | 資料是否逾期 |
| `freshness` | 過期判斷方法與稽核 metadata；`method` 為 `TRADING_CALENDAR` 或 `WALL_CLOCK_FALLBACK` |
| `data_quality_hard_fail` | 整體快照是否有系統級關鍵資料失敗；個股 hard fail 僅列於 `excluded` |
| `reason_codes` | 可稽核原因碼陣列 |
| `market` | `MarketOutput.to_dict()` |
| `predictions` | `StockPredictionOutput.to_dict()` 陣列 |
| `watchlist` | 目前登入者的自選股預測陣列 |
| `excluded` | hard fail 標的陣列 |
| `model_version` | 排名模型版本 |
| `training_end_date` | 訓練資料截止日 |
| `cost_profile_version` | 成本契約版本 |
| `validation` | Walk-forward、holdout、排名、校準與成本敏感度摘要 |

研究快照可附加下列最新已發布證券主檔分類欄位：`current_industry`、
`current_industry_code`、`industry_classification_effective_from`、
`industry_classification_effective_to`、`industry_classification_available_at` 及
`industry_classification_basis`。有效期間採半開區間
`[effective_from, effective_to)`；`effective_to=null` 代表尚未結束。已過期或尚未
`available_at` 的分類不得回傳為目前分類。
它們只供目前畫面顯示與篩選，不是模型在 `decision_at` 使用的 point-in-time
`industry`，不得用來產生或補寫 `industry_rank`。`cost_profile` 可由已綁定的
`cost_profile_version` 解析為已知成本情境；無法辨識時必須回傳 `null`。

若指定市場尚無任何 `prediction_run`，端點回 `200` 與該市場的真實空快照：
`system_status=RESEARCH_ONLY`、`reason_codes=["NO_PREDICTION_SNAPSHOT"]`、
`predictions/watchlist/excluded=[]`，且未知日期與版本欄位為 `null`。不得以目前日期
或 placeholder 代替，也不得以另一市場的快照 fallback。若 run、prediction、security
或 market prediction 的市場互相衝突，回 `409 PREDICTION_MARKET_SCOPE_MISMATCH`。

Validation 不以「同版本最新一筆」任意拼接。只有同一
`model_bundle_version + horizon`、`completed_at <= prediction_run.created_at`，且查詢
結果可唯一識別時才附加；缺少或有歧義時 `validation={}`，並加入
`VALIDATION_SNAPSHOT_NOT_LINKED`。這不阻擋已保存的個股研究輸出，但不得將未連結的
驗證結果當作該次預測之正式證據。

正式 `PASS` 股票的 `gates` 必須依下列固定順序完整回傳：

1. `data_quality_hard_gate`
2. `tradability_gate`
3. `liquidity_capacity_gate`
4. `market_exposure_cap`
5. `calibrated_direction_probabilities`
6. `net_quantile_thresholds`
7. `rank_eligibility`
8. `position_capacity_limits`

每個 gate 必須包含 `gate`、`passed`、`actual`、`threshold` 及 `reason_code`。

正式 `PASS` 契約還必須保留每個 gate 的 `source_date`。目前 Python／前端 gate adapter 尚未完整實作此欄位，屬正式接入前必修缺口。

只有完整且通過 `PredictionSnapshotOutput` 驗證的 `PASS` 回應，才會在前端顯示正式候選。缺欄、錯誤 horizon、非單調分位數、錯誤機率、未知契約版本或缺少稽核欄位都會轉為 `FAIL`，不會以舊資料補上。

### 交易日曆感知 freshness

後端優先使用已驗證、來源斷言且 point-in-time 可用的交易日曆觀測判斷最近應完成 session。判斷必須同時限制 `available_at <= observed_at`，且交易日的 `decision_data_cutoff_at` 已經過去；不得只用星期幾猜測開休市。

可信日曆覆蓋完整時：

- `freshness.method=TRADING_CALENDAR`。
- `expected_session_date` 為截至請求時間最近已完成的交易 session。
- `as_of_date < expected_session_date` 時加入 `STALE_PREDICTION_SNAPSHOT`。
- `as_of_date > expected_session_date` 視為日曆／快照不一致，回傳 `stale=true` 與 `PREDICTION_SNAPSHOT_SESSION_AFTER_EXPECTED_CALENDAR`，禁止把未經日曆驗證的未來日期當成新鮮資料。

日曆不存在或連續覆蓋不完整時：

- `freshness.method=WALL_CLOCK_FALLBACK`。
- 加入 `PREDICTION_FRESHNESS_WALL_CLOCK_FALLBACK`，以及 `VERIFIED_TRADING_CALENDAR_UNAVAILABLE` 或 `VERIFIED_TRADING_CALENDAR_COVERAGE_INCOMPLETE`。
- 再以 `PREDICTION_STALE_AFTER_HOURS` 的固定門檻保守判斷。

`PREDICTION_CALENDAR_READY_HOUR_TAIPEI` 預設 17，`PREDICTION_CALENDAR_LOOKBACK_DAYS` 預設 45。前者控制當日 session 何時可成為 freshness 的必要基準，後者要求 14～62 日的連續可信日曆資料。RPC 固定帶回 63 個曆日，避免在就緒時間前、`required_date` 仍為前一日且 lookback 設為 62 時少取最早一天。

## PUT watchlist/{market}/{symbol}

用途：將股票加入目前使用者的自選股。

此端點目前尚未部署；前端按鈕不得在後端缺席時模擬儲存成功。

```json
{"market":"TWSE","symbol":"股票代號"}
```

必須驗證 `Authorization: Bearer <Supabase access token>`，以 JWT 的 `sub` 作為資料擁有者，不得接受 body 內的 user id。成功可回傳 JSON，或使用 `204 No Content`。

## DELETE watchlist/{market}/{symbol}

用途：將股票移出目前使用者的自選股。必須使用相同的 Supabase JWT 驗證與資料擁有者限制。成功可回傳 JSON，或使用 `204 No Content`。

## Horizon 拒絕契約

後端收到 2、3 或 10 等未發布 horizon 時必須回傳 `UNSUPPORTED_HORIZON`，不得靜默改成 5。現有前端內部錯誤碼仍使用 `MODEL_NOT_RELEASED`；正式接入前需統一成 `UNSUPPORTED_HORIZON`，並補前後端 contract test。

## HTTP、CORS 與快取

- `401`：未登入或 token 失效。
- `403`：已登入但無權存取資源。
- `404`：未知股票或端點。
- `409`：資料／模型版本無法形成一致快照。
- `422`：query 或研究設定不合法。
- `429`：請求過於頻繁。
- `5xx`：服務失敗；不得回傳舊資料冒充成功。
- API 若回傳符合 `A-Z0-9_` 格式的 `code`，前端會保留該 reason code 供稽核；畫面仍使用固定的安全錯誤文案。
- 若 API 與前端不同網域，CORS 只允許正式前端 origin、必要 method 與 `Authorization`、`Content-Type`、`X-Alpha-Lens-Contract` headers。
- `prediction-snapshot` 應回傳 `Cache-Control: no-store`，或使用包含 `as_of_date`、設定與使用者身分的正確快取鍵。
- Edge Function 使用 `PREDICTION_ALLOWED_ORIGINS` 的逗號分隔 exact-origin allowlist；不得使用 `*`。
- 公開研究快照不要求登入，因此 Function gateway 設為 `verify_jwt=false`；這不會讓瀏覽器直接取得私有 schema，所有資料仍只經 server-side repository 整理後回傳。
- 每個回應都帶 `X-Request-Id`；若客戶端提供符合格式的 `X-Request-Id` 會沿用，否則由後端產生 UUID。錯誤 JSON 同時回傳 `request_id`，供 Edge Function logs 對照。
- `PREDICTION_REQUEST_TIMEOUT_MS` 控制整體 request deadline，預設 10 秒；`PREDICTION_DATABASE_TIMEOUT_MS` 控制單次 PostgREST 查詢，預設 4 秒。逾時分別回 `504 PREDICTION_REQUEST_TIMEOUT` 或 `504 PREDICTION_DATABASE_TIMEOUT`，不得等待至平台強制終止。
- 結構化 logs 只記錄 request ID、method、market、status、error code 與耗時，不得記錄 Authorization、原始 client address、service role key 或資料庫 payload。
- 可部署的持久化 fixed-window 限流使用 `market_data.consume_prediction_snapshot_rate_limit`。客戶端位址先以 server-side `PREDICTION_RATE_LIMIT_KEY_SECRET` 做 HMAC-SHA256；來源 header 由 `PREDICTION_RATE_LIMIT_CLIENT_IP_HEADER` 明確指定，預設為 `CF-Connecting-IP`。部署前必須確認該 header 在實際 Edge 平台由可信代理覆寫且外部用戶不能任意偽造；若無法確認，不得開啟限流。資料庫只保存 64 字元 opaque key，不保存原始位址。限流必須在 migration 套用、權限與 rollback 驗證通過並設定至少 32 字元專用 secret 後，才可將 `PREDICTION_RATE_LIMIT_ENABLED=true`；否則維持關閉。啟用後後端不可因限流儲存不可用而 fail open。

## 接入檢查

1. 後端以 `PredictionSnapshotOutput.to_dict()` 產生一份真實快照。
2. 確認 `api_contract_version`、日期、horizon、模型版本與成本版本一致。
3. 確認所有 `available_at <= decision_at`，hard fail 不會成為 `CANDIDATE`。
4. 分別驗證 `TWSE` 與 `TPEX`，確認任一市場為空或錯誤時不會回退或污染另一市場。
5. 設定 `predictionApiBaseUrl`。
6. 以未登入、已登入、逾時、401、錯誤 JSON、`RESEARCH_ONLY`、`FAIL` 與 `PASS` 各測一次。
7. 驗證交易日、週末、國定假日、臨時休市、日曆缺日與 72 小時 fallback。
8. 確認同一市場的總覽、候選、個股詳情及自選股都顯示相同 `as_of_date` 與模型版本。
