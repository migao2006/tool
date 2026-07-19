# Supabase 5 日 MVP 資料骨架

`market_data` 是只允許伺服器端 `service_role` 存取的研究資料 schema。它會註冊於 Data API，
但 `anon`／`authenticated` 沒有 schema 或資料表權限；`service_role` 絕不可放入瀏覽器或 Git。

以下檔案是可讀的 declarative schema 來源，供契約審查與新 migration 產生使用：

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
12. `012_security_listing_periods.sql`
13. `013_trading_calendar_observations.sql`

`012_security_listing_periods.sql` 將穩定掛牌期間識別碼
`listing_period_id` 與 append-only 證據列 `listing_evidence_id` 分開。
VERIFIED 列必須具有 ISIN，且 trigger 會同時核對 canonical security 的市場、
資產類型、股票代號與 ISIN；矛盾資料只能新增為 `CONFLICT`。

`013_trading_calendar_observations.sql` 要求 VERIFIED 交易日具有完整開盤、收盤
與決策資料截止時間，時間必須落在同一個台灣交易日；同市場同日期只允許一筆
VERIFIED 證據，避免重複修訂灌高就緒筆數。

上述兩個 schema 在非正式環境完成 migration 驗證前不得套用 Production。
既有 `securities` 仍有 `(market, symbol)` 唯一限制，因此同市場代號重用的完整
歷史身分遷移仍是後續工作；在完成前相關證據必須維持 UNRESOLVED／RESEARCH_ONLY。

實際資料庫版本只以 `supabase/migrations/` 為 source of truth，不得直接把本目錄
當作正式 migration 依序重跑。全新本機資料庫由
`20260717180000_initial_market_data_baseline.sql` 建立；該 baseline 具有
fail-closed guard，只允許空資料庫執行。

既有正式資料庫不得執行 baseline。必須先完成 schema 等價稽核，再把 baseline 版本
標記為已套用，且確認 migration 差異只包含尚未執行的 forward-only migration。
`004_contract_alignment.sql` 雖使用單一 transaction，仍不可因此假設所有 schema
檔案都能安全重跑。執行角色必須是 `market_data` 物件擁有者，才能讓
`ALTER DEFAULT PRIVILEGES` 套用到日後由同一角色建立的物件。

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

`security_listing_periods` 與 `trading_calendar_observations` 是 append-only 的 point-in-time
證據表。每一列都保留來源事件、revision、payload hash、原始列及 `available_at` 基礎。
`VERSIONED_SNAPSHOT` 只能從首次觀察時間起使用，不會回填成更早已知。`PASS / VERIFIED`
必須沒有 reason code；未解決或衝突列必須保留原因，狀態只能是 `RESEARCH_ONLY`
或 `FAIL`。

`security_listing_periods.source_name` 是來源當時顯示名稱，不是 canonical 名稱；`asset_type`
明確分開 `COMMON_STOCK` 與 `ETF`，`isin` 可空但有值時必須符合 12 碼格式。新的矛盾證據
必須追加成 `CONFLICT`，不得更新或覆寫既有 `VERIFIED` period。兩證據表沒有前端政策，
僅允許 `service_role` 新增及讀取，且 trigger 阻擋更新與刪除；既有 `security_history` 與
`trading_calendar` 不會被此契約改寫。
