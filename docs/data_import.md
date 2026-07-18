# 真實資料匯入要求

目前已建立正式資料契約，並匯入真實但仍屬 `RESEARCH_ONLY` 的市場資料；新多年日線原始列
封存於 private Cloudflare R2，Supabase 保存 queue、manifest 與摘要。專案沒有插入假股票、
假行情、假模型輸出或假回測績效。

匯入順序：

1. `data_sources`
2. `trading_calendar`
3. `securities` 與 `security_history`
4. `daily_bars` 與 `corporate_actions`
5. 籌碼、融資券及國際市場 observations
6. `feature_snapshots`
7. 模型、驗證、推論與回測結果

多年歷史日線採可續跑任務佇列漸進匯入，優先順序固定為上市普通股、上櫃普通股、ETF。
三個隔離的 FinMind credential worker 依各自剩餘額度節流並保留安全額度；只有 primary worker
建立共用任務清單，三個 worker 仍可並行下載，最後由單一 finalizer 更新首頁摘要。

新回補的完整原始列以 ZSTD 壓縮 Parquet 寫入 private Cloudflare R2；Supabase 只保存 queue、
object manifest、資料品質、版本與摘要。達到執行期限、額度或 R2 單次 object／byte 上限時停止，
由後續排程接續。原始資料在身分與時間稽核完成前一律維持
`UNVERIFIED / RAW_LANDING_ONLY / RESEARCH_ONLY`。

不受 FinMind token 額度控制的官方 current OpenAPI 匯入使用有界平行下載：全域最多 4 個、
同一 provider 最多 2 個同時請求。日行情、證券快照、公司行動與基準資料會先完成全部下載
及驗證，再進入原有資料庫寫入階段；不得用無上限 concurrency 換取速度或造成部分批次寫入。

每筆 fact 必須帶 `source_id`、`source_version`、`available_at` 與 `ingested_at`。修訂資料新增版本，不得直接覆寫歷史後假裝當時已知。

資料匯入使用伺服器端資料庫連線，憑證只放環境變數；不得把 Supabase `service_role`、secret key 或資料庫密碼寫入前端與 Git。
