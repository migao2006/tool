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

完整 DDL、read-model hardening 與 DB-first pipeline 位於以下四個 migration，必須依檔名順序套用：

- `supabase/migrations/20260716021553_add_v20_quant_models.sql`
- `supabase/migrations/20260716024526_add_v20_signal_outcomes_calibration.sql`
- `supabase/migrations/20260716031500_harden_v20_public_read_model.sql`
- `supabase/migrations/20260716101225_add_db_first_enrichment_pipeline.sql`

所有 `public` 表均啟用 RLS；公開讀取表只授權 `SELECT`，內部回測與結果表只允許 `service_role`。個股非排行訊號只能透過固定模型版本、單一股票且最多 8 筆的 sanitized RPC 讀取。新增資料表使用明確 `GRANT`，不依賴 Supabase 新專案的預設 Data API 權限。

`twss-v20-model` Edge Function 以分批、冪等 Upsert 方式產生訊號與排行榜。上市、上櫃、ETF 各自保存資料日、游標與進度；單檔失敗會進入有上限的重試佇列並被隔離，不會回滾同批其他股票。由於既有 `pg_cron` 不會帶使用者 JWT，Function 關閉 Gateway JWT 驗證，但每次請求仍必須先通過既有 Vault 私密同步權杖的 `twss_verify_sync_token()` 驗證；前端不能取得同步權杖或 service role 金鑰。

## DB-first 兩階段處理

盤後處理保留原本兩個 Supabase 專案與既有表的用途，新增以下兩個階段：

1. **Base（資料庫優先）**：`twss-sync-batch` 先將 TWSE／TPEx 官方同日價量、法人與融資融券資料批次寫入既有歷史表，再透過 `twss_analysis_inputs` 一次載入所需歷史，在記憶體計算並批次 Upsert `stock_analysis_cache`。Base 不逐檔呼叫 FinMind，也不等待借券或缺漏歷史補齊。
2. **Enrichment（背景補齊）**：`stock_enrichment_queue` 依日期、資料集與優先序保存缺漏工作；FinMind 配額、429、暫時錯誤、租約與重試只影響該工作。補齊後同日模型可以冪等重算，既有 Base 頁面持續可用。

Base 會沿用下列既有正規化表：`stock_price_history`、`stock_monthly_revenues`、`stock_quarterly_financials`、`stock_institutional_flows`、`stock_margin_history`。本次只新增：

- `stock_lending_history`：借券歷史；主鍵為 `(symbol, trade_date)`。
- `stock_enrichment_queue`：每日補齊工作；`(symbol, data_date, dataset_key)` 唯一，狀態為 `pending`、`running`、`success` 或 `error`。

兩表皆啟用 RLS、沒有 `anon`／`authenticated` policy，並明確撤銷公開權限；只允許 `service_role` 存取。既有資料不搬移、不刪除，也不在兩個 Supabase 專案間交換用途。

新增或擴充的 service-only RPC：

- `twss_analysis_inputs(...)`：批次取得價格、營收、財報、法人、融資融券與借券歷史。
- `twss_claim_enrichment_batch(...)`：以 `FOR UPDATE SKIP LOCKED` 原子領取工作。
- `twss_complete_enrichment(...)`、`twss_fail_enrichment(...)`、`twss_release_enrichment(...)`：完成、重試／終止及配額未取得時釋放租約。
- `twss_enrichment_summary(date)`：回傳 total、pending、running、success、error、retryableErrors、terminalErrors、unresolved、complete 與各資料集統計。
- `twss_claim_sync_lease(...)`：既有租約 RPC 向後相容更新；Base 與 v20 model 的安全租約下限為 420 秒。
- `twss_admin_operations_log(...)`：保留原 payload 並增補 `enrichmentQueue`、`baseAnalysis` 與 `publication`；仍只允許已驗證管理員查看。

## 原子同日發布

`twss-v20-model` 不再分別尋找三個市場的「最新一日」。只有在 universe 的上市、上櫃、ETF `groupDates` 完全相同，且三個 `deep_*` 的 `completedCycleKey` 都明確完成該日後，才啟動 v20 模型。任何 mixed dates、缺組或空 cache 都回到 `pending`，不切換公開日期。

同一日期的全部訊號完成後，`twss_v20_refresh_rankings` 先在資料庫交易內重建排行榜；成功後才更新 `stock_sync_state.details.publishedDataDate` 與 publication metadata。Vercel API 使用此 server-only pointer 讀取 home、market、short、medium、rankings 與 stock，因此使用者只會看到上一個完整日期或新完整日期，不會看到半套資料。Enrichment 進度 fingerprint 改變時可同日重新 Upsert 訊號及覆蓋排行榜，不產生重複列。

`GET /api/v20/home` 同時產生與 `publishedDataDate` 相同的 `v20-atomic-base-report`。舊的 `/data/daily-report.json` 只可作明確標示為 `cached` 的快速 fallback；它不能被標示為當日完成，也不能在背景回來時覆蓋同日 Base report，且不阻塞首頁其他內容。

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

所有回應保留既有的 `dataState`、`dataDate`、`sourceDates`、`fetchedAt`、`completeness` 與 `degradedSources`，並向後相容增補 `publicationPhase`、`baseCompletedAt`、`enrichmentCompletedAt`、`enrichmentPending` 與 `dataCompleteness`。`sourceDates` 用來逐一揭露實際來源日期；`publicationPhase` 只使用 `cached`、`base_ready`、`enriching`、`complete`。既有 `dataState` 仍可為 `cache`、`refreshing`、`complete`、`partial`、`error`，舊客戶端不需要修改即可繼續使用。

`GET /api/v20/home` 另包含與公開 `dataDate` 完全相同的 `dailyReport`。單一來源失敗時保留最近成功資料並透過 metadata 標示，不讓整頁失效，也不把不同日期的報告與排行榜混合顯示。

v19 API 及既有 `/api/market-data` 保持原路徑與格式。

## 環境變數

只列名稱，不在文件、程式碼、日誌或版控中保存任何值：

- `SUPABASE_URL`
- `SUPABASE_PUBLISHABLE_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_SECRET_KEYS`
- `FINMIND_TOKEN`
- `ALPHA_VANTAGE_API_KEY`
- `FINNHUB_API_KEY`
- `TWSS_V20_INTERNAL_KEY`
- `TWSS_V20_BATCH_LIMIT`

`SUPABASE_SECRET_KEYS` 與 `FINMIND_TOKEN` 只供 Supabase Edge Functions 使用；`SUPABASE_SERVICE_ROLE_KEY`、國際資料金鑰及內部金鑰都只限伺服器端；`TWSS_V20_BATCH_LIMIT` 為選用批次上限。Vault 使用既有 secret 名稱 `twss_sync_token`，本文件不記錄其值。

國際資料金鑰缺少、達限或來源失敗時，API 必須列入 `degradedSources`，不能產生替代假值。所有私密值只設定在 Vercel／Supabase 的 Secret 管理介面，不提交到 GitHub，也不加任何公開前綴。

## 排程

DB-first migration 在 MARKET 專案建立或取代以下 UTC 排程：

- `twss-deep-listed`：`*/2 7-15 * * 1-5`，Base 上市批次上限 200。
- `twss-deep-otc`：`*/2 7-15 * * 1-5`，Base 上櫃批次上限 200。
- `twss-deep-etf`：`*/2 7-15 * * 1-5`，Base ETF 批次上限 200。
- `twss-enrichment-weekday`：`1,5,11,15,21,25,31,35,41,45,51,55 7-15 * * 1-5`，背景補齊批次上限 50。
- `twss-v20-model-weekday`：`*/2 7-15 * * 1-5`，v20 模型批次上限 250。
- `twss-v20-model-weekday-final`：`59 15 * * 1-5`，收尾批次上限 250。

上述時段換算台北時間為平日 15:00 至 23:59。既有 17:10 與 21:10 universe reconciliation 維持不變；Base、Enrichment 與 v20 model 均使用租約避免重疊執行。

## 部署順序

1. 先切換維護模式，暫停舊的 deep／v20 排程，或確認沒有作用中的同步租約。
2. 依「測試」章節完成本機驗證。
3. 在 MARKET 專案部署新版 `twss-sync-batch` 與 `twss-v20-model`，但在 schema 尚未完成前不呼叫；不要部署到 CORE 專案。
4. 依檔名順序在 MARKET 專案套用四個 migration，最後套用 `20260716101225_add_db_first_enrichment_pipeline.sql` 以建立新增表、RPC 並取代相關排程。不要在 CORE 專案套用市場表 migration。
5. 執行 Supabase Security 與 Performance Advisor，確認資料表、RLS、RPC 與排程，再以 Vault 授權分別做小批次 Base 及 Enrichment 驗證。
6. 部署 Vercel API 與 UI，確認所有公開端點指向同一 `publishedDataDate`。
7. 驗證首頁、排行榜、個股、管理員與既有 v19 API 後恢復排程，最後移除維護模式。

## 測試

部署前依序執行：

- `npm run build`
- `npm run validate`
- `npm run test:pipeline`
- `npm run test:data`
- `npm run test:v20-worker`
- `npm run test:v20-api`
- `npm run smoke`
- `npm test`

測試涵蓋 Base 階段不呼叫 FinMind、混合日期拒絕發布、Enrichment queue 的冪等領取／重試、排行榜與公開 pointer 的原子切換、首頁 daily report 與公開日期一致，以及舊靜態報告只能作明確 `cached` fallback。`npm test` 為最後完整回歸，包含模型、API、PWA、管理員及既有 v19 相容性。

## 驗收重點

- 首頁先顯示快取或靜態快照，再局部更新，不出現長時間全螢幕 Loading。
- 五個底部分頁為首頁、短期、中期、自選、AI 分析；沒有獨立預測頁及投資紀錄入口。
- 全站固定深色，不保存主題選項。
- 短期與中期分數、條件及風險可同時呈現不同結論。
- 排行榜採游標分頁；首頁只取得摘要及 Top 股票。
- 自選股仍可登入同步；一般使用者看不到管理員功能。
- 所有資料顯示實際交易／分析／新聞日期，不以程式執行時間冒充交易日。
- Base 完成後即可發布可用內容，Enrichment 在背景補齊；頁面依 `publicationPhase` 顯示目前階段，不因補齊工作阻塞。
- 首頁、排行榜、個股與 AI 每日報告必須使用同一 `publishedDataDate`；混合日期或未完成 Base 不得切換公開指標。
- v19 API、CORE 資料、MARKET 舊表與既有 Edge Functions 均保持可用。

## 尚未完成與選用項目

- `src/v20-backtest.js` 的 point-in-time Walk-forward 引擎、測試、資料表與唯讀摘要 API 已完成；但正式 MARKET 專案尚無可安全回溯的歷史 v20 特徵快照，因此本次不捏造歷史結果，也不把現有資料倒灌成過去訊號。`v20_backtest_runs`／`v20_backtest_outcomes` 初期為空，API 會回傳 `partial`／`insufficient_history`。正式歷史 backfill runner 是後續項目；每日正式訊號則由 `v20_signal_outcomes` 持續累積真實成熟結果與校準。
- S&P 500、NASDAQ 100、SOX、台積電 ADR、NVIDIA、VIX、美債殖利率與 USD/TWD 屬選用國際資料。只有伺服器端設定 `FINNHUB_API_KEY`／`ALPHA_VANTAGE_API_KEY` 並以內部授權觸發更新時才顯示；未設定時明確列為待補，不使用 Yahoo 非正式端點或假值。加權、櫃買與台指期仍沿用既有已驗證資料來源並逐卡顯示來源及日期。
- Supabase Advisor 對沒有 client policy 的內部 v20 表會提出 INFO；這些表刻意採 RLS deny-by-default 且只授權 `service_role`。兩個公開 SECURITY DEFINER RPC 均為固定 SQL、固定 v20.0、無動態 SQL，並分別限制為單一股票最多 8 筆及最多 500 個匿名彙總，不提供原始內部 outcome 列。

## 回滾

1. 重新切換維護模式，避免回滾期間產生混合版本寫入。
2. 停用 `twss-deep-listed`、`twss-deep-otc`、`twss-deep-etf`、`twss-enrichment-weekday`、`twss-v20-model-weekday` 與 `twss-v20-model-weekday-final` 六個新排程。
3. 將 `twss-sync-batch` 與 `twss-v20-model` 部署回上一個已驗證版本，並還原先前 deep／v20 排程定義。
4. 將 Vercel production alias 回指上一個成功部署，確認 v19 API 與管理員功能正常後再移除維護模式。
5. 保留本次新增的 additive 資料表、欄位、索引與已寫入資料，不執行破壞性刪表或跨專案搬移；既有兩個 Supabase 專案及分工完全不變。

本系統只提供量化研究、機會篩選與風險評估，不保證獲利，也不把統計機率描述為確定結果。
