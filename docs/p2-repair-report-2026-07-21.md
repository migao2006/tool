# Alpha Lens P2 修復交付報告

- 日期：2026-07-21（Asia/Taipei）
- 基礎版本：`tool-main-p1-fixed-2026-07-20.zip`
- 修復範圍：P2 Repository 修補、契約測試與部署手冊
- 遠端狀態：**尚未部署至 GitHub、Supabase、Vercel Staging／Production**
- 模型狀態：仍為 **`RESEARCH_ONLY`**

## 一、核心結論

P2 Repository 修復已完成，涵蓋原稽核列出的四項 P2 工作：

1. Prediction Snapshot 的 stale 判斷改為優先使用可信、point-in-time 的交易日曆；日曆證據不足時才明確退回 72 小時牆鐘門檻。
2. TWSE／TPEX 月度基準回補與研究特徵資料集 CLI 改用共用協調器，場別 adapter 與既有公開介面維持不變。
3. 三個過長核心函式已拆分為可測試的小型步驟，主流程分別降至 56、34、40 行。
4. 新增 Supabase Auth 密碼復原流程：PKCE、同源 redirect、`PASSWORD_RECOVERY` session gate、防帳號枚舉訊息，以及 callback 機密參數清除。

本次修補涉及 55 個既有／新增專案檔案（不含本報告）。Repository 層級驗證未發現 P2 新增功能造成的非 `pyarrow` 回歸；但 Supabase migration、真實 PostgreSQL execution plan、正式 Deno runtime、Playwright 瀏覽器流程、Auth 寄信及遠端 response headers 均尚未實際驗證，因此不能宣稱已上線。

## 二、P2 修復內容

### 2.1 交易日曆感知 freshness

新增：

- `supabase/functions/prediction-snapshot/freshness.ts`
- `supabase/migrations/20260721090000_prediction_snapshot_calendar_freshness.sql`
- `supabase/snippets/validate_prediction_snapshot_calendar_freshness.sql`
- `supabase/snippets/rollback_prediction_snapshot_calendar_freshness.sql`
- `supabase/functions/prediction-snapshot/tests/freshness_test.ts`

新增唯讀 RPC：

```text
market_data.get_prediction_snapshot_rows_v2(integer,text,timestamptz)
```

此 RPC 先呼叫 P1 的單一快照 RPC，再附加同市場、截至 `p_observed_at` 已可用的交易日曆觀測。正式 Edge 路徑仍維持單一 PostgREST 請求。

可信日曆列必須同時符合：

```text
calendar_verification_status = VERIFIED
market_basis = SOURCE_ASSERTED
usage_scope = POINT_IN_TIME_CALENDAR
system_status = PASS
available_at <= observed_at
```

交易 session 只有在 `decision_data_cutoff_at <= observed_at` 後，才能成為預期最新 session。系統不使用星期幾自行推測開休市。

預設政策：

```text
PREDICTION_CALENDAR_READY_HOUR_TAIPEI=17
PREDICTION_CALENDAR_LOOKBACK_DAYS=45
PREDICTION_STALE_AFTER_HOURS=72
```

- `PREDICTION_CALENDAR_LOOKBACK_DAYS` 允許 14～62 日。
- RPC 固定帶回 63 個曆日；這可涵蓋「台北就緒時間前，必要截止日仍是前一日」且 lookback 設為 62 的邊界。
- 可信且連續的日曆完整時，`freshness.method=TRADING_CALENDAR`。
- `as_of_date` 早於預期 session 時，加入 `STALE_PREDICTION_SNAPSHOT`。
- `as_of_date` 晚於可信日曆的預期 session 時，fail closed 為 stale，加入 `PREDICTION_SNAPSHOT_SESSION_AFTER_EXPECTED_CALENDAR`。
- 日曆不存在或覆蓋缺日時，明確回傳 `WALL_CLOCK_FALLBACK` 及對應原因碼，再以固定時數保守判斷。
- 若 RPC 回傳另一市場的日曆列，API 回傳 `409 PREDICTION_MARKET_SCOPE_MISMATCH`，禁止跨市場污染。

緊急 `legacy` 讀取模式不讀取新版日曆 payload，因此會明確使用牆鐘 fallback；它不是正式長期執行路徑。

### 2.2 TWSE／TPEX 共用協調器

新增月度基準 OHLC 共用模組：

```text
src/data/ingestion/monthly_benchmark_ohlc_backfill.py
```

共用處理：

- 輸入範圍驗證
- queue seed／claim／complete／snapshot
- lease 與重試
- provider／ingestion 錯誤封裝
- request interval
- 完成統計與 outcome

原場別檔案保留：

- `TaiexOhlcBackfillCoordinator`
- `TpexOhlcBackfillCoordinator`
- 原 summary 類別
- 場別資料集、symbol、錯誤碼及來源初始化

因此既有呼叫端不需要改名或改參數。

新增研究特徵 CLI 共用模組：

```text
scripts/_build_venue_research_feature_dataset.py
```

TWSE／TPEX adapter 只注入：

- archive scope
- identity repository
- dataset hash 函式
- Parquet writer／reader
- dataset builder
- 場別失敗原因碼

候選 artifact 的建立、read-back verification、原子 replace、audit 寫入及 fail-closed 錯誤結果由同一流程執行。

### 2.3 過長核心函式拆分

以 Python AST 重新量測：

| 核心函式 | 修補後行數 |
|---|---:|
| `HistoricalBackfillCoordinator.run` | 56 |
| `TwseDailyResearchInference.run` | 34 |
| `PreparedResearchDataset.from_frame` | 40 |

拆分後各主流程只負責協調；驗證、成本估算、任務處理、特徵與標籤準備、稽核組裝及輸出建立分散至具名 helper。既有決策門檻、研究狀態、資料血緣與 fail-closed 規則未放寬。

另新增純記憶體的 TWSE 每日推論測試，不依賴 Parquet，直接走完拆分後的推論主流程。

### 2.4 Supabase Auth 密碼復原

新增：

```text
src/features/auth/auth-callback.js
```

並修改 Auth service、controller、dialog、template、router、Supabase client、錯誤訊息與產品文件。

流程：

1. 使用者輸入 Email。
2. 前端呼叫 `resetPasswordForEmail`，並提供同源 recovery redirect。
3. 畫面無論供應商回覆為何，一律顯示通用訊息：不透露帳號是否存在。
4. Supabase 由 callback 建立 recovery session 並發出 `PASSWORD_RECOVERY` 事件後，才開啟新密碼表單。
5. controller 只有在 `recoveryMode=true` 時才允許呼叫 `updateUser({ password })`。
6. SDK 處理後，History API 清除 URL 中的 code、token、refresh token 與錯誤內容。

安全限制：

- Supabase client 使用 `flowType: "pkce"`。
- confirmation 與 recovery redirect 必須同源；跨來源值在 service 初始化時直接拒絕。
- 一般 `state` 查詢參數不會單獨被誤判成 Auth callback，也不會被清除。
- Router 在尚未處理的 implicit callback fragment 存在時，不覆寫 fragment。
- provider 的「帳號不存在」錯誤只送往既有 Sentry hook，不顯示給使用者；URL token 及原始 callback payload不寫入日誌。

Repository 已準備流程，但 Supabase Dashboard Redirect URLs allowlist、正式寄信 SMTP、寄件網域與實際信件交付仍需在 Staging／Production 驗證。

### 2.5 Release manifest 與部署契約

`release-manifest.json` 已更新：

- Repository migration 數量：37
- Primary RPC：`get_prediction_snapshot_rows_v2`
- 交易日曆 freshness 預設值與 63 日 RPC window
- P2 共用協調器路徑
- 三個核心函式行數
- Auth recovery 的 PKCE、event、redirect 與防枚舉狀態
- 遠端 migration／Auth／SMTP／Vercel 狀態均標示為未重新驗證

同步輸出：

- `model_card.md`
- `docs/current-status.md`
- `docs/release-state.md`
- `release-manifest.sha256`

`python scripts/sync_release_manifest.py --check` 已通過。

## 三、驗證結果

### 3.1 已通過

| 驗證 | 結果 |
|---|---:|
| P2 相關 Python 測試 | **97 通過、2 因缺少 `pyarrow` 排除** |
| 全部可執行 Python 測試 | **829 通過** |
| Edge Function TypeScript strict／noEmit | 通過 |
| Edge Function 行為測試 | **47／47 通過** |
| Auth recovery Node 行為檢查 | **9 項 assertion 通過** |
| Python `compileall` | 通過 |
| JavaScript／MJS `node --check` | **66 個檔案通過** |
| GitHub workflow YAML parse | **33 個檔案通過** |
| Workflow Bash syntax | **91 個 run block 通過 `bash -n`** |
| GitHub Action SHA 契約 | **137 次引用／10 個核准 pin 通過** |
| Migration 靜態契約 | **37 個 migration 通過** |
| Python lock 契約 | **32 個 exact pin 通過** |
| Vercel CSP／安全標頭契約 | 通過 |
| Release manifest sync | 通過 |
| `git diff --check` | 通過 |
| 私鑰／常見雲端 token／JWT 特徵掃描 | 0 項命中 |

Edge 行為測試涵蓋：

- 交易日、週末、長週末及臨時休市
- 自訂台北資料就緒時間
- 新 session 造成 stale
- snapshot 日期晚於可信日曆時 fail closed
- 日曆不可用／缺日的牆鐘 fallback
- 跨市場日曆資料拒絕
- 單一 RPC、RPC 缺失、timeout、429、CORS 與既有資料契約

### 3.2 因環境限制未完整執行

完整 Python suite 結果：

```text
829 passed, 36 failed, 10 errors
```

36 個失敗與 10 個收集錯誤全部來自目前容器沒有 `pyarrow`；錯誤均為 `ModuleNotFoundError: pyarrow` 或專案既有的 `PARQUET_DEPENDENCY_MISSING`。未觀察到其他失敗類型。這不等同完整 suite 通過，正式 CI 必須在鎖定依賴完整的環境重跑。

其他尚未完成：

- 容器沒有真正 Deno binary。47 項 Edge 測試先由 TypeScript 5.8.3 轉譯成 ES2022，再由 Node 22 相容 harness 執行；正式 Deno check／fmt／lint／test 仍由 GitHub CI 負責。
- 容器沒有 pnpm／`@playwright/test`／瀏覽器 binary；Corepack 嘗試下載 pnpm 時因無法連線 npm registry 失敗，所以新增的瀏覽器 E2E 尚未實際執行。
- 本機沒有 PostgreSQL、Supabase CLI 與 Docker Engine，新增 SQL 尚未執行、`EXPLAIN ANALYZE`、RLS、權限、validation 與 rollback 尚未實測。
- 本機沒有 Ruff、basedpyright、Biome、actionlint、Gitleaks、pip-audit、SQLFluff、pre-commit binary；Repository 契約已通過，但工具本身仍需由線上 CI 執行。
- 未核對 GitHub branch protection 是否要求 `test-gate`。
- 未核對 Vercel Preview／Production 實際 response headers。
- 未驗證 Supabase Auth recovery Email、Redirect URL allowlist、專用 SMTP 或寄件網域。

## 四、部署前限制與風險

### 4.1 Migration history 必須先核對

Repository 目前有 37 個 migration；現有文件只記錄 Staging／Production 套用到第 31 個：

```text
20260719152201_publish_research_snapshot_atomically.sql
```

其後共有 6 個 migration：

1. `20260720051630_tpex_price_index_ohlc_queue.sql`
2. `20260720061143_scope_prediction_runs_by_market.sql`
3. `20260720064801_exclude_legacy_prediction_publisher_from_lint.sql`
4. `20260720170000_prediction_snapshot_rate_limit.sql`
5. `20260720190000_prediction_snapshot_read_rpc.sql`
6. `20260721090000_prediction_snapshot_calendar_freshness.sql`

文件狀態不代表遠端真實狀態。禁止直接使用 `supabase db push --include-all`，也禁止未比對 schema 就執行 migration repair。必須先讀取真實 remote migration history，逐一判斷哪些檔案尚未套用。

### 4.2 部署順序不可顛倒

建議順序：

1. 在新的 Git branch 解壓並確認 SHA-256。
2. 在 Supabase Local 或隔離 PostgreSQL 重建 schema，執行全部 migration、validation 與 rollback 演練。
3. 比對 Staging 真實 migration history。
4. 只依時間順序套用確定缺少的 migration。
5. 執行：
   - `validate_prediction_snapshot_rate_limit.sql`
   - `validate_prediction_snapshot_read_rpc.sql`
   - `validate_prediction_snapshot_calendar_freshness.sql`
6. 設定 Staging Edge 變數：

```text
PREDICTION_SNAPSHOT_READ_MODE=rpc
PREDICTION_CALENDAR_READY_HOUR_TAIPEI=17
PREDICTION_CALENDAR_LOOKBACK_DAYS=45
PREDICTION_STALE_AFTER_HOURS=72
```

7. 部署 Edge Function；先測 weekday、週末、假日、臨時休市、缺日、跨市場、RPC 缺失及 timeout。
8. 在 Supabase Auth 設定正式與 Preview callback URL allowlist，設定專用 SMTP、寄件網域與寄信 rate limit。
9. 部署 Vercel Preview，驗證 CSP、安全標頭、PKCE callback、通用 reset 訊息及密碼更新。
10. 完整 GitHub CI、Playwright、Deno、SQLFluff、pip-audit 與 `test-gate` 全部通過後，才依相同步驟推進 Production。

### 4.3 Rate limit 仍維持關閉

P0 的持久化限流預設仍是：

```text
PREDICTION_RATE_LIMIT_ENABLED=false
```

只有在確認實際 Supabase Edge 平台提供的 client-address header 由可信代理覆寫、外部使用者無法偽造，且已設定獨立 HMAC secret 後，才能啟用。這個條件未因 P2 修補而改變。

### 4.4 模型仍不得升級為正式投資推薦

P2 只處理工程可靠性、維護性與帳號安全；沒有改變以下研究限制：

- rank model 未優於 20 日動能基準。
- 平均 Rank IC 仍為負。
- locked holdout 尚未執行。
- 歷史身分、公司行動、可成交性與 total-return benchmark 尚未完整 point-in-time 驗證。
- 最新 1,068 筆快照仍是 retrospective research inference，且全部為 `NO_TRADE`。

因此狀態必須維持 `RESEARCH_ONLY`。

## 五、Rollback

### 5.1 Snapshot freshness

在移除 v2 RPC 前，先將 Edge Function 明確切換至：

```text
PREDICTION_SNAPSHOT_READ_MODE=legacy
```

或重新部署 P1 版 Edge code。確認 API 可用後，再執行：

```text
supabase/snippets/rollback_prediction_snapshot_calendar_freshness.sql
```

若先刪除 v2 RPC、但 Edge 仍在 `rpc` 模式，API 會依設計回傳 503。

### 5.2 Frontend Auth recovery

Frontend recovery 沒有新增資料庫表。需要回復時，將 Vercel deployment rollback 至 P1 artifact，並同步移除不再使用的 Supabase recovery redirect URL；不要只移除 Dashboard allowlist 而保留會顯示成功的前端入口。

### 5.3 共用協調器／函式拆分

此部分沒有 migration。若線上 CI 或實際資料回補發現行為差異，直接 revert P2 commit；場別 adapter 名稱與呼叫介面已保留，因此回復不需要修改外部 workflow 參數。

## 六、驗收標準

Production 只能在以下條件全部成立後視為 P2 上線：

- 37 個 migration 與遠端 history 完整對齊。
- v2 RPC validation、權限、RLS 與 rollback 演練通過。
- 真實資料下 RPC P95／P99、payload、CPU 與 execution plan 在可接受範圍。
- 交易日、週末、國定假日、臨時休市與 calendar gap smoke test 通過。
- Supabase Redirect URLs allowlist、PKCE callback、SMTP 與 recovery Email 實測通過。
- 新增 Playwright recovery tests 在 Chromium、WebKit 與專案要求的瀏覽器矩陣通過。
- 真實 Deno、Ruff、basedpyright、Biome、actionlint、Gitleaks、pip-audit、SQLFluff、pre-commit 全部通過。
- GitHub branch protection 已將 `test-gate` 設為 required check。
- Vercel Preview／Production 實際回應 CSP 與安全標頭正確。
- 模型狀態仍為 `RESEARCH_ONLY`，沒有因工程修補被誤升級。
