# Supabase 5 日 MVP 資料骨架

`market_data` 是只允許伺服器端 `service_role` 存取的研究資料 schema。它會註冊於 Data API，
但 `anon`／`authenticated` 沒有 schema 或資料表權限；`service_role` 絕不可放入瀏覽器或 Git。

執行順序：

1. `001_market_facts.sql`
2. `002_research_outputs.sql`
3. `003_validation_and_security.sql`
4. `004_contract_alignment.sql`
5. `005_data_api_service_role.sql`
6. `006_security_snapshot_contract.sql`
7. `007_corporate_action_provenance.sql`
8. `008_benchmark_contract.sql`
9. `009_delisting_registry.sql`
10. `010_historical_daily_bar_landing.sql`
11. `011_historical_r2_archive_manifest.sql`

全新專案依序執行十一個檔案。既有專案需依序補上尚未執行的檔案；這些 migration
均可安全重跑，且
`004_contract_alignment.sql` 以單一 transaction 套用，失敗時不會留下
部分變更，且可安全重跑。執行角色必須是 `market_data` 物件擁有者，才能讓
`ALTER DEFAULT PRIVILEGES` 同時套用到日後由同一角色建立的物件。

所有可修訂的 point-in-time 事實表都保留 `available_at`、來源與來源版本。
`feature_snapshots` 與 `prediction_runs` 以資料庫約束強制
`latest_available_at <= decision_at`；`data_quality_audits` 另以 trigger 對照所屬
prediction run，阻擋晚於 `decision_at` 的稽核資料。

本 schema 只建立空表與約束，不含股票、行情、預測或回測假資料。未來若要讓前端讀取正式輸出，應另外建立小型、唯讀且具 RLS 的 API view，不應直接公開原始訓練資料。

`historical_daily_bar_landing` 與 `historical_daily_bar_quarantine` 只保存尚未完成身分及
point-in-time 驗證的來源列與問題。它們不含 `security_id`，也不會外鍵連到正式
`securities` 或 `daily_bars`；資料只能標示為 `RAW_LANDING_ONLY / RESEARCH_ONLY`。

`historical_backfill_tasks` 只管理自動回補的排序、lease、重試及斷點。任務股票池來自
目前可見的 security master，只能作為排程依據，不會讓歷史落地資料取得 point-in-time
資格。此佇列只由版本化 migration 建立，不維護第二份重複 SQL。

`historical_archive_objects` 是 private Cloudflare R2 Parquet object 的 service-role-only
manifest，只保存位置、來源期間、雜湊、列數、品質狀態及版本 metadata。新 R2 封存的完整
原始列不複製進 PostgreSQL；object 與 manifest 驗證完成也不會自動取得正式模型使用資格。
