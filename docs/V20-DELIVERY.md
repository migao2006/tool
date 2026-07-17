# 台股智選 v20.2 交付與部署說明

## 升級原則

v20 是現有 Vanilla JavaScript PWA、Vercel Functions 與雙 Supabase 架構的增量升級。CORE 專案繼續負責登入、管理員與自選清單；MARKET 專案繼續保存市場、分析、排行榜與回測資料。升級不搬移、不重新命名、不刪除既有資料表，也不改變 v19 API。

v20.2 不提供真實持股、成本、損益、投資紀錄或下單功能。前台只保留自選股；既有 `portfolio_positions` 表與資料為相容性而保留，但不在使用者介面讀寫，也不執行破壞性刪除。

產品定位是可驗證的機會排序，不宣稱預知漲跌。量化規則與模型負責排序；語言模型只能整理新聞、解釋理由與指出矛盾。核心排名在語言模型服務不可用時仍可運作。

## 新增後端資料

MARKET 專案包含下列 v20 專用資料表：

- `v20_market_context`：市場環境與各來源實際資料日期。
- `v20_model_signals`：短期與中期模型的點時訊號。
- `v20_ranking_snapshots`：預先計算、可分頁讀取的排行榜。
- `v20_universe_membership`：回測當時的可交易母體，避免倖存者偏差。
- `v20_backtest_runs`、`v20_backtest_outcomes`：Walk-forward 執行與成熟結果。
- `v20_calibration_buckets`：依模型、期間、策略及市場環境保存的機率校準。
- `v20_signal_outcomes`：正式訊號成熟後，以次一交易日開盤進場及第 N 個交易日收盤評估的不可前視結果。
- `v20_recommendation_runs`、`v20_recommendation_items`：原子發布且不可修改的推薦執行與逐股 point-in-time 快照。
- `v20_outcome_observations`：只追加版本的成熟結果；修正以新 revision 表示，不覆寫舊觀測。
- `v20_publication_head`：唯一可變的公開指標，只指向已完整驗證並原子發布的 run。
- `v20_model_releases`、`v20_model_channel_heads`、`v20_model_validation_events`：模型版本與 Champion／Challenger 稽核軌跡。

歷史 v20 DDL、read-model hardening 與 DB-first pipeline 起點如下；實際部署必須先比對遠端 migration history，再將所有尚未套用且明確屬於 MARKET 的 migration 依時間順序 dry-run，不可只挑四個檔案，也不可把 CORE migration 套入 MARKET：

- `supabase/migrations/20260716021553_add_v20_quant_models.sql`
- `supabase/migrations/20260716024526_add_v20_signal_outcomes_calibration.sql`
- `supabase/migrations/20260716031500_harden_v20_public_read_model.sql`
- `supabase/migrations/20260716101225_add_db_first_enrichment_pipeline.sql`

v20.2 的關鍵 MARKET migration：

- `supabase/migrations/20260716173332_verifiable_opportunity_snapshots.sql`：不可變推薦快照、成本後欄位、模型版本通道與不可變結果。
- `supabase/migrations/20260716174105_operational_maintenance_control.sql`：維護狀態、Cron 精確暫停／恢復與稽核事件。
- `supabase/migrations/20260717083846_add_v20_medium_blend_rankings.sql`：不可變 10／20／40 日中期綜合排名與 keyset 分頁。
- `supabase/migrations/20260717090140_register_v20_2_model_release.sql`：v20.2 正確性修補的 Champion／Challenger 發布與回滾軌跡。

目前 repository 的歷史 migration 仍包含早期 CORE 與 MARKET 檔案；因此不得直接對任一 linked project 執行未檢查的 `db push --include-all`。部署者必須使用獨立目標清單或先完成 migration history reconciliation。

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

## 原子同日發布與不可變快照

`twss-v20-model` 不再分別尋找三個市場的「最新一日」。只有在 universe 的上市、上櫃、ETF `groupDates` 完全相同，且三個 `deep_*` 的 `completedCycleKey` 都明確完成該日後，才啟動 v20 模型。任何 mixed dates、缺組或空 cache 都回到 `pending`，不切換公開日期。

同一日期的全部訊號完成後，Worker 以 service-only `twss_v20_publish_recommendation_run` 在單一交易驗證 universe、三市場完成狀態、八個研究期間、公開／研究列數、資料完整度、終止錯誤與內容雜湊。驗證成功才新增不可修改的 run/items，並在同一交易切換 `v20_publication_head`。同日資料補齊會建立新的 revision 與 content hash，不覆寫已發布快照。

Vercel API 只以 service role 讀取 publication head 指向的 immutable items；公開端不能讀取 raw staging signal、legacy ranking RPC 或尚未發布的同日資料。游標綁定 publication key；發布版本改變後的舊游標會明確失效，避免跨版本混頁。

`GET /api/v20/home` 同時產生與 `publishedDataDate` 相同的 `v20-atomic-base-report`。舊的 `/data/daily-report.json` 只可作明確標示為 `cached` 的快速 fallback；它不能被標示為當日完成，也不能在背景回來時覆蓋同日 Base report，且不阻塞首頁其他內容。

## 模型與回測

- 短波段模型：2、3、5、10 個交易日；價量與趨勢 25%、法人籌碼 20%、相對強弱與產業動能 15%、波動與風險報酬 15%、市場環境 10%、營收與事件 10%、流動性與交易成本 5%。
- 中期模型：前台 10、20、40 個交易日（約 2～8 週）；營收與獲利成長 25%、財務品質 15%、中期趨勢 20%、法人與籌碼 15%、產業環境 10%、估值合理性 10%、流動性與風險 5%。60 日仍在後台研究，但 `research_only=true`，不進入公開排行。
- 兩套模型只共用點時原始特徵，不共用總分、門檻、風險、買點或停損。
- 推薦前依序檢查資料完整度、流動性、交易限制、市場環境、趨勢、相對強度、營運支撐與正交易期望值。
- 淨機會值以原始機會分數扣除動態交易成本、下跌風險與換手懲罰後再做市場相對排序。交易成本保存版本、手續費、交易稅、流動性／波動滑價與價差假設，不能只用固定常數。
- 核心研究函式在未校準或有效樣本少於 100 筆時，機率與預期超額報酬一律回傳 `null` 與「資料不足」，不可用公式初估冒充歷史勝率。
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
- `TWSS_INTERNAL_REFRESH_TOKEN`
- `MAINTENANCE_BYPASS_SECRET`
- `MAINTENANCE_MODE`
- `MAINTENANCE_FAIL_CLOSED`

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
4. 比對 MARKET 遠端 migration history，只對尚未套用的 MARKET migration 做 transaction dry-run；先套用 v20 不可變快照，再依版本套用後續 migration。不要直接 `db push --include-all`，也不要在 CORE 專案套用市場表 migration。
5. 執行 Supabase Security 與 Performance Advisor，確認資料表、RLS、RPC 與排程，再以 Vault 授權分別做小批次 Base 及 Enrichment 驗證。
6. 部署 Vercel API 與 UI，確認所有公開端點指向同一 `publishedDataDate`。
7. 驗證首頁、排行榜、個股、管理員與既有 v19 API 後恢復排程，最後移除維護模式。

### 維護狀態機

Production 在維護資料表缺少或查詢失敗時預設 fail-closed。首次套用維護 migration 也會以 `draining` 啟動，避免 schema 與程式版本切換時短暫開站。所有指令都需要 MARKET service role 環境變數；變更狀態的指令另需明確附加 `--confirm`：

```sh
npm run maintenance:status
npm run maintenance:enter -- --confirm
npm run maintenance:verify -- --confirm
npm run maintenance:signature -- verify
npm run maintenance:reclose -- --confirm
npm run maintenance:resume -- --confirm
```

`enter` 先關閉全站，等待 edge cache 收斂，再保存並暫停 Cron。`verify` 會再次捕捉部署期間新增或替換的 Cron，保留首次快照後進入驗證狀態；網站對一般使用者仍回 503。短效 HMAC `verify-get` 只允許兩分鐘內的唯讀 GET 冒煙測試，不能繞過 POST。測試失敗執行 `reclose`；全部通過才執行 `resume`，在同一資料庫交易恢復原 Cron 狀態並開站。

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
- 五個底部分頁為首頁、短波段、中期機會、自選股、策略驗證中心；沒有獨立預測頁及投資紀錄入口。
- 全站固定深色，不保存主題選項。
- 短期與中期分數、條件及風險可同時呈現不同結論。
- 排行榜採游標分頁；首頁只取得摘要及 Top 股票。
- 自選股仍可登入同步；一般使用者看不到管理員功能。
- 所有資料顯示實際交易／分析／新聞日期，不以程式執行時間冒充交易日。
- Base 完成後即可發布可用內容，Enrichment 在背景補齊；頁面依 `publicationPhase` 顯示目前階段，不因補齊工作阻塞。
- 首頁、排行榜、個股與每日市場報告必須使用同一 immutable publication；混合日期或未完成 Base 不得切換公開指標。
- v19 API、CORE 資料、MARKET 舊表與既有 Edge Functions 均保持可用。

## 尚未完成與選用項目

- `src/v20-backtest.js` 的 point-in-time Walk-forward 引擎、測試、資料表與唯讀摘要 API 已完成；但正式 MARKET 專案尚無可安全回溯的歷史 v20 特徵快照，因此本次不捏造歷史結果，也不把現有資料倒灌成過去訊號。`v20_backtest_runs`／`v20_backtest_outcomes` 初期為空，API 會回傳 `partial`／`insufficient_history`。正式歷史 backfill runner 是後續項目；每日正式訊號則由 `v20_signal_outcomes` 持續累積真實成熟結果與校準。
- S&P 500、NASDAQ 100、SOX、台積電 ADR、NVIDIA、VIX、美債殖利率與 USD/TWD 屬選用國際資料。只有伺服器端設定 `FINNHUB_API_KEY`／`ALPHA_VANTAGE_API_KEY` 並以內部授權觸發更新時才顯示；未設定時明確列為待補，不使用 Yahoo 非正式端點或假值。加權、櫃買與台指期仍沿用既有已驗證資料來源並逐卡顯示來源及日期。
- Supabase Advisor 對沒有 client policy 的內部 v20 表可能提出 INFO；這些表刻意採 RLS deny-by-default 且只授權 `service_role`。v20.2 的推薦、個股與驗證讀取 RPC 僅回傳白名單欄位；瀏覽器角色不能讀 raw staging、不可變 outcome 明細或管理通道。

## 回滾

1. 重新切換維護模式，避免回滾期間產生混合版本寫入。
2. 停用 `twss-deep-listed`、`twss-deep-otc`、`twss-deep-etf`、`twss-enrichment-weekday`、`twss-v20-model-weekday` 與 `twss-v20-model-weekday-final` 六個新排程。
3. 將 `twss-sync-batch` 與 `twss-v20-model` 部署回上一個已驗證版本，並還原先前 deep／v20 排程定義。
4. 將 Vercel production alias 回指上一個成功部署，確認 v19 API 與管理員功能正常後再移除維護模式。
5. 保留本次新增的 additive 資料表、欄位、索引與已寫入資料，不執行破壞性刪表或跨專案搬移；既有兩個 Supabase 專案及分工完全不變。

本系統只提供量化研究、機會篩選與風險評估，不保證獲利，也不把統計機率描述為確定結果。
