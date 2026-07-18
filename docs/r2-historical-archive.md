# R2 歷史行情封存

歷史日線 R2 封存只由 GitHub Actions 排程 worker 執行，不是瀏覽器、Vercel runtime 或公開 API 的功能。輸出維持 `RESEARCH_ONLY`，不得直接進入正式推薦。

## 執行與憑證隔離

- 排程以三個獨立 job 執行，每個 job 只取得自己的 FinMind token：`FINMIND_TOKEN`、`FINMIND_TOKEN_SECONDARY` 或 `FINMIND_TOKEN_TERTIARY`。
- reusable workflow 明確傳入每一項 secret，不使用 `secrets: inherit`。任一 token 的失效或 quota 用盡不應讓其他 credential slot 共用或暴露該 token。
- `R2_ACCESS_KEY_ID`、`R2_SECRET_ACCESS_KEY`、FinMind token 及 `SUPABASE_SERVICE_ROLE_KEY` 只存於 GitHub Actions secrets。不得寫入 `.env.example` 的值、程式、artifact、log、commit、PR 或 Issue。
- R2 worker credential 只授予該 private archive bucket 的 Object Read & Write；bucket 管理、CORS 或 lifecycle 使用另一組 admin credential，且不得注入 worker。
- `R2_ACCOUNT_ID` 與 `R2_BUCKET_NAME` 可由 GitHub repository variables 傳入；它們不是存取憑證。worker 仍須同時取得完整的四項 R2 設定才會啟動。

## 儲存邊界

- R2 bucket 必須保持 private，不啟用 `r2.dev` 公開存取或 public custom domain。
- worker 透過 R2 的 S3-compatible HTTPS endpoint 寫入 immutable Parquet object；R2 client 固定使用 `region=auto`，並以已知 byte length 上傳及驗證 metadata、大小與 SHA-256。
- Supabase 只保存 `historical_archive_objects` manifest，包含 bucket、object key、來源期間、資料雜湊、Parquet 雜湊、列數、狀態及追蹤資訊；原始歷史列不複製進 PostgreSQL。
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
```

`.env.example` 只記錄名稱與空值；實際 secret 不得以明文保存或回傳。
