# R2 歷史行情封存

歷史日線 R2 封存只由 GitHub Actions 排程 worker 執行，不是瀏覽器、Vercel runtime 或公開 API 的功能。輸出維持 `RESEARCH_ONLY`，不得直接進入正式推薦。

## 執行與憑證隔離

- 排程以三個獨立 job 執行，每個 job 只取得自己的 FinMind token：`FINMIND_TOKEN`、`FINMIND_TOKEN_SECONDARY` 或 `FINMIND_TOKEN_TERTIARY`。
- 只有 primary job 設定 `HISTORICAL_BACKFILL_SEED_COMMON_TASKS=true`；secondary 與 tertiary 不重複建立共用 queue，但三者仍同時下載及認領不同任務。
- 三個 worker 都設定 `HISTORICAL_BACKFILL_REFRESH_HOME_STATUS=false`；完成後只由 `finalize-home-status` job 執行一次摘要更新，暫時性 Supabase timeout 採有限次 retry。
- reusable workflow 明確傳入每一項 secret，不使用 `secrets: inherit`。任一 token 的失效或 quota 用盡不應讓其他 credential slot 共用或暴露該 token。
- `R2_ACCESS_KEY_ID`、`R2_SECRET_ACCESS_KEY`、FinMind token 及 `SUPABASE_SERVICE_ROLE_KEY` 只存於 GitHub Actions secrets。不得寫入 `.env.example` 的值、程式、artifact、log、commit、PR 或 Issue。
- R2 worker credential 只授予該 private archive bucket 的 Object Read & Write；bucket 管理、CORS 或 lifecycle 使用另一組 admin credential，且不得注入 worker。
- `R2_ACCOUNT_ID` 與 `R2_BUCKET_NAME` 可由 GitHub repository variables 傳入；它們不是存取憑證。worker 仍須同時取得完整的四項 R2 設定才會啟動。

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

## GitHub Actions 設定名稱

Repository variables：

```text
R2_ACCOUNT_ID
R2_BUCKET_NAME
```

Repository secrets：

```text
FINMIND_TOKEN
FINMIND_TOKEN_SECONDARY
FINMIND_TOKEN_TERTIARY
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
```

`.env.example` 只記錄名稱與空值；實際 secret 不得以明文保存或回傳。

## 排程與驗證

- Caller workflow 使用單一 concurrency group，`cancel-in-progress=false`；前一輪未完成時，後一輪不得平行修改同一 queue。
- 正常完成必須同時看到 primary、secondary、tertiary 與 `finalize-home-status` 四個 job 成功。
- 日線 worker 每組每輪上限為 100 檔，仍受 FinMind 即時 quota、保留額度、請求 pacing、
  20 分鐘執行期限及 R2 object／byte guard 限制；不得用同一 token 開多個 worker。
- 實際封存量以 Supabase manifest 的 object、distinct symbol、row count 與 byte size 為準；GitHub artifact 只保存每個 worker 的執行摘要，不保存 Parquet 原始資料。
- 首頁 `historical_landing_count` 可以合計既有 Supabase landing 與最新 R2 logical slices，但 `historical_production_eligible_count` 在 point-in-time 驗證完成前必須保持 0。

## 資料集邊界

R2 object 依 `source_dataset` 使用獨立 schema 與 key prefix：

- `daily_bars`
- `adjusted_bars`
- `institutional_flows`
- `margin_short`
- `benchmark_total_return`

每一類資料都必須以自己的 schema version、metadata 與 row validator 驗證；不得把 benchmark
或籌碼資料套用日線 schema。研究 feature artifact 不是原始封存，也不得覆寫任何 raw object。
