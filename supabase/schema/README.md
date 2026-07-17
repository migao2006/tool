# Supabase 5 日 MVP 資料骨架

`market_data` 是未對前端 Data API 公開的研究資料 schema。資料匯入、訓練、推論與回測應由受控的伺服器工作使用 `service_role` 執行；`service_role` 絕不可放入瀏覽器或 Git。

執行順序：

1. `001_market_facts.sql`
2. `002_research_outputs.sql`
3. `003_validation_and_security.sql`
4. `004_contract_alignment.sql`

全新專案依序執行四個檔案。已建立前三個檔案的既有專案只需執行
`004_contract_alignment.sql`；該檔案以單一 transaction 套用，失敗時不會留下
部分變更，且可安全重跑。執行角色必須是 `market_data` 物件擁有者，才能讓
`ALTER DEFAULT PRIVILEGES` 同時套用到日後由同一角色建立的物件。

所有可修訂的 point-in-time 事實表都保留 `available_at`、來源與來源版本。
`feature_snapshots` 與 `prediction_runs` 以資料庫約束強制
`latest_available_at <= decision_at`；`data_quality_audits` 另以 trigger 對照所屬
prediction run，阻擋晚於 `decision_at` 的稽核資料。

本 schema 只建立空表與約束，不含股票、行情、預測或回測假資料。未來若要讓前端讀取正式輸出，應另外建立小型、唯讀且具 RLS 的 API view，不應直接公開原始訓練資料。
