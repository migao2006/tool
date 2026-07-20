# R2 歷史行情封存

> 2026-07-19 核對：Production R2 manifest 目前只有 `daily_bars`；其他 dataset 只有程式支援，尚未執行對應 workflow。最新數量見 [`current-status.md`](current-status.md)。

歷史日線 R2 封存只由 GitHub Actions 排程 worker 執行，不是瀏覽器、Vercel runtime 或公開 API 的功能。輸出維持 `RESEARCH_ONLY`，不得直接進入正式推薦。

## 日線流程與憑證隔離

- 排程以三個獨立 job 執行，每個 job 只取得自己的 FinMind token：`FINMIND_TOKEN`、`FINMIND_TOKEN_SECONDARY` 或 `FINMIND_TOKEN_TERTIARY`。
- 只有 primary job 設定 `HISTORICAL_BACKFILL_SEED_COMMON_TASKS=true`；secondary 與 tertiary 不重複建立共用 queue，但三者仍同時下載及認領不同任務。
- 三個 worker 都設定 `HISTORICAL_BACKFILL_REFRESH_HOME_STATUS=false`；完成後只由 `finalize-home-status` job 執行一次摘要更新，暫時性 Supabase timeout 採有限次 retry。
- reusable workflow 明確傳入每一項 secret，不使用 `secrets: inherit`。任一 token 的失效或 quota 用盡不應讓其他 credential slot 共用或暴露該 token。
- `R2_ACCESS_KEY_ID`、`R2_SECRET_ACCESS_KEY`、FinMind token 及 `SUPABASE_SERVICE_ROLE_KEY` 只存於 GitHub Actions secrets。不得寫入 `.env.example` 的值、程式、artifact、log、commit、PR 或 Issue。
- R2 worker credential 只授予該 private archive bucket 的 Object Read & Write；bucket 管理、CORS 或 lifecycle 使用另一組 admin credential，且不得注入 worker。
- `R2_ACCOUNT_ID` 與 `R2_BUCKET_NAME` 可由 GitHub repository variables 傳入；它們不是存取憑證。worker 仍須同時取得完整的四項 R2 設定才會啟動。

以上 primary seed、三個 worker 與單一 finalizer 規則只適用 `backfill-historical-daily-bars.yml`。其他 dormant workflow 不得套用錯誤的日線完成條件：

- Supplemental：三個 credential worker 各自執行冪等 seed／claim，沒有首頁 finalizer。
- Historical benchmark：單一 job、單一 FinMind request。
- Feature dataset：讀取並驗證 raw R2 object，輸出 30 天 GitHub artifact；目前不寫入 R2。
- Historical evidence：三個隔離 credential worker，但受 verified identity gate 阻擋。

## 儲存邊界

- R2 bucket 必須保持 private，不啟用 `r2.dev` 公開存取或 public custom domain。
- worker 透過 R2 的 S3-compatible HTTPS endpoint 寫入 immutable Parquet object；R2 client 固定使用 `region=auto`，並以已知 byte length 上傳及驗證 metadata、大小與 SHA-256。
- Supabase 只為新 R2 封存保存 `historical_archive_objects` manifest，包含 bucket、object key、來源期間、資料雜湊、Parquet 雜湊、列數、狀態及追蹤資訊；新封存的原始歷史列不複製進 PostgreSQL。目前多年歷史行情以 R2 為原始封存來源，Supabase landing 可以保持空白並由 queue 重新回補至 R2。
- object 驗證成功後才寫 manifest。既有 object 或 manifest 必須以相同 key 冪等處理；驗證失敗時 fail closed，排程 task 進入 retry。

## 讀取與完整性稽核

- `HistoricalParquetReader` 先驗證 bucket、R2 head metadata、ETag、byte size 及 SHA-256，再解析 Parquet；任一檢查失敗時不得釋出資料列。
- Parquet 必須符合固定 schema、schema metadata 與 ZSTD 壓縮，並逐列核對股票代號、日期範圍、來源 payload、資料狀態、排序及 parsed／quarantined 數量。
- `HistoricalArchiveManifestRepository` 使用 `archive_id` keyset pagination 讀取全部 manifest，不使用會因資料持續新增而漂移的 offset pagination。
- `.github/workflows/audit-historical-r2.yml` 每日執行全量唯讀稽核，也可手動執行；結果保存為 90 天 GitHub artifact，不包含憑證或原始行情內容。
- 本機或 CI 可執行：

```powershell
uv run python -m scripts.audit_historical_r2_archive `
  --output historical-r2-audit.json
```

- 完整性 `PASS` 只代表 manifest 與 R2 Parquet 一致，不代表 point-in-time、身分解析、模型或回測已通過；系統仍維持 `RESEARCH_ONLY`。

2026-07-19 手動全量稽核 run `29677606085` 已成功完成：

- object_count：1,971
- row_count：2,183,917
- byte_count：295,007,049
- integrity_status：`PASS`
- point_in_time_status：`UNVERIFIED`
- system_status：`RESEARCH_ONLY`
- manifest_snapshot_sha256：`fb926d3c43a2eca6345dd7771860100335c2ce9469d3de1f31b87283b73820be`

資料就緒度報告為 `BLOCKED`，原因包含 verified listing period、verified calendar、security
state、company action coverage 與 canonical contract 尚不可用，以及 843 筆下市身分仍未解析。

## GitHub Actions 設定名稱

Repository variables：

```text
R2_ACCOUNT_ID
R2_BUCKET_NAME
HISTORICAL_BACKFILL_SEED_DELISTED_TASKS
HISTORICAL_BENCHMARK_BACKFILL_ENABLED
HISTORICAL_SUPPLEMENTAL_BACKFILL_ENABLED
FINMIND_HISTORICAL_EVIDENCE_ENABLED
TWSE_RESEARCH_FEATURE_DATASET_ENABLED
TPEX_RESEARCH_FEATURE_DATASET_ENABLED
TPEX_PRICE_INDEX_OHLC_BACKFILL_ENABLED
FUGLE_ADJUSTED_BACKFILL_ENABLED
FUGLE_ADJUSTED_MIGRATION_READY
```

Repository secrets：

```text
FINMIND_TOKEN
FINMIND_TOKEN_SECONDARY
FINMIND_TOKEN_TERTIARY
FUGLE_API_KEY
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
```

worker runtime 另設定：

```text
HISTORICAL_BACKFILL_STORAGE_TARGET
HISTORICAL_BACKFILL_MAX_ARCHIVE_OBJECTS_PER_RUN
HISTORICAL_BACKFILL_MAX_ARCHIVE_OBJECT_BYTES
HISTORICAL_BACKFILL_SEED_COMMON_TASKS
HISTORICAL_BACKFILL_REFRESH_HOME_STATUS
HISTORICAL_SUPPLEMENTAL_ALLOWED_DATASETS
```

依 2026-07-19 免費 FinMind credential 的實際存取結果，預設值為
`institutional_flows,margin_short`。`adjusted_bars` 任務不刪除、不記為成功，會以
`ADJUSTED_BARS_PROVIDER_ACCESS_UNAVAILABLE` 延後；確認 credential 已取得
`TaiwanStockPriceAdj` 權限後，才可在手動 workflow dispatch 明確加入 `adjusted_bars`。

Fugle adjusted workflow 另用單一 `FUGLE_API_KEY`，不共用 FinMind supplemental RPC 或
credential slot。兩個 Fugle repository variables 未同時明確設為 `true` 時，排程 job 會保持
關閉；worker 本身也會在 dedicated migration RPC 不存在時先 fail closed，之後才可能建立
R2 client 或呼叫 provider。

`.env.example` 只記錄名稱與空值；實際 secret 不得以明文保存或回傳。

## 排程與驗證

- Caller workflow 使用單一 concurrency group，`cancel-in-progress=false`；前一輪未完成時，後一輪不得平行修改同一 queue。
- 正常完成必須同時看到 primary、secondary、tertiary 與 `finalize-home-status` 四個 job 成功。
- 日線 worker 每組每輪上限為 100 檔，仍受 FinMind 即時 quota、保留額度、請求 pacing、
  20 分鐘執行期限及 R2 object／byte guard 限制；不得用同一 token 開多個 worker。
- 實際封存量以 Supabase manifest 的 object、distinct symbol、row count 與 byte size 為準；GitHub artifact 只保存每個 worker 的執行摘要，不保存 Parquet 原始資料。
- 首頁 `historical_landing_count` 可以合計既有 Supabase landing 與最新 R2 logical slices，但 `historical_production_eligible_count` 在 point-in-time 驗證完成前必須保持 0。

## 資料集邊界

2026-07-19 已實際出現在 Production R2 manifest 的 dataset 仍只有：

- `daily_bars`

實際完成範圍：

- TWSE common stock：1,080 objects／1,205,606 rows。
- TPEX common stock：891 objects／978,311 rows。
- ETF：0 objects。

尚未出現在 Production R2 manifest：

- `adjusted_bars`
- `institutional_flows`
- `margin_short`
- `benchmark_total_return`

每一類資料都必須以自己的 schema version、metadata 與 row validator 驗證；不得把 benchmark
或籌碼資料套用日線 schema。Feature artifact typed manifest 與 provenance 驗證不會修改原始
R2 object；workflow 只輸出 GitHub artifact，不會把衍生特徵寫回 raw archive。

## TPEX 研究 artifact 邊界

- R2 已有 891 檔 TPEX 普通股 `daily_bars`，但仍是
  `RAW_LANDING_ONLY / POINT_IN_TIME_UNVERIFIED / RESEARCH_ONLY`。
- 2026-07-20 新增的 TPEX 17 個價量特徵 workflow 只讀取並驗證既有 immutable raw objects，輸出
  GitHub Parquet artifact 與 audit；typed read-back 驗證失敗時不得釋出 artifact。
- `TPEX_RESEARCH_FEATURE_DATASET_ENABLED` 未明確設為 `true` 時，workflow 不得執行。
- [run `29716316791`](https://github.com/migao2006/tool/actions/runs/29716316791) 已成功驗證
  1,642 個 manifests／891 檔來源股票，產生 1,511,065 筆／879 檔 feature rows；Parquet 為
  219,459,812 bytes，日期範圍 2018-04-09～2026-07-17。
- Dataset snapshot 為 `aa7b43d08ae939a4bebea930d914865f1e68aba9d287cc40afd9b44445685370`；
  Parquet SHA-256 為 `7e12dac2707e7dea17559ffe6b69f74f08ae4790c712c52bd33de1564eb3da8b`。
- 12 檔來源股票沒有 feature row；目前只有彙總排除原因，尚無逐檔排除清單。
- 本次分支已建立官方 TPEX 月 OHLC 的專用 Parquet schema、immutable R2 read-back、Supabase
  queue／RPC、CLI 與 GitHub Actions workflow。Object scope 固定為
  `TPEX / tpex_price_index_ohlc / TPEX_INDEX / BENCHMARK`，不得與普通股或 TAIEX 交叉配對。
- Local 已通過 migration、validation、rollback 再套用及 schema lint；Production feature gate
  仍關閉且尚無 TPEX benchmark object。首輪只能先執行單一完成月份 smoke test。
- TPEX OHLC 固定維持 `POINT_IN_TIME_UNVERIFIED / RAW_LANDING_ONLY / RESEARCH_ONLY /
  PRICE_INDEX_NOT_TOTAL_RETURN`；5 日標籤、獨立模型與 UI 不屬於本次已完成範圍。

因此 TPEX 目前已有 raw archive 與驗證過的研究 feature artifact，但尚無標籤或模型，狀態維持
`RESEARCH_ONLY / FEATURE_RESEARCH_ONLY / LABELS_NOT_ASSEMBLED`。

目前 campaign 固定結束於 2026-07-17。既定 queue 已全部完成，但這不會讓 R2 自動向後累積。
建立可稽核、冪等的 daily delta archive workflow 前，新交易日仍不會自動加入多年 R2 封存。
