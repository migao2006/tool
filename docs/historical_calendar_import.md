# 歷史交易日曆匯入

> 2026-07-19 核對：Production 舊 `trading_calendar` 有 2,077 筆 TWSE 日期（2018-01-02～2026-07-17），但開盤、收盤與 decision cutoff 全部為空；新 append-only observation migration 尚未上 Production。

這個模組只匯入來源實際回傳的交易日，不依星期幾推算交易或休市，也不猜測開收盤時間與資料截止時間。歷史上經交易所確認的週六交易日會保留。

## 目前契約

- 來源：FinMind `TaiwanStockTradingDate`
- 已驗證市場：TWSE
- TPEx：尚未驗證獨立來源契約，因此不匯入、不複製 TWSE 日期
- `available_at`：使用實際抓取時間，不回填成歷史日期
- 系統狀態：維持 `RESEARCH_ONLY`
- 防重：以 `market,trading_date` 冪等寫入，保留第一次寫入的時間

FinMind 只提供交易日期，因此 `opens_at`、`closes_at` 與
`decision_data_cutoff_at` 會保持空值。這些欄位未來只能由可稽核的交易所來源補齊。
目前資料表沒有逐列 `source_version`／payload hash，因此完整版本鏈仍待後續 migration；
匯入摘要會先保留來源 URI、版本與 SHA-256，系統不會因此升級為正式預測。

`20260719053500_trading_calendar_observations.sql` 目前要求任何 `is_trading_day=true` 列都具有完整開盤、收盤與 cutoff，因而也會阻擋只有日期的 `UNRESOLVED / SCHEDULING_HINT` FinMind 證據。正式套用前必須先在新 migration 修正這個契約，讓未解析日期證據可安全保存，同時維持 VERIFIED 列的完整時間要求。

## 本機驗證

本機需要 `FINMIND_TOKEN`。只有正式寫入時才需要 Supabase 的伺服器端金鑰。

```powershell
uv run python -m scripts.import_trading_calendar `
  --start-date 2018-01-01 `
  --dry-run
```

## GitHub Actions

工作流程 `Import historical trading calendar` 的手動執行預設為 dry-run。確認輸出的日期範圍、
筆數、來源網址、payload SHA-256 與 reason codes 後，才可將手動 dry-run 改為 false。

每週日台北時間 10:45 會自動執行正式冪等匯入，避開 10:15 的下市資料排程。
排程固定從 `2018-01-01` 重新核對至執行當日，只新增尚未保存的來源交易日，
既有資料仍由 `market,trading_date` 防重與 `preserve_existing` 保護。

每次執行會保存 90 天的 audit summary。摘要不包含 API 金鑰，也不代表模型已通過驗收。
