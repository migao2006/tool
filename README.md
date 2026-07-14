# 台股智選 v16.5

以台灣公開市場資料建立的 1～8 週機會股研究系統。核心不是把所有指標直接相加，而是依序執行：

1. 風險排除
2. 成長確認
3. 籌碼確認
4. 價量進場判斷
5. 估值與市場環境檢查
6. 點時快照回測

候選分數只是研究排序，不是買進訊號，也不保證未來報酬。

## v16.5：手動 Gemini AI 研究摘要

v16.5 沒有修改 v16.3 的量化公式、深度資料、機會分數、排行榜或趨勢預測。Gemini 是一條完全獨立的後端支線；股票明細只顯示「AI 研究摘要」按鈕，使用者按下後才讀取快取或產生新摘要。

- 取消自動候選篩選與平日 AI 排程；上市、上櫃、ETF 只要後端深度資料已完成，都可手動要求摘要。
- 開啟股票明細不會呼叫 AI；按下按鈕才會先查快取，沒有可用摘要時才呼叫 Gemini。
- 產生新摘要需要登入，單一帳戶每日預設最多 6 次；全站每日預設最多 12 次、資料庫硬上限 20 次，同時最多兩份。
- 輸入雜湊、模型與 schema 都沒變時直接回傳 14 天快取，不重複花費。
- AI 只能整理支持因素、風險、三種情境與後續觀察，禁止重算分數、目標價及買賣指令。
- 沒有設定 `GEMINI_API_KEY` 時會安全停用；原本網站、排行榜與 API 完全正常。
- AI 公開表只有 ready 摘要可讀，輸入快照、雜湊、執行紀錄與用量帳本不對訪客開放。

完整架構、成本閘門與啟用方式請見 [docs/AI-RESEARCH.md](docs/AI-RESEARCH.md)。

## v16.3 的關鍵改變

- 新增 Supabase Postgres 持久化後端。每日完整市場母體會先入庫，再由游標分批深度驗證；排行榜不再被單次 GitHub 工作流程的「每組 10 檔」上限鎖住。
- 上市、上櫃、ETF 使用三個獨立游標與錯開排程。冷資料每批無 Token 為 6／6／19 檔、有 Token 為 11／11／23；歷史已重用時公司批次可提高為 10／10 或 22／22。資料庫租約避免重複批次，失敗股票採持久化指數退避，未見過的股票不會被單一失敗標的阻塞。
- 每個完成深度驗證的公司股保存最多 280 日價量、40 月營收、12 季財務、30 日法人及 30 日融資融券；前端先讀後端，資料不足時才回退到原有即時來源。
- 前端顯示後端已驗證檔數與同步狀態；交易日切換會保留每檔最後成功驗證結果並標示日期，不會每日重新只剩第一批。GitHub 靜態檔只匯出同一份 v16.3 後端結果，舊模型快照不會冒充正式候選。
- 資料表全面啟用 RLS：訪客只有讀取公開研究資料的權限，批次寫入必須由 Vault 保管的同步權杖與伺服器密鑰完成。
- 修正季度營業額已入庫卻未輸出、應收帳款金額被 `_per` 百分比覆蓋、空摘要被永久重用，以及非價格 API 錯誤被誤存成 `ready` 的問題。
- 月營收全市場表若暫時漏掉仍在交易的公司，不再當成 0 或永久低分；上市／上櫃公司批次會保留一半名額，依序用逐檔歷史來源補回月營收與季度營業額。若逐檔來源也無資料，才標記為來源無紀錄。
- 資料信心現在會納入月營收月數、財報季數、價量日數與籌碼日數；新 ETF 未滿 120 個交易日不會進入正式榜。
- TWSE MIS 官方 ETF 檔補入估計淨值與折溢價；不可融資、去年同期營收為零、營收公布後未滿五日會標為「不適用／待觀察」，不再冒充 API 缺漏。

- 修正股票明細頁的市場路由：上櫃歷史行情由後端 `stock_price_history` 取得；排程使用目前帳號可用的 FinMind 原始行情並合併同日 TWSE／TPEx 官方盤後報價。若近 40 日出現超過 35% 的疑似除權、減資或分割跳空，系統會隔離技術評分，不會把未還原價格誤判成突破。
- 修正財報期間語意：FinMind 損益表已是單季值，不再重複差分；現金流量表的年內累計值才轉成單季。
- 現金轉換改採近四季 TTM 營業現金流 ÷ 近四季淨利，避免單季營運資金波動產生極端倍數；上櫃負現金流扣分依嚴重度分級。

- 上市、上櫃、ETF 完全分榜，不互相比較。
- 公司股採 100 分制：成長 30、籌碼 25、技術價量 25、估值 10、市場／產業 10，風險最多扣 30 分。
- 缺少資料時移除該項權重並重正規化，不把缺漏當成 0 分；同時獨立顯示資料信心。
- 資料信心低於 70%、最終分數低於 60，或命中硬性風險規則時，不進正式排行榜。
- 月營收深度驗證使用 48 個月請求範圍，正式需求至少 24 個月；計算年增、月增、累計年增、3 月平均年增、加速度、連續加速、近 12 月新高、歷年同期新高、季節性與公布後價格反應。
- 價量深度驗證保留最多 280 筆日線，計算 MA 5／10／20／60／120／240、斜率、突破、量能結構、ATR、RSI、MACD、KD、相對市場強弱與過熱距離。
- 籌碼計算外資／投信／自營商 5／10／20 日累計、連買天數、買超占量、融資使用率及融資融券變化；TDCC 每週資料只用於持股結構，不當成每日訊號。
- 財務品質使用最多 12 季損益、資產負債及現金流，檢查 EPS、利潤率、ROE、現金轉換、FCF、存貨、應收、負債、流動比率與利息保障。
- 會識別營運加速型、籌碼轉強型、落後補漲型；不符合時標為綜合觀察型。
- 回測只使用三組候選覆蓋率均達 75% 後封存的點時快照，至少累積 25 個交易日才公布；檢查 5／10／20 日報酬、超額報酬、勝率、最大有利走勢及最大回撤。

完整公式與欄位請見 [docs/METHODOLOGY.md](docs/METHODOLOGY.md)，資料稽核請見 [docs/API-AUDIT.md](docs/API-AUDIT.md)。

## 資料來源與用途

| 來源 | 用途 | 更新方式 |
| --- | --- | --- |
| TWSE 盤後介面／OpenAPI／MIS | 上市行情、估值、法人、融資融券、注意、處置、變更、停牌、市場指數、基金基本資料與 ETF 折溢價 | 當日快照 |
| TPEx OpenAPI | 上櫃行情、估值、法人、融資融券、注意、處置、變更、停牌、櫃買指數 | 當日快照 |
| MOPS 開放資料 | 最新月營收與六類財報快照 | 每月／每季 |
| FinMind 公開歷史資料 | 原始價量（含公司行動跳空隔離）、48 個月請求範圍（最多保存 40 月）營收、12 季財務／現金流、20 日法人與融資融券、TAIEX／TPEx 長期市場基準 | 僅由中央後端逐檔、限速排程 |
| TDCC 開放資料 | 每週集保戶股權分散 | 每週 |
| Supabase Postgres／Edge Function | 持久化價量、營收、財務、法人、融資與分析結果；保存同步游標 | 分批累積 |
| 原有 Supabase Edge | 全市場資料失效備援與既有使用者紀錄 | 備援 |

FinMind 請求以兩個並行通道、每 0.5 秒啟動一筆，在資料庫先寫入「滑動 60 分鐘」原子配額保留；排程重疊、手動重跑或基準備援都共用同一帳本。排程內不做同一請求的即時重送，失敗股票由下一輪依 `next_retry_at` 重試。無 Token 最多 300 次／60 分鐘，有 Token 最多 600 次／60 分鐘，不會在整點交界突發超額。市場基準與 TDCC 全市場檔每日持久重用。

上述上限已依 [FinMind 官方 Quick Start](https://finmind.github.io/quickstart/) 核對；Supabase Free plan Edge Function 的 150 秒 wall-clock 上限則依 [Supabase Functions Limits](https://supabase.com/docs/guides/functions/limits) 設計批次大小。請求數上限與單次函式時間是兩個不同限制，中央配額帳本會同時避免超量與批次過長。

## 持久化後端

目前正式後端已啟用。平日台北時間 14:43 更新全市場快照，三組深度工作每 20 分鐘各跑一次。冷資料無 Token 時上市／上櫃／ETF 每批最多為 6／6／19，有 Token 時最多為 11／11／23；新期別尚未出現時會重用營收與財報歷史，公司批次可提高到 10／10 或 22／22。實際數量仍由最近 60 分鐘剩餘額度與候選數決定。第一輪完整覆蓋需要時間；完成的檔案會立刻進入累積排行榜。

主要資料表：

- `stock_master`、`stock_snapshots`：全市場主檔與每日初篩快照
- `stock_price_history`、`stock_monthly_revenues`、`stock_quarterly_financials`
- `stock_institutional_flows`、`stock_margin_history`
- `stock_analysis_cache`、`opportunity_score_history`：目前榜單與歷史分數
- `ai_stock_research`、`ai_research_runs`、`ai_research_usage`：獨立 AI 摘要、批次紀錄與每日成本帳本
- `stock_sync_state`：上市／上櫃／ETF 的游標、進度與錯誤

資料庫建置檔位於 `supabase/migrations/`，批次程式位於 `supabase/functions/twss-sync-batch/`。完整結構、排程與重新部署方式請見 [docs/BACKEND.md](docs/BACKEND.md)。同步權杖與伺服器密鑰不可放進 GitHub；公開前端只使用 Supabase publishable key。

## 部署到 Supabase、GitHub 與 Vercel

1. 先執行 `npm test`。
2. 依 [docs/BACKEND.md](docs/BACKEND.md) 部署 Supabase migration、`twss-sync-batch` 與 `twss-ai-research`。既有專案因 v16.3 新增較早時間戳的 bootstrap migration，必須先 dry-run，再使用 `supabase db push --include-all`；全新專案使用一般 `supabase db push`。
3. 將本專案所有檔案上傳至 GitHub Repository，包含 `.github/`、`api/`、`public/`、`src/`、`scripts/`、`data/`、`supabase/` 與 `vercel.json`。
4. 在 Vercel 選擇 **Add New → Project**，匯入 Repository。
5. Framework Preset 選 **Other**，Root Directory 保持 `./`。
6. Build Command 使用 `npm run build`，Output Directory 使用 `public`。`vercel.json` 已把 `/api/*.js` 設為 300 秒，符合目前 Vercel Hobby Functions 上限。
7. 確認 Supabase 的 `stock_sync_state.details.version` 與排行榜 `analysis_version` 已是 v16.3 後，再在 GitHub **Actions** 執行一次 **Update Taiwan market snapshot → Run workflow**。

平日排程在台北時間 22:30 執行。它只從已受中央配額帳本保護的 Supabase 後端匯出 `public/data/latest.json` 與不可覆寫的 `data/snapshots/YYYY-MM-DD.json`，不會再從 GitHub Actions 額外直連 FinMind；Vercel 會因 GitHub commit 自動重新部署。GitHub 排程以 UTC 儲存且只在預設分支執行，實際啟動時間可能因 Actions 佇列略有延遲。

### 選用的環境變數

`FINMIND_TOKEN` 只應設在 Supabase Edge Function 的伺服器環境，不要放到公開前端或 GitHub Actions。沒有 Token 時中央帳本自動使用 300 次／60 分鐘上限；有 Token 時使用 600 次／60 分鐘上限。

Fork 或改用新 Supabase 專案時，可在 GitHub Repository Variables 設定公開的 `SUPABASE_URL` 與 `SUPABASE_PUBLISHABLE_KEY`；Vercel 也設定同名環境變數。它們不是伺服器密鑰，但資料表仍必須維持 RLS 與唯讀 grant。新專案還必須在部署 migration 前替換 SQL 排程 URL 與 `vercel.json` 的 CSP，完整清單見後端文件。

## 本機操作

需要 Node.js 20 或更新版本。

啟動本機完整頁面與 API：

```sh
npm run dev
```

```sh
npm test
```

從持久後端匯出靜態備援快照：

```sh
npm run export-data
```

`npm run update-data` 僅保留作開發診斷，不應與正式 Supabase 排程共用 Token 或放入自動排程。

```sh
SNAPSHOT_COMPANY_LIMIT=2 SNAPSHOT_ETF_LIMIT=3 npm run update-data
```

依已累積的每日快照重建無前視偏誤回測：

```sh
npm run backtest:snapshots
```

稽核目前各公開介面的日期與欄位：

```sh
npm run audit
```

## API

- `GET /api/market-data?type=stocks`
- `GET /api/market-data?type=revenue`
- `GET /api/market-data?type=financials`
- `GET /api/market-data?type=risks`
- `GET /api/market-data?type=benchmarks`
- `GET /api/market-data?type=etf-profiles`
- `GET /api/market-data?type=deep&symbol=2330&instrumentType=股票&market=上市`
- `GET /api/market-data?type=history&symbol=6613&market=上櫃&months=18`
- `GET /api/market-data?type=backend-rankings&limit=100`
- `GET /api/market-data?type=backend-status`
- `GET /api/market-data?type=ai-research&symbol=2330`
- `POST /api/ai-research`（需登入；body：`{"symbol":"2330"}`）
- `GET /api/market-data?type=sources`
- `GET /api/health`

`deep` 與 `history` 只讀持久後端，不會因 `refresh=1` 繞過中央 API 配額。其他官方全市場端點加入 `refresh=1` 可略過短期快取；日常使用不應頻繁加入。

AI 唯讀查詢找不到摘要時會回傳 HTTP 200 與 `available:false`；股票明細仍會顯示手動按鈕。只有按鈕送出的 `POST /api/ai-research` 才可能消耗一次 Gemini 額度。

## 目前不能假裝已取得的資料

ETF 估計淨值與折溢價使用 TWSE MIS 公開檔。追蹤誤差、完整內扣費用與成分集中度目前仍沒有已串接且格式一致的免金鑰來源；v16.3 會據實顯示缺口並降低 ETF 信心，不會拿公司基本面代替。

TDCC 公開下載檔提供目前一週的全市場持股級距；歷史趨勢必須靠每日快照逐週累積。產業 20 日相對強弱也必須靠持續快照建立，初期只使用市場指數與當日產業廣度。

## 免責聲明

本專案僅供資料研究與軟體示範，不構成投資建議、買賣邀約、報酬保證或任何受託管理。公開資料可能延遲、更正、缺漏或調整格式；使用者應在重要決策前回到原始公告核對。
