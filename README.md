# 台股智選 v20.2.1

台股智選是一套可驗證的台股機會排序、個股研究、資料品質管理與策略驗證系統。它以不可變的 point-in-time 推薦快照作為公開讀取來源，分開計算短波段與中期候選，並納入交易成本、下跌風險及換手懲罰。

本專案不提供自動交易、投資代操或獲利保證。大型語言模型只負責整理與解釋，不直接決定正式排名、勝率或買賣分數。

## 文件導覽

- [AGENTS.md](AGENTS.md)：AI 與自動化工具必須遵守的固定規則。
- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md)：目前架構、資料來源、模型與限制。
- [TASK_TEMPLATE.md](TASK_TEMPLATE.md)：每次修改任務的簡短模板。
- [docs/V20-DELIVERY.md](docs/V20-DELIVERY.md)：v20 部署、維護模式、驗收與回滾。
- [docs/METHODOLOGY.md](docs/METHODOLOGY.md)：量化方法、成本、校準與驗證原則。
- [docs/BACKEND.md](docs/BACKEND.md)：持久化後端、資料表、排程與權限。
- [docs/API-AUDIT.md](docs/API-AUDIT.md)：資料來源、限制與稽核紀錄。

## 主要功能

- 台股市場環境首頁。
- 短波段 2／3／5／10 交易日機會排行榜。
- 中期 10／20／40 交易日及綜合機會排行榜；60 日只供內部研究。
- 上市股票、上櫃股票與 ETF 篩選。
- 個股研究、風險、失效條件與來源日期。
- 訪客及登入帳戶自選股。
- Point-in-time／Walk-forward 策略驗證中心。
- 不可變推薦批次、revision、內容雜湊與公開 head。
- 管理員資料健康、修復、模型與維護狀態觀測。
- iPhone Safari、手機直式 PWA 與桌面版。

歷史 v20 特徵尚未累積足夠時，策略驗證 API 會回傳 `partial`／`insufficient_history`；系統不會倒灌今天的資料假造過去績效。

## 技術架構

### 前端

- Vanilla JavaScript。
- HTML5 與 CSS。
- PWA、Service Worker 與 LocalStorage 快取。

### API 與背景工作

- Node.js 24.x。
- Vercel Functions。
- Supabase Edge Functions（Deno／TypeScript）。
- Supabase PostgreSQL、RLS、RPC、Cron 與 Vault。

### CI 與部署

- GitHub Actions。
- Vercel。
- 目前維持一個 Vercel 專案。

### 資料庫

- Supabase CORE：登入、帳戶、自選股、使用者資料與管理員身分。
- Supabase MARKET：市場、模型、排行榜、回測、不可變發布、管理日誌及維護狀態。

CORE 與 MARKET 的 migration、環境變數、service role、JWT 與權限不可混用。

## 環境需求

- Node.js 24.x。
- npm。
- Git。
- Supabase CLI：只有資料庫或 Edge Function 工作需要。

確認版本：

```bash
node --version
npm --version
git --version
supabase --version
```

## 安裝

```bash
git clone https://github.com/migao2006/tool.git
cd tool
npm ci
```

建立本機環境檔：

```bash
# macOS / Linux
cp .env.example .env.local

# Windows PowerShell
Copy-Item .env.example .env.local
```

`.env.example` 只包含無效範例值。不要把任何真實憑證提交到 Git。

## 環境變數與 Secrets

實際需求依執行的元件而定；完整清單及部署位置請以 [docs/V20-DELIVERY.md](docs/V20-DELIVERY.md) 和原始碼為準。

### 公開讀取設定

```text
SUPABASE_URL
SUPABASE_PUBLISHABLE_KEY
MARKET_SUPABASE_URL
MARKET_SUPABASE_PUBLISHABLE_KEY
```

Publishable key 可出現在前端，但資料表及 RPC 仍必須使用 RLS、GRANT 與欄位白名單保護。

### 僅限伺服器端

```text
MARKET_SUPABASE_SERVICE_ROLE_KEY
MARKET_SUPABASE_SECRET_KEY
SUPABASE_SERVICE_ROLE_KEY
FINNHUB_API_KEY
ALPHA_VANTAGE_API_KEY
TWSS_V20_INTERNAL_KEY
TWSS_INTERNAL_REFRESH_TOKEN
MAINTENANCE_BYPASS_SECRET
```

通用 `SUPABASE_SERVICE_ROLE_KEY` 只作既有程式的相容備援；雙專案環境應優先使用明確的 MARKET／CORE 設定，避免連錯專案。

### Supabase Edge Function／Vault

```text
FINMIND_TOKEN
FINMIND_TOKEN_SECONDARY
SUPABASE_SECRET_KEYS
```

Fugle MarketData 金鑰保存於 MARKET Supabase Vault，既有 secret 名稱為 `fugle_marketdata_api_key`。不得把 Fugle、FinMind 或其他第三方金鑰放進前端、GitHub 原始碼或公開環境變數。

### 維護模式

```text
MAINTENANCE_MODE
MAINTENANCE_FAIL_CLOSED
MAINTENANCE_BYPASS_SECRET
MAINTENANCE_ACTOR
MAINTENANCE_REASON
```

已出現在聊天、日誌或 Commit 的真實金鑰應視為可能外洩並撤銷重發。

## 本機執行

啟動本機頁面與 API：

```bash
npm run dev
```

列出所有實際可用指令：

```bash
npm run
```

## 建置與測試

基本建置及產物驗證：

```bash
npm run build
npm run validate
```

依修改範圍執行相關測試，例如：

```bash
npm run test:v20-api
npm run test:v20-global
npm run test:admin-observability
npm run test:maintenance
```

完整回歸：

```bash
npm test
```

瀏覽器端到端測試：

```bash
npm run test:e2e
```

Smoke test：

```bash
npm run smoke
```

依賴安全稽核：

```bash
npm audit
```

`npm run audit` 執行的是正式／公開資料端點稽核，和 npm 依賴安全稽核不同。只有在已授權且環境正確時執行：

```bash
npm run audit
```

測試逾時、失敗、中止或未執行時，不得宣稱通過。本機測試通過也不代表正式部署已驗證。

## 公開 API

v20 主要 API：

```text
GET /api/v20/home
GET /api/v20/market
GET /api/v20/rankings?model=short|medium&cursor=...
GET /api/v20/stocks?symbol=2330
GET /api/v20/backtest?model=short|medium
GET /api/health
```

既有 v19／市場資料 API 仍需維持相容；修改前請先確認現有呼叫端及測試。

## Supabase 資料庫

### CORE

只能套用與登入、帳戶、自選股、使用者資料及管理員身分相關的 CORE migration。

### MARKET

只能套用與市場資料、模型、排行榜、回測、發布快照、管理觀測及維護狀態相關的 MARKET migration。

套用 migration 前：

1. 確認目前連線的 Supabase project ref。
2. 比對遠端 migration history。
3. 確認 migration 屬於 CORE 或 MARKET。
4. 檢查 RLS、GRANT、RPC、索引及破壞性操作。
5. 執行 transaction dry-run 或等效驗證。
6. 準備 rollback、roll-forward 或備份還原方案。
7. 正式變更前進入維護模式。

不得在未確認目標專案與歷史狀態時直接執行：

```bash
supabase db push --include-all
```

完整 migration 順序見 [docs/V20-DELIVERY.md](docs/V20-DELIVERY.md)。

## Supabase Edge Functions

本機執行與部署範例：

```bash
supabase functions serve
supabase functions deploy <FUNCTION_NAME>
supabase secrets set KEY=value
```

執行前必須確認目標 Supabase 專案。Secret 不得寫進命令紀錄、程式碼或 Git；若終端會保存歷史，應改用核准的秘密管理流程。

## 維護模式與正式部署

純閱讀、分析及本機修改不切換正式站維護模式。正式部署、migration、資料回填或直接寫入正式資料前，依序使用：

```bash
npm run maintenance:status
npm run maintenance:enter -- --confirm
npm run maintenance:verify -- --confirm
npm run maintenance:signature -- verify
npm run maintenance:reclose -- --confirm
npm run maintenance:resume -- --confirm
```

標準流程：

1. `status` 核對目前狀態。
2. `enter` 關站、等待快取收斂並暫停 Cron。
3. 完成本機驗證、migration、Edge Function 與 Vercel 更新。
4. `verify` 進入仍對一般使用者回 503 的受控驗證階段。
5. 驗證失敗執行 `reclose`；全部通過才執行 `resume`。

完整部署與回滾步驟見 [docs/V20-DELIVERY.md](docs/V20-DELIVERY.md)。上傳 GitHub 分支不等於已授權合併或部署 production；Vercel 自動部署規則必須在操作前核對。

## 部署後驗收

- 首頁及五個底部分頁可正常載入。
- 首頁、排行榜、個股與每日摘要使用相同 publication。
- 資料日期、來源日期與同步時間語意正確。
- 排行榜期間、市場、搜尋及排序快速切換不被舊請求覆蓋。
- iPhone Safari／PWA 無水平捲動或底部導覽遮擋。
- 管理員權限同時通過前端、後端、RLS 與 RPC 驗證。
- Service Worker 已使用新 build，舊 schema 快取正確失效。
- API 空值、過期資料、部分資料及上游錯誤不會被顯示為數值 0 或成功狀態。

## 主要資料來源

- TWSE。
- TPEx。
- TAIFEX。
- MOPS。
- TDCC。
- FinMind。
- Fugle MarketData：選用個股行情補充。
- Finnhub：選用國際 ETF／ADR／股票代理資料。
- Alpha Vantage：選用美債殖利率及匯率資料。

台股當日資料以官方來源為優先；第三方資料主要用於歷史補充、個股行情補充與國際市場背景。快取必須保留原始來源及日期，不能冒充最新官方資料。

## 開發流程

開始修改前閱讀：

1. [AGENTS.md](AGENTS.md)。
2. [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md)。
3. 本 README。
4. 本次任務及相關程式碼與測試。

可複製 [TASK_TEMPLATE.md](TASK_TEMPLATE.md) 描述任務。一般交付直接提交並上傳授權的工作分支，不產生 ZIP；合併、正式部署與資料庫變更仍需獨立授權。

## 風險聲明

本專案提供資料整理與模型研究，不構成投資建議。任何模型、排行或研究結果都不保證未來報酬。

第三方 API、官方資料發布時間、歷史修正、網路狀況與部署平台限制，都可能影響資料完整性及更新時間。進行重要決策前，應回到原始官方來源核對。
