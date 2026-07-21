# Alpha Lens P0 修復交付報告

> 日期：2026-07-20（Asia/Taipei）
> 修復來源：`alpha-lens-full-audit-2026-07-20.md`
> 交付狀態：原始碼修復完成；**尚未套用遠端 migration、尚未部署 Supabase Edge Function 或 Vercel Production**。

## 一、核心結論

本次已完成稽核報告中的 P0 原始碼修復，且維持既有產品邊界：

- 系統狀態仍為 `RESEARCH_ONLY`。
- 所有已發布研究列仍為 `NO_TRADE`。
- 未新增虛構資料、正式候選股或獲利宣稱。
- Watchlist 後端尚未存在，因此前端與資料層均 fail closed。
- Prediction API 的持久化限流預設關閉；在 migration、權限、rollback 與可信 client-address header 驗證完成前不得開啟。

## 二、已完成修復

### 1. 產業分類有效期間

`prediction-snapshot` 現在以半開區間判斷目前分類：

```text
effective_from <= 台北日期 < effective_to
```

`effective_to=null` 才表示持續有效。已過期或 `available_at` 晚於目前時間的分類不會再回傳為目前分類。API 與前端契約新增：

```text
industry_classification_effective_to
```

### 2. Watchlist 功能閘門

新增公開設定：

```js
watchlistPersistenceEnabled: false
```

在功能關閉時：

- 個股頁星號按鈕保持 disabled。
- UI 顯示「自選股儲存功能尚未上線」。
- 資料層在讀取 Supabase session 或執行 `fetch` 前直接回傳 `WATCHLIST_NOT_AVAILABLE`。
- 實際執行驗證確認網路呼叫次數為 0。

### 3. Prediction API deadline 與可觀測性

新增：

- 整體 request deadline，預設 10 秒，上限 30 秒。
- 單次 PostgREST query timeout，預設 4 秒，上限 30 秒。
- `X-Request-Id` 輸入驗證、產生與回傳。
- JSON 結構化 completion／failure logs。
- CORS allow／expose headers，包括 request ID 與 rate-limit headers。
- 穩定錯誤碼：
  - `PREDICTION_REQUEST_TIMEOUT`
  - `PREDICTION_DATABASE_TIMEOUT`
  - `PREDICTION_RATE_LIMIT_TIMEOUT`
  - `PREDICTION_RATE_LIMIT_UNAVAILABLE`

Logs 僅包含 request ID、method、market、status、error code 與耗時，不記錄 Authorization、原始 client address、service-role key 或資料庫 payload。

### 4. 持久化、原子化限流

新增 migration：

```text
supabase/migrations/20260720170000_prediction_snapshot_rate_limit.sql
```

設計特性：

- Postgres fixed-window 原子計數。
- 計數封頂於 `limit + 1`，避免持續攻擊造成整數無限制增長。
- client address 先以專用 server-side secret 做 HMAC-SHA256。
- 資料庫不保存原始位址，只保存 64 字元 opaque key。
- Table 啟用並強制 RLS。
- `anon`、`authenticated` 與 `public` 不可存取 table 或 RPC。
- RPC 為 `SECURITY INVOKER`，僅授權 `service_role`。
- Edge Function 對不合理的 backend response fail closed。
- Rate-limit backend 不可用時不會放行請求。

同時新增：

```text
supabase/snippets/validate_prediction_snapshot_rate_limit.sql
supabase/snippets/rollback_prediction_snapshot_rate_limit.sql
```

限流預設：

```text
PREDICTION_RATE_LIMIT_ENABLED=false
```

因此此 patch 可以先部署程式但保持限流關閉；不得在 migration 與權限驗證前設為 `true`。

### 5. 單一 Release Manifest

新增：

```text
release-manifest.json
release-manifest.sha256
scripts/sync_release_manifest.py
```

由 manifest 產生或同步：

- `model_card.json`
- `model_card.md` 的受管區段
- `docs/current-status.md` 的受管區段
- manifest SHA-256 digest

目前最新發布研究快照已改為：

- Workflow：`29701335309`
- Prediction run：`4`
- Model bundle：`c41b76df09decf6be62da3cc59012597c7fd889d4980e43c14eb7cca70de5ca7`
- Snapshot：`4581af6f96eb56791a498343784e484a3c604ef7c32f549ffdbbfc7dce60f505`
- GitHub artifact：`8446597593`

可用證據沒有記錄發布 commit，因此 manifest 保留 `null` 與 `NOT_RECORDED_IN_AVAILABLE_EVIDENCE`，沒有沿用舊 commit。

Migration 證據也已分開記錄：

- Repository：35 個 migration 檔案。
- 本修補新增並待隔離驗證：`20260720170000_prediction_snapshot_rate_limit.sql`。
- 遠端文件最後完整記錄：Staging／Production 各 31 筆，截止 `20260719152201_publish_research_snapshot_atomically.sql`。
- 其後 4 個 migration 的遠端套用狀態，本修補沒有連線重新驗證，因此不判定已部署或未部署。

## 三、驗證結果

### 已通過

| 驗證 | 結果 |
| --- | --- |
| 受影響 Python 契約測試 | 28／28 通過 |
| Prediction Edge 行為測試 | 32／32 通過 |
| TypeScript `strict`／`noEmit` | 通過 |
| 修改的 JavaScript／MJS `node --check` | 通過 |
| Python 語法檢查 | 通過 |
| `release-manifest` 同步檢查 | 通過 |
| 33 個 GitHub Actions workflow YAML 解析 | 通過 |
| 修改 workflow 的 12 個 Bash run block 語法 | 通過 |
| Watchlist runtime capability gate | 通過，0 次網路呼叫 |
| 修改檔案機密特徵掃描 | 0 項命中 |

Edge 測試是在 Node 22 的 TypeScript transform 與 `Deno.test` 相容 harness 下執行；它驗證行為，但不等同實際 Deno runtime。

### 尚未完成／受環境限制

- 完整 Python suite 在 collection 階段因容器缺少 `truststore` 中止；離線 `uv` 安裝又缺少 `pyarrow` wheel。因此不能宣稱全套 Python 測試通過。
- 容器沒有 Deno binary，未執行真正的 `deno fmt --check`、`deno lint`、`deno test`。
- 容器沒有 pnpm／Playwright runtime，未重跑瀏覽器測試。
- 容器沒有 PostgreSQL、Supabase CLI 與 Docker Engine，migration、validation、rollback、RLS 與 PostgREST RPC 尚未實際執行。
- 未連線查詢 Staging／Production migration history、Edge logs 或正式 response headers。
- 未執行任何遠端部署或修改任何遠端環境變數。

## 四、部署前必要步驟

### 1. 建立分支並安裝鎖定依賴

```powershell
uv sync --frozen --extra test
pnpm install --frozen-lockfile
```

執行：

```powershell
uv run pytest
pnpm exec playwright install chromium
pnpm run test:e2e
python scripts/sync_release_manifest.py --check
```

### 2. 本機 Supabase 隔離驗證

先確認 Docker Engine 可連線，再依專案既有規範執行：

```powershell
pnpm exec supabase db reset --local --no-seed
pnpm exec supabase db lint --local --schema public,market_data --level warning --fail-on error
```

在 Local 執行：

```text
supabase/snippets/validate_prediction_snapshot_rate_limit.sql
```

接著演練：

```text
supabase/snippets/rollback_prediction_snapshot_rate_limit.sql
```

完成 rollback 後重新 reset／套用 migration，再重跑 validation 與 lint。驗證 table、RPC、RLS、grants、原子計數及拒絕結果均符合契約。

### 3. 先核對遠端 migration history

遠端文件最後只完整記錄到第 31 個 migration。操作 Staging 前必須先查明以下 4 個檔案在各環境的實際狀態：

```text
20260720051630_tpex_price_index_ohlc_queue.sql
20260720061143_scope_prediction_runs_by_market.sql
20260720064801_exclude_legacy_prediction_publisher_from_lint.sql
20260720170000_prediction_snapshot_rate_limit.sql
```

禁止直接使用 `db push --include-all`、盲目 migration repair，或僅依 Repository 檔案推測遠端狀態。只能推送經確認尚未套用、且已在 Local 驗證的 forward migration。

### 4. Staging 部署

先保持：

```text
PREDICTION_RATE_LIMIT_ENABLED=false
```

設定或確認：

```text
PREDICTION_DATABASE_TIMEOUT_MS=4000
PREDICTION_REQUEST_TIMEOUT_MS=10000
PREDICTION_RATE_LIMIT_REQUESTS=30
PREDICTION_RATE_LIMIT_WINDOW_SECONDS=60
PREDICTION_RATE_LIMIT_CLIENT_IP_HEADER=CF-Connecting-IP
```

透過 GitHub workflow 部署 Staging Edge Function，完成 smoke test、request ID、timeout 與錯誤碼驗證。

### 5. 驗證可信 client-address header 後才開啟限流

必須先在實際 Supabase Edge 環境確認 `PREDICTION_RATE_LIMIT_CLIENT_IP_HEADER`：

- 由可信代理覆寫。
- 外部用戶不能透過同名 request header 任意偽造。
- 正常請求能取得穩定但不會被 log 的 client address。

產生至少 32 字元、只供限流使用的隨機 secret：

```text
PREDICTION_RATE_LIMIT_KEY_SECRET=<dedicated-random-secret>
```

再將 Staging 設為：

```text
PREDICTION_RATE_LIMIT_ENABLED=true
```

驗證：

- 前 30 次請求正常。
- 超過門檻回 `429 PREDICTION_API_RATE_LIMITED`。
- `X-RateLimit-Limit`、`X-RateLimit-Remaining`、`Retry-After` 正確。
- 資料庫沒有原始 client address。
- RPC 或資料庫故障時回 503／504，不會 fail open。

### 6. Production

只有在 Local、Staging、完整 CI、瀏覽器測試、Deno 測試、migration history 與 rollback 都通過後，才透過 GitHub PR／merge 進入 Production。不得直接使用 Vercel CLI 或 Supabase CLI 手動繞過既有發布閘門。

## 五、回復方式

若新 Edge Function 有問題但 migration 正常：

1. 將 `PREDICTION_RATE_LIMIT_ENABLED=false`。
2. 透過 GitHub workflow 重新部署。
3. 回復至上一個已驗證 Edge Function commit。

若必須移除 rate-limit schema：

1. 先確認所有環境已關閉 rate limit。
2. 在 Staging 執行 rollback snippet 並驗證。
3. 經相同發布閘門後才在 Production 執行。
4. 不要在仍有 Function traffic 使用 RPC 時直接 drop function／table。

## 六、未納入本次 P0 的項目

下列仍屬後續工作：

- 將約 42 次 request-time PostgREST 查詢重構為單一 RPC、唯讀 View 或預組裝 artifact。
- 將 Ruff、basedpyright、Biome、actionlint、Gitleaks、pip-audit、SQL lint 納入 required CI。
- GitHub Actions 外部 action pin 至完整 commit SHA。
- Vercel CSP 與完整 response security headers。
- 交易日曆感知的 stale 判斷。
- Watchlist table、RLS、PUT／DELETE API 與正式帳號復原流程。
