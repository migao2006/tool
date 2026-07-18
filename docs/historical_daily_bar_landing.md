# Supabase 歷史日線原始落地區

`market_data.historical_daily_bar_landing` 逐列保存歷史日線來源資料與不可變稽核資訊。
它不是正式行情表，也不會依目前仍在使用的股票代號反向連到歷史 `security_id`。

此表保留既有資料與小批次稽核流程。排程產生的新多年完整行情改存 private Cloudflare R2
Parquet，Supabase 只保存 `historical_archive_objects` manifest；詳見
[`r2-historical-archive.md`](r2-historical-archive.md)。不得為了前端顯示再把 R2 全量原始列複製回此表。

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

## 自動漸進回補

`.github/workflows/backfill-historical-daily-bars.yml` 每小時第 17 分鐘啟動三個可續跑的
FinMind credential worker。固定單一 concurrency group 且不取消進行中的 workflow，避免不同
排程彼此重疊。只有 primary worker 建立共用任務清單；primary、secondary、tertiary 仍會透過
lease 安全並行認領不同股票。三個 worker 完成後，由單一 finalizer 更新首頁摘要。

任務順序固定為：

1. 上市普通股。
2. 上櫃普通股。
3. ETF。

只有前一層沒有待處理任務時才進入下一層。ETF 與普通股票分開建立任務，不會混入普通股票
模型資料。每次 workflow 預設最多處理 60 檔（每組 credential 最多 20 檔）；工作開始時先讀取 FinMind 額度，保留安全額度後依
可用請求數決定實際批次，並在請求之間節流。額度不足或接近執行期限時會安全停止，下一次
排程從未完成任務繼續，而不是重新抓取整批資料。

R2 模式使用單次 object 數與 object byte 上限保護儲存及執行時間，不再以 Supabase landing
relation 大小限制新封存。Supabase 仍保留 queue、manifest 及摘要；任何容量閘門觸發時都不會
刪除既有資料，也不會改用假資料填補。此門檻是安全上限，不是完整股票池已完成的證明。

自動回補和原本手動匯入使用相同原始資料及品質契約，但儲存 adapter 不同。所有結果仍固定為
`UNRESOLVED / UNVERIFIED / RAW_LANDING_ONLY / RESEARCH_ONLY`；在 security identity、公司
行動、point-in-time 股票池及正式驗證完成前，不得用於正式推薦、回測或績效宣稱。

手動啟動時只開放調整單次 `max_tasks`。日期範圍、額度保留、執行時間與容量上限由 workflow
固定，執行摘要保存為 90 天 artifact，供後續稽核實際進度、停止原因及錯誤。
