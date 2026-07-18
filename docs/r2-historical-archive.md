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
- Supabase 只為新 R2 封存保存 `historical_archive_objects` manifest，包含 bucket、object key、來源期間、資料雜湊、Parquet 雜湊、列數、狀態及追蹤資訊；新封存的原始歷史列不複製進 PostgreSQL。既有 landing rows 保留，不做破壞性搬移。
- object 驗證成功後才寫 manifest。既有 object 或 manifest 必須以相同 key 冪等處理；驗證失敗時 fail closed，排程 task 進入 retry。

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
- 實際封存量以 Supabase manifest 的 object、distinct symbol、row count 與 byte size 為準；GitHub artifact 只保存每個 worker 的執行摘要，不保存 Parquet 原始資料。
- 首頁 `historical_landing_count` 可以合計既有 Supabase landing 與最新 R2 logical slices，但 `historical_production_eligible_count` 在 point-in-time 驗證完成前必須保持 0。
