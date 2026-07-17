# 台股智選專案背景

## 0. 文件狀態

- 專案名稱：台股智選
- GitHub Repository：`migao2006/tool`
- 目前工作分支：`agent/v20-upgrade`
- Repository 應用版本：`v20.2.2`
- 本文件最後依原始碼核對日期：`2026-07-17`
- 已知正式網址：<https://smart-two-ochre.vercel.app>

版本、Commit、正式部署、資料日期及維護狀態都可能在本文件更新後改變。執行發布或正式環境操作前，必須分別向 GitHub、Vercel、Supabase 與公開 API 即時核對，不得只依本文件宣稱正式狀態。

## 1. 專案定位

台股智選是一套台股機會排序、資料研究與模型驗證平台。核心不是「AI 猜股票」，而是利用可追溯資料、量化規則與可驗證模型，回答：

1. 現在哪些股票相對值得進一步觀察。
2. 為什麼被選出來。
3. 哪些條件成立或失效。
4. 過去相同條件在成本與風險調整後的實際表現。

主要用途：

- 整合台股官方與第三方市場資料。
- 分析短波段與中期股票機會。
- 建立可追溯且不可直接修改的排行榜與推薦快照。
- 顯示資料完整度、模型校準狀態與缺漏來源。
- 提供個股研究、自選股及策略驗證功能。
- 協助使用者研究候選股票，不替使用者作投資決策。

本系統不是：

- 自動交易或自動下單系統。
- 投資代操系統。
- 保證獲利工具。
- 下一根 K 棒預測工具。
- 由大型語言模型直接決定排名或勝率的系統。

## 2. 主要使用者與裝置

主要使用情境：

- iPhone Safari。
- 手機直式 PWA。
- 單手操作。
- 桌面版作為管理與開發輔助。

介面設計優先考慮：

- 大型且清楚的觸控區域。
- 完整可見的資料日期、來源及狀態。
- 不遮擋內容並處理安全區的底部導覽。
- 避免過小文字、重疊及重要狀態被省略號截斷。
- 避免多欄內容在手機過度壓縮；必要時改為單欄或橫向捲動。
- 明確區分載入中、完整、部分資料、快取、過期、無資料及錯誤狀態。

## 3. 技術架構

### 前端

- Vanilla JavaScript。
- HTML5 與 CSS。
- PWA 與 Service Worker。
- LocalStorage 快取與帳戶隔離。
- 固定深色介面。

目前不使用 React、Next.js、Vue 或其他大型前端框架。不得為單一功能任意改寫整個前端架構。

### API 與背景工作

- Node.js `24.x`。
- Vercel Functions。
- Supabase Edge Functions，使用 Deno／TypeScript。
- Supabase PostgreSQL、RPC、Cron、Vault 與 RLS。

### CI 與部署

- GitHub Actions 負責測試、資料快照或既有自動化工作。
- 一個 Vercel 專案負責公開網站及 Vercel Functions。
- GitHub Actions 屬於 CI／自動化層，不是應用後端執行環境。

## 4. CORE 與 MARKET 資料庫

系統使用兩個獨立 Supabase PostgreSQL 專案。

### CORE

負責：

- 使用者登入與 Session。
- 帳戶資料。
- 訪客／登入使用者自選股同步。
- 一般使用者資料。
- `app_admins` 管理員身分名單。
- `twss_is_admin()` 等 CORE 權限判斷。

### MARKET

負責：

- 全市場盤後資料與歷史價量。
- 法人、融資融券、借券、月營收與財務資料。
- 市場環境、模型訊號與排行榜。
- Point-in-time 快照、回測、成熟結果與校準資料。
- 不可變推薦發布與公開 head。
- 資料健康、修復佇列、管理員操作日誌與維護狀態。
- Worker lease、配額帳本、背景工作及 Cron。

目前背景工作與管理員觀測以 `stock_sync_state`、enrichment／dirty queue、publication head 及不可變 run 為準。舊 `data_sync_status` 只屬相容性資料，不得單獨用來判定目前工作仍在執行或失敗。

CORE 與 MARKET 的 migration、環境變數、JWT、service role、RPC 與權限不得混用。管理員身分由 CORE 驗證；MARKET 的管理操作仍必須透過受保護的伺服器或 RPC 邊界執行。

## 5. 核心功能

### 首頁

首頁使用最近一次相容快照先顯示並在背景更新，主要呈現：

- 加權指數。
- 櫃買指數。
- 台指期。
- 市場環境及強弱尺度。
- 資料日期、各來源日期與更新狀態。
- 資料完整度與模型校準／信心狀態。
- 缺漏來源。
- 短波段與中期 Top 5。
- 每日量化摘要。
- 該不可變發布批次已保存的重要新聞與公告；未保存時明確顯示未收錄。

市場成交值因子使用 TWSE／TPEx 股票（排除 ETF）的同一母體，至少需要 5 個已完成交易日。`v20_market_context` 尚未累積足夠日期時，Worker 會從既有 `stock_price_history` 回補可驗證的歷史交易日；涵蓋率不足或查詢失敗時仍保留 `turnover_baseline` 缺漏，不補零。

### 短波段排行榜

觀察與驗證期間：

- 2 個交易日。
- 3 個交易日。
- 5 個交易日。
- 10 個交易日。

主要輸出：

- 原始機會分數。
- 成本後機會分數。
- 風險分數。
- 資料完整度及校準狀態。
- 策略類型、成立理由與失效條件。
- 建議研究期間。

### 中期排行榜

公開觀察與驗證期間：

- 10 個交易日。
- 20 個交易日。
- 40 個交易日。
- 10／20／40 日綜合排行，現行組成權重為 25%／50%／25%。

60 日訊號設定為 `research_only`，只供內部研究，不進入公開排行榜。中期模型不得直接沿用短波段總分、勝率、校準樣本或風險定義。

### 市場別與商品類型

畫面可提供「上市股票、上櫃股票、ETF」的快速篩選，但底層資料必須分成兩個維度：

- `market`：TWSE 或 TPEx。
- `instrument_type`：stock、ETF、ETN 等。

ETF 仍有自己的上市市場；不得把 TWSE、TPEx 與 ETF 當成互斥的原始資料欄位。

### 個股研究

依實際已保存資料可能包含：

- 歷史價量、趨勢、動能與技術指標。
- 法人籌碼、融資融券與借券。
- 月營收、財務品質與同業比較。
- 模型理由、風險、閘門與失效條件。
- 資料缺漏、來源日期、模型版本及發布識別。
- Fugle 的選用個股行情補充；行情補充不得改寫已封存模型訊號或排行榜。

### 自選股

支援：

- 訪客本機自選。
- 登入後雲端自選。
- 登入時合併訪客與帳戶資料。
- 依目前 publication 身分背景載入個股資料。

未經明確需求不得新增真實持股、成本、損益、交易紀錄或自動下單。既有 `portfolio_positions` 表及資料保留，但目前公開前端不讀寫。

### 策略驗證中心

包含或預留：

- Point-in-time 與 Walk-forward 驗證。
- 成本後報酬與超額報酬。
- MFE、MAE、最大回撤、換手率與樣本數。
- 成本後正報酬比例及信賴區間。
- 模型版本、期間與市場環境比較。

驗證引擎、資料表與唯讀摘要 API 已存在，但正式 MARKET 目前缺少可安全回溯的完整 v20 歷史特徵快照。因此不得倒灌今天的資料假造過去結果；歷史不足時回傳 `partial`／`insufficient_history`，每日正式訊號則持續累積成熟結果。有效樣本少於 100 或尚未校準時，不顯示推估勝率或期望報酬。

## 6. 不可變推薦架構

推薦批次完成後不得直接修改。需要修正時：

1. 建立新的 revision 或發布批次。
2. 執行資料、模型、成本與權限驗證。
3. 只有通過驗證的批次可以原子切換為公開 head。
4. 保留舊批次、舊結果與內容雜湊供稽核及比對。

重要識別資訊包括：

- run ID。
- publication key。
- revision。
- data date。
- model version／model release。
- cost policy version。
- content hash。
- generated at。
- source dates。

首頁、排行榜、個股、每日摘要及驗證資訊必須屬於相容的 publication；不得混用不同日期、run 或內容雜湊。

## 7. 主要資料來源

### TWSE

- 上市股票與 ETF 盤後行情。
- 加權指數。
- 三大法人、融資融券、注意、處置、變更與停牌資料。
- ETF 基本資料及可取得的估計淨值／折溢價資訊。

### TPEx

- 上櫃股票盤後行情。
- 櫃買指數。
- 三大法人、融資融券、注意、處置、變更與停牌資料。

### TAIFEX

- 台指期行情、契約月份、成交量及未平倉量。
- 一般盤與盤後盤辨識。

### MOPS

- 月營收。
- 損益表、資產負債表與現金流量表。
- 公司重大公告及公開資訊。

### TDCC

- 每週集保股權分散。
- 400 張以上及 10 張以下等持股結構。

TDCC 是週資料，不得冒充每日法人或買賣訊號。

### FinMind

- 歷史日線。
- 月營收及財務歷史。
- 法人、融資融券與借券歷史。
- 台指期或市場歷史備援。

FinMind 是歷史與深度資料補充來源。兩組不同 Token 可使用獨立配額帳本；Token 只能存在 Supabase Edge Function secrets 或 Vault，不得進入前端與 Git。

### Fugle MarketData

- 選用的個股行情補充。
- API 金鑰由 MARKET Supabase Vault 的 `fugle_marketdata_api_key` 提供，只能由 service role 取得。
- 個股行情採短期伺服器快取；失敗時安全退回已保存快照。
- 不得用 Fugle 即時行情覆寫不可變推薦的特徵、分數或歷史價格快照。

### Finnhub

- SPY：S&P 500 ETF 代理。
- QQQ：NASDAQ 100 ETF 代理。
- SOXX：SOX ETF 代理。
- TSM ADR。
- NVDA。
- VIXY：VIX ETF 代理。

SPY、QQQ、SOXX 與 VIXY 必須清楚標示為代理標的，不得冒充原始指數。

### Alpha Vantage

- 美國十年期公債殖利率。
- USD／TWD 匯率。

Finnhub 與 Alpha Vantage 都是選用國際背景資料；未設定伺服器金鑰時顯示缺漏，不使用假值或未核准端點替代。

## 8. 資料來源與備援順序

必須分開記錄「資料原始來源」與「系統目前從哪個保存層讀取」。Supabase 是保存與供應層，不會因資料存入 Supabase 就變成新的原始來源。

### 當日台股資料原始來源

1. TWSE、TPEx、TAIFEX 官方資料。
2. FinMind 或 Fugle 只在既定用途內補充，不得無標示取代官方發布。

### 讀取與備援

1. 與目前公開 head 完全一致的 MARKET 不可變快照。
2. 最近一次成功且通過 schema 檢查的 last-good snapshot，必須標示原始來源、實際資料日期及 `stale`／`cached` 狀態。
3. 若沒有可驗證快照，顯示缺漏或錯誤，不製造數值。

### 歷史資料

1. 已保存且保留來源／可用時間的 MARKET 歷史資料。
2. FinMind 歷史補充。
3. 官方可取得的歷史端點。

### 國際資料

1. Finnhub 或 Alpha Vantage。
2. 最近一次成功的伺服器快取，保留原始市場日期。
3. 顯示缺漏，不製造假資料。

## 9. 日期、時區與資料狀態

台灣市場使用 `Asia/Taipei`。美國市場資料必須保存原始美國市場日期，不能直接當成台灣交易日。

必須分開保存：

- 資料所屬日期／交易日期。
- 資料實際發布時間。
- API 取得時間。
- 模型計算時間。
- 推薦發布時間。
- 修訂或補抓時間。

TWSE、TPEx 與 TAIFEX 的日期必須個別核對。任一重要來源日期不一致時，整體狀態不得直接標示為完整。

常用狀態包括：

- `loading`／`refreshing`。
- `base_ready`／`enriching`。
- `complete`。
- `partial`。
- `cached`／`stale`。
- `error`。
- `source_not_returned`。
- `history_insufficient`／`insufficient_history`。
- `quota_waiting`。

狀態名稱應遵循實際 API 契約，不為了畫面文字任意改寫後端語意。不能僅因畫面已有數字就判定資料完整；完整度與信心必須在資料補齊後重新計算。

`publicationPhase: complete` 只表示該推薦批次已封存，不代表所有資料品質因子皆完整；公開畫面仍以 `dataState`、`degradedSources`、來源日期與完整度判斷是否顯示「部分資料不足」。

## 10. API 與快取

公開 v20 API：

- `GET /api/v20/home`
- `GET /api/v20/market`
- `GET /api/v20/rankings?model=short|medium&cursor=...`
- `GET /api/v20/stocks?symbol=2330`
- `GET /api/v20/backtest?model=short|medium`

API 回應依用途包含：

- `version`。
- `dataDate`、`fetchedAt` 與 `sourceDates`。
- `dataState` 與 `publicationPhase`。
- `completeness`、校準／信心狀態及 `degradedSources`。
- `runId`、`publicationKey`、`contentHash` 與 `modelVersion`。

排行榜快取身分至少包含模型、期間、市場、排序、搜尋條件、run ID、publication key、content hash、資料日期、schema 版本及前端 build 版本。

Service Worker 對 v20 API 採 network-first；畫面可以先顯示相容且有 TTL 的本機快取，但必須送出背景更新並套用新回應。網路失敗或逾時後，才能繼續顯示明確標示日期與狀態的 last-good cache。

## 11. 安全與權限

前端只能使用允許公開的 Supabase publishable key，且所有公開資料表及 RPC 必須配合 RLS、GRANT 與欄位白名單。

下列資訊只能存在伺服器端、Supabase Secrets／Vault 或安全環境變數：

- CORE／MARKET Supabase service role 或 secret key。
- FinMind Token。
- Fugle MarketData API Key。
- Finnhub API Key。
- Alpha Vantage API Key。
- 同步與內部更新權杖。
- 維護模式簽章秘密。
- 私有資料庫連線字串。

管理員 API 必須在伺服器端重新驗證登入身分與 `app_admins` 狀態，不能只依前端畫面或 LocalStorage 判斷。已出現在聊天、日誌或 Git 的真實金鑰應視為可能外洩並撤銷重發。

## 12. 既有設計限制

除非本次任務明確要求，否則不得：

- 改寫整個前端框架。
- 合併 CORE 與 MARKET。
- 刪除歷史推薦或既有正式資料。
- 修改已封存發布內容。
- 混合短波段與中期分數或校準樣本。
- 將不同市場或商品類型用錯誤欄位混成同一母體。
- 新增自動下單或保證獲利文字。
- 新增真實持股損益功能。
- 使用生成式 AI 決定正式排名。
- 使用假資料、零值或今天修正後的資料補齊歷史缺漏。

## 13. 正式環境與維護模式

本文件不保證目前正式網站是否已部署最新 Commit、是否處於維護模式或最新資料日期。需要變更正式環境時，依 `AGENTS.md` 及 `docs/V20-DELIVERY.md` 的維護狀態機執行並即時驗證；純閱讀、分析及本機文件修改不切換維護模式。
