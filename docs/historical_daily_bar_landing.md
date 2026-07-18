# 歷史日線原始落地區

`market_data.historical_daily_bar_landing` 逐列保存歷史日線來源資料與不可變稽核資訊。
它不是正式行情表，也不會依目前仍在使用的股票代號反向連到歷史 `security_id`。

- 每一來源列都有包含 revision hash 的 deterministic `landing_key`、payload／row hash 與來源列序號。
- `PARSED` 只代表欄位格式及 OHLC 契約通過，不代表身分或 point-in-time 已驗證。
- `QUARANTINED` 列仍保留完整 `source_row`；每個問題另寫入
  `historical_daily_bar_quarantine`，同一列可有多個 `reason_code`。
- `source_market_claim` 只能保留來源直接聲明的市場，並將 `source_market_basis` 設為
  `SOURCE_ASSERTED`；缺少來源聲明時市場必須為 null，basis 必須為 `UNAVAILABLE`。
- 全部資料固定為 `UNRESOLVED / UNVERIFIED / RAW_LANDING_ONLY / RESEARCH_ONLY`，不得直接
  用於正式特徵、標籤、推薦、回測或模型績效。

兩張表均啟用 RLS，撤銷 `public`、`anon` 與 `authenticated` 權限，只允許伺服器端
`service_role` 存取。`service_role` 不得放入前端或 Git。

## 有界驗證流程

先執行只讀探測，不保存原始行情：

```powershell
python -m scripts.probe_finmind_historical `
  --symbols "2330,2317" `
  --start-date 2021-07-19 `
  --end-date 2026-07-17 `
  --output data/raw/finmind-historical-probe.json
```

再執行 landing dry run；只有明確加上 `--write` 才會寫入 Supabase：

```powershell
python -m scripts.import_historical_daily_bars `
  --symbols "2330,2317" `
  --start-date 2021-07-19 `
  --end-date 2026-07-17 `
  --output data/raw/historical-daily-bar-import.json
```

GitHub 的兩個手動 workflow 皆限制最多 20 檔、最長 5 年。預設試批股票來自目前可見
股票池，因此稽核結果固定包含 `REQUEST_UNIVERSE_NOT_POINT_IN_TIME`；它不能用來證明
歷史股票池完整，也不能消除生存者偏誤。
