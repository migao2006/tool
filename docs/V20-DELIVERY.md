# 台股智選 v20 交付與部署說明

## 升級原則

v20 是現有 Vanilla JavaScript PWA、Vercel Functions 與雙 Supabase 架構的增量升級。CORE 專案繼續負責登入、管理員與自選清單；MARKET 專案繼續保存市場、分析、排行榜與回測資料。升級不搬移、不重新命名、不刪除既有資料表，也不改變 v19 API。

v20 不提供真實持股、成本、損益、投資紀錄或下單功能。部位試算只使用當次輸入，重新整理後即清除，不寫入 Local Storage 或 Supabase。

## 新增後端資料

MARKET 專案新增下列 v20 專用資料表：

- `v20_market_context`：市場環境與各來源實際資料日期。
- `v20_model_signals`：短期與中期模型的點時訊號。
- `v20_ranking_snapshots`：預先計算、可分頁讀取的排行榜。
- `v20_universe_membership`：回測當時的可交易母體，避免倖存者偏差。
- `v20_backtest_runs`、`v20_backtest_outcomes`：Walk-forward 執行與成熟結果。
- `v20_calibration_buckets`：依模型、期間、策略及市場環境保存的機率校準。
- `v20_signal_outcomes`：正式訊號成熟後，以次一交易日開盤進場及第 N 個交易日收盤評估的不可前視結果。

完整 DDL 與 read-model hardening 位於以下三個 migration，必須依檔名順序套用：

- `supabase/migrations/20260716021553_add_v20_quant_models.sql`
- `supabase/migrations/20260716024526_add_v20_signal_outcomes_calibration.sql`
- `supabase/migrations/20260716031500_harden_v20_public_read_model.sql`

所有 `public` 表均啟用 RLS；公開讀取表只授權 `SELECT`，內部回測與結果表只允許 `service_role`。個股非排行訊號只能透過固定模型版本、單一股票且最多 8 筆的 sanitized RPC 讀取。新增資料表使用明確 `GRANT`，不依賴 Supabase 新專案的預設 Data API 權限。

`twss-v20-model` Edge Function 以分批、冪等 Upsert 方式產生訊號與排行榜。上市、上櫃、ETF 各自保存資料日、游標與進度；單檔失敗會進入有上限的重試佇列並被隔離，不會回滾同批其他股票。由於既有 `pg_cron` 不會帶使用者 JWT，Function 關閉 Gateway JWT 驗證，但每次請求仍必須先通過既有 Vault 私密同步權杖的 `twss_verify_sync_token()` 驗證；前端不能取得同步權杖或 service role 金鑰。

## 模型與回測

- 短期模型：2、3、5、10 個交易日；技術 20%、量價 20%、法人 15%、市場 15%、產業 10%、事件 10%、基本面安全 5%、流動性 5%。
- 中期模型：20、40、60 個交易日；成長 25%、產業 20%、法人 15%、趨勢 15%、估值 10%、財務安全 10%、事件 5%。
- 兩套模型只共用點時原始特徵，不共用總分、門檻、風險、買點或停損。
- 推薦前依序檢查資料完整度、流動性、交易限制、市場環境、趨勢、相對強度、營運支撐與正交易期望值。
- 核心研究函式在樣本不足時回傳 `null` 與「資料不足」。正式背景 Worker 初期可使用固定公式、可重現的 `deterministic-quant-bootstrap` 估計，但 API 與 UI 必須標成「規則初估（待校準）」，不可冒充歷史勝率；成熟結果累積後才切換為 Walk-forward 校準值。
- 回測使用 Walk-forward 與 point-in-time 資料，收盤訊號最早以次一交易日可成交價格進場，並納入手續費、交易稅、價差與滑價。
- 成熟訊號評估會保存 MFE、MAE、固定持有期結果與交易計畫結果；同一根 OHLC 同時觸及停損及停利時，採保守的停損優先。

## 公開 API

- `GET /api/v20/home`
- `GET /api/v20/market`
- `GET /api/v20/rankings?model=short|medium&cursor=...`
- `GET /api/v20/stocks?symbol=2330`
- `GET /api/v20/backtest?model=short|medium`

所有回應提供 `dataState`、`dataDate`、`sourceDates`、`fetchedAt`、`completeness` 與 `degradedSources`。允許的狀態為 `cache`、`refreshing`、`complete`、`partial`、`error`。單一來源失敗時保留最近成功資料，不能讓整頁失效。

v19 API 及既有 `/api/market-data` 保持原路徑與格式。

## 環境變數

保留既有名稱：

- `SUPABASE_URL`
- `SUPABASE_PUBLISHABLE_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`（只限伺服器）

v20 選用的伺服器端金鑰：

- `ALPHA_VANTAGE_API_KEY`
- `FINNHUB_API_KEY`
- `TWSS_V20_INTERNAL_KEY`

國際資料金鑰缺少、達限或來源失敗時，API 必須列入 `degradedSources`，不能產生替代假值。所有私密值只設定在 Vercel／Supabase 的 Secret 管理介面，不提交到 GitHub，也不加任何公開前綴。

## 部署順序

1. 執行 `npm test`，確認模型、API、PWA、管理員與既有 v19 測試全數通過。
2. 先在 MARKET 專案部署 `twss-v20-model`（不呼叫）；不要部署到 CORE 專案。
3. 依檔名順序在 MARKET 專案套用三個 v20 migration；第二個提供成熟結果 RPC，第三個提供單一股票 read model、固定 v20.0 的公開回測彙總及高容量排程。不要在 CORE 專案套用市場表 migration。
4. 執行 Supabase Security 與 Performance Advisor，修正本次新增物件造成的問題，再以 Vault 授權請求做一次小批次驗證。
5. 推送 GitHub 功能分支，驗證 Vercel Preview 的五頁 UI、API 與手機版面。
6. 推送 `main` 觸發正式部署；驗證完成後才移除維護導向。

## 驗收重點

- 首頁先顯示快取或靜態快照，再局部更新，不出現長時間全螢幕 Loading。
- 五個底部分頁為首頁、短期、中期、自選、AI 分析；沒有獨立預測頁及投資紀錄入口。
- 全站固定深色，不保存主題選項。
- 短期與中期分數、條件及風險可同時呈現不同結論。
- 排行榜採游標分頁；首頁只取得摘要及 Top 股票。
- 自選股仍可登入同步；一般使用者看不到管理員功能。
- 所有資料顯示實際交易／分析／新聞日期，不以程式執行時間冒充交易日。
- v19 API、CORE 資料、MARKET 舊表與既有 Edge Functions 均保持可用。

## 尚未完成與選用項目

- `src/v20-backtest.js` 的 point-in-time Walk-forward 引擎、測試、資料表與唯讀摘要 API 已完成；但正式 MARKET 專案尚無可安全回溯的歷史 v20 特徵快照，因此本次不捏造歷史結果，也不把現有資料倒灌成過去訊號。`v20_backtest_runs`／`v20_backtest_outcomes` 初期為空，API 會回傳 `partial`／`insufficient_history`。正式歷史 backfill runner 是後續項目；每日正式訊號則由 `v20_signal_outcomes` 持續累積真實成熟結果與校準。
- S&P 500、NASDAQ 100、SOX、台積電 ADR、NVIDIA、VIX、美債殖利率與 USD/TWD 屬選用國際資料。只有伺服器端設定 `FINNHUB_API_KEY`／`ALPHA_VANTAGE_API_KEY` 並以內部授權觸發更新時才顯示；未設定時明確列為待補，不使用 Yahoo 非正式端點或假值。加權、櫃買與台指期仍沿用既有已驗證資料來源並逐卡顯示來源及日期。
- Supabase Advisor 對沒有 client policy 的內部 v20 表會提出 INFO；這些表刻意採 RLS deny-by-default 且只授權 `service_role`。兩個公開 SECURITY DEFINER RPC 均為固定 SQL、固定 v20.0、無動態 SQL，並分別限制為單一股票最多 8 筆及最多 500 個匿名彙總，不提供原始內部 outcome 列。

## 回滾

1. 將 Vercel production alias 回指 v19.2 的最後成功部署。
2. 保留 v20 新資料表與資料，不執行破壞性刪表；v19 不會讀取它們。
3. 停用 `twss-v20-model-weekday` 排程或將 v20 Worker Function 回滾；`TWSS_V20_INTERNAL_KEY` 只控制 Vercel 端選用的國際資料更新，不控制 Supabase Worker。既有同步仍可獨立運作。
4. 若 Edge Function 有問題，部署上一個已驗證版本；不要重設或重建任一 Supabase 專案。

本系統只提供量化研究、機會篩選與風險評估，不保證獲利，也不把統計機率描述為確定結果。
