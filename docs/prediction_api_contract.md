# Alpha Lens 5 日預測 API 契約

目前前端固定使用 `horizon=5`，契約版本為 `prediction-snapshot.v1`。後端應使用 `src.api.PredictionSnapshotOutput` 產生回應，避免自行拼接欄位。

## 公開設定

在 `src/core/public-config.js` 設定：

```js
predictionApiBaseUrl: "https://api.example.com/v1/",
```

也可以在部署時於 `<html>` 設定 `data-prediction-api-base-url` 覆寫。正式環境必須使用 HTTPS。前端逾時預設為 12 秒，所有請求都帶有：

```http
Accept: application/json
X-Alpha-Lens-Contract: prediction-snapshot.v1
```

## GET prediction-snapshot

用途：取得今日總覽、候選股、個股詳情與目前登入者的自選清單。未登入時不帶權杖並回傳公開資料；已登入時前端會自動加入 `Authorization: Bearer <Supabase access token>`，後端才可回傳該使用者的 `watchlist`。

必要 query：

- `horizon=5`

允許的研究設定 query：

- `commission_discount`
- `minimum_fee`
- `estimated_order_notional_ntd`
- `max_adv_participation`
- `cost_profile`
- `max_single_position`
- `max_industry_position`
- `max_market_exposure`

回應 envelope：

| 欄位 | 說明 |
| --- | --- |
| `api_contract_version` | 固定 `prediction-snapshot.v1` |
| `as_of_date` | 資料交易日，ISO 日期 |
| `decision_at` | 含時區的決策時間 |
| `horizon` | 第一版固定 `5` |
| `system_status` | `PASS`、`RESEARCH_ONLY` 或 `FAIL` |
| `stale` | 資料是否逾期 |
| `data_quality_hard_fail` | 快照是否有關鍵資料失敗 |
| `reason_codes` | 可稽核原因碼陣列 |
| `market` | `MarketOutput.to_dict()` |
| `predictions` | `StockPredictionOutput.to_dict()` 陣列 |
| `watchlist` | 目前登入者的自選股預測陣列 |
| `excluded` | hard fail 標的陣列 |
| `model_version` | 排名模型版本 |
| `training_end_date` | 訓練資料截止日 |
| `cost_profile_version` | 成本契約版本 |
| `validation` | Walk-forward、holdout、排名、校準與成本敏感度摘要 |

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

只有完整且通過 `PredictionSnapshotOutput` 驗證的 `PASS` 回應，才會在前端顯示正式候選。缺欄、錯誤 horizon、非單調分位數、錯誤機率、未知契約版本或缺少稽核欄位都會轉為 `FAIL`，不會以舊資料補上。

## PUT watchlist/{symbol}

用途：將股票加入目前使用者的自選股。

```json
{"symbol":"股票代號"}
```

必須驗證 `Authorization: Bearer <Supabase access token>`，以 JWT 的 `sub` 作為資料擁有者，不得接受 body 內的 user id。成功可回傳 JSON，或使用 `204 No Content`。

## DELETE watchlist/{symbol}

用途：將股票移出目前使用者的自選股。必須使用相同的 Supabase JWT 驗證與資料擁有者限制。成功可回傳 JSON，或使用 `204 No Content`。

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

## 接入檢查

1. 後端以 `PredictionSnapshotOutput.to_dict()` 產生一份真實快照。
2. 確認 `api_contract_version`、日期、horizon、模型版本與成本版本一致。
3. 確認所有 `available_at <= decision_at`，hard fail 不會成為 `CANDIDATE`。
4. 設定 `predictionApiBaseUrl`。
5. 以未登入、已登入、逾時、401、錯誤 JSON、`RESEARCH_ONLY`、`FAIL` 與 `PASS` 各測一次。
6. 確認總覽、候選、個股詳情及自選股都顯示相同 `as_of_date` 與模型版本。
