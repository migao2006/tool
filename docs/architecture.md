# 5 日 MVP 架構

```text
market_data facts
  -> point-in-time dataset + security master
  -> data quality / tradability hard gates
  -> shared executable-return labels and transaction costs
  -> rank / direction / quantile / market / volatility models
  -> probability and interval calibration
  -> decision policy (no final-score reweighting)
  -> staggered-cohort execution simulator
  -> auditable prediction and validation outputs
```

所有 Python 入口接受 `horizon`，但 production guard 目前只允許 `5`。未來 3、10、2 日各自使用 `artifacts/horizon_{h}`、獨立模型版本、標籤與驗證結果，不共用已訓練模型檔。

Supabase 的 `market_data` schema 是私有研究區。它只為伺服器端 `service_role` 註冊於 Data API，
`anon`／`authenticated` 均無權限；前端未來只應讀取經過驗證、欄位最小化且另有 RLS 的 read model。
