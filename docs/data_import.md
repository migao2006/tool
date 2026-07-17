# 真實資料匯入要求

本次只建立空 schema，沒有插入股票、行情、模型輸出或回測假資料。

匯入順序：

1. `data_sources`
2. `trading_calendar`
3. `securities` 與 `security_history`
4. `daily_bars` 與 `corporate_actions`
5. 籌碼、融資券及國際市場 observations
6. `feature_snapshots`
7. 模型、驗證、推論與回測結果

每筆 fact 必須帶 `source_id`、`source_version`、`available_at` 與 `ingested_at`。修訂資料新增版本，不得直接覆寫歷史後假裝當時已知。

資料匯入使用伺服器端資料庫連線，憑證只放環境變數；不得把 Supabase `service_role`、secret key 或資料庫密碼寫入前端與 Git。

