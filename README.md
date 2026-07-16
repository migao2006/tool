# 台股智選 v20.0.0

v20 在既有系統上增量加入完全獨立的短期（2／3／5／10 日）與中期（20／40／60 日）量化模型、Walk-forward 回測、預先計算排行榜及五頁手機介面。首頁採快取／靜態資料優先與背景局部更新，全站固定深色；沒有獨立預測頁、投資紀錄、持股成本或損益管理。既有 API、登入、管理員功能，以及 CORE／MARKET 兩個 Supabase 專案的用途與資料均保持不變。

完整交付、部署與回滾說明請見 [docs/V20-DELIVERY.md](docs/V20-DELIVERY.md)。

---

# 台股智選 v18.0.0

以台灣公開市場資料建立的 1～8 週機會股研究系統。核心不是把所有指標直接相加，而是依序執行：

1. 風險排除
2. 成長確認
3. 籌碼確認
4. 價量進場判斷
5. 估值與市場環境檢查
6. 點時快照回測

候選分數只是研究排序，不是買進訊號，也不保證未來報酬。

### v18.0.0 CORE／MARKET 雙專案

- 使用者登入、預測與自選清單改由獨立 CORE Supabase 專案負責；大量市場資料仍保留在 MARKET。
- 主網站與獨立管理後台使用不同的工作階段儲存位置，CORE JWT 不會送往 MARKET。
- 本機使用者資料依帳戶 UUID 隔離；空白雲端結果也會正確清空該帳戶畫面，避免跨帳戶殘留。
- 自選清單的新增與刪除會同步至 CORE。

### v17.3.3 晚間日期校正修復

- 正式資料庫補上平日 17:10、21:10 的全市場日期校正排程，避免 14:43 首次同步停在前一交易日。
- 管理頁會檢查校正排程是否存在並啟用，明確區分「日期待同步」與「校正排程缺失」。
- 日期換日後重新建立上市、上櫃與 ETF 的同日分析週期。

### v17.3.2 手機首頁顯示穩定性修復

- 關閉 Safari／PWA 的自動捲動還原，避免重新開啟時把舊位置套回首頁。
- 首次市場資料完成後會穩定回到頁首，切換功能頁時也不會沿用上一頁的位置。
- 關閉首頁非同步重畫的捲動錨定，避免基本面資料完成時將市場摘要推到固定頁首後方。

### v17.3.1 日期同步與管理版面修復

- 全市場後台保留 14:43 的初次收盤後同步，另於台北時間 17:10、21:10 執行日期校正，避免官方來源尚未換日便把後台停在前一交易日。
- 上市與上櫃日期不同時，不再以較新日期冒充全市場完成日；首頁會分別標示兩市日期，整體狀態維持部分資料。
- 管理頁分開顯示上市行情日、上櫃行情日、後台全市場日與三組共同分析日，並在落後時明確顯示待同步。
- 切換頁面與開啟管理後台會回到頁首；管理時間固定使用台北時區，成功狀態色彩亦已修正。
- 靜態資產與 Service Worker 快取升至 v17.3.1。

### v17.3.0 管理員後台

- 登入後會由 `twss_is_admin()` 即時查核 `app_admins`；只有啟用中的管理員會看到「管理後台」入口。
- 管理頁透過 `twss_admin_operations_log()` 顯示資料健康、同步工作、修復佇列、來源缺漏、API 額度與最近事件。
- 未登入者與一般登入帳號均無法讀取管理 RPC；即使自行修改前端或 Local Storage，後端仍會拒絕。
- 管理資料只保存在目前頁面的記憶體，登出、撤權或授權失敗會立即清除，不寫入 PWA 快取或靜態 JSON。
- 登出會先撤銷 Supabase Session，再移除本機 Session；v17.3.0 首次加入獨立管理員後台。

### v17.2.2 管理診斷修復

- 一般使用者介面不再載入或顯示資料健康中心；來源缺漏、修復進度與同步錯誤只寫入受保護的 Supabase Edge Function 管理日誌。
- 移除公開 `data-health` 與 `backend-status` 路由，健康／缺漏 RPC 改為僅限 `service_role`，並撤銷訪客直接讀取 `stock_sync_state` 的權限。
- `stock_analysis_cache` 改用欄位級讀取權限，公開研究結果維持可用，原始錯誤、重試與修復欄位不再透過 Data API 暴露。
- 靜態資產與 Service Worker 快取升至 v17.2.2，避免已安裝的 PWA 繼續顯示舊入口。

### v17.2.1 快速修復

- TPEx 當日端點暫時失敗時，會從 Supabase 最近一次官方快照補回上櫃母體，不再顯示「上櫃 0」。每檔仍保留自己的交易日期，整體狀態維持部分資料，不會把前一日資料冒充當日行情。

## v17.2：免費公開資料長期架構與研究比較

v17.2 延續 v17.1 的免費公開資料架構，長期運作只依賴台灣公開市場資料、FinMind 公開額度與 Supabase 免費層。量化核心、深度資料、機會分數、排行榜與趨勢預測仍沿用已驗證的 v16.3 固定公式，不因介面版本升級而改寫。

- 新增同市場候選比較：上市、上櫃與 ETF 不混合，一次最多比較 4 檔，並排檢查資料日期、信心、缺漏、風險及該組適用指標。
- 新增 UTF-8 CSV 匯出，可匯出目前比較表或上市／上櫃／ETF 各自的深度排行榜；只整理既有結果，不重新計分，也不增加外部 API 請求。

- 資料來源日期仍會在個股研究內容中顯示；全域涵蓋率、修復佇列與缺漏分類改由管理員後台日誌保存，不提供給一般使用者。
- 排名與分數變化只比較已完成封存的整組排行榜；未完成的當日批次不會被誤當成正式排名。
- 同業比較由後端限定在相同市場與相同產業；同產業樣本少於 5 檔時，才退回同市場比較。上市、上櫃與 ETF 永遠不混合。
- 後端持續保存正式榜前 10 名的 5／10／20 日結果。訊號在收盤後產生，因此固定使用次一交易日開盤價進場，並計算報酬、超額報酬、MFE 與 MAE；每組每個期間未滿 25 個成熟訊號日以前只顯示累積進度。
- 自選股規則提醒完全在裝置端計算與保存，涵蓋分數門檻、正式候選、前 10 名、營收加速、法人轉正、突破、過熱與資格失效，不使用推播或外部付費服務。

## v16.3 的關鍵改變

- 新增 Supabase Postgres 持久化後端。每日完整市場母體會先入庫，再由游標分批深度驗證；排行榜不再被單次 GitHub 工作流程的「每組 10 檔」上限鎖住。
- 上市、上櫃、ETF 使用三個獨立游標與錯開排程。冷資料每批無 Token 為 6／6／19 檔、有 Token 為 11／11／23；歷史已重用時公司批次可提高為 10／10 或 22／22。資料庫租約避免重複批次，失敗股票採持久化指數退避，未見過的股票不會被單一失敗標的阻塞。
- 每個完成深度驗證的公司股保存最多 280 日價量、40 月營收、12 季財務、30 日法人及 30 日融資融券；前端先讀後端，資料不足時才回退到原有即時來源。
- 前端只顯示排行榜已累積的驗證檔數與各筆研究日期，不顯示同步工作、修復佇列或錯誤狀態；交易日切換仍會保留每檔最後成功驗證結果並標示日期，不會每日重新只剩第一批。GitHub 靜態檔只匯出同一份 v16.3 後端結果，舊模型快照不會冒充正式候選。
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
- 回測只使用上市、上櫃與 ETF 在同一精確交易日均已完成 final cycle，且保存官方開盤價的點時快照。每組、每個 5／10／20 日期間都要累積至少 25 個成熟訊號日才公布統計；未達門檻的報酬、勝率、超額報酬、MFE 與 MAE 一律保持空值。

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

FinMind 請求以兩個並行通道、每 0.5 秒啟動一筆，在資料庫先寫入「滑動 60 分鐘」原子配額保留；排程重疊、手動重跑或基準備援都共用同一帳本。排程內不做同一請求的即時重送，失敗股票由下一輪依 `next_retry_at` 重試。未登入最多 300 次／60 分鐘；每組已驗證 Token 各自最多 600 次／60 分鐘。設定兩個不同帳號的 Token 後，背景補齊會以獨立帳本交錯執行，合計上限最多 1,200 次／60 分鐘，仍不會在整點交界突發超額。市場基準與 TDCC 全市場檔每日持久重用。

上述上限已依 [FinMind 官方 Quick Start](https://finmind.github.io/quickstart/) 核對；Supabase Free plan Edge Function 的 150 秒 wall-clock 上限則依 [Supabase Functions Limits](https://supabase.com/docs/guides/functions/limits) 設計批次大小。請求數上限與單次函式時間是兩個不同限制，中央配額帳本會同時避免超量與批次過長。

## 持久化後端

目前正式後端已啟用。平日台北時間 14:43 更新全市場快照，三組深度工作每 20 分鐘各跑一次。冷資料無 Token 時上市／上櫃／ETF 每批最多為 6／6／19，有 Token 時最多為 11／11／23；新期別尚未出現時會重用營收與財報歷史，公司批次可提高到 10／10 或 22／22。實際數量仍由最近 60 分鐘剩餘額度與候選數決定。第一輪完整覆蓋需要時間；完成的檔案會立刻進入累積排行榜。

主要資料表：

- `stock_master`、`stock_snapshots`：全市場主檔與每日初篩快照
- `stock_price_history`、`stock_monthly_revenues`、`stock_quarterly_financials`
- `stock_institutional_flows`、`stock_margin_history`
- `stock_analysis_cache`、`opportunity_score_history`：目前榜單與歷史分數
- `opportunity_ranking_cycles`：只封存整組完成的正式評分日
- `opportunity_backtest_outcomes`：次日開盤進場的成熟排名驗證結果
- `stock_sync_state`：上市／上櫃／ETF 的游標、進度與錯誤

資料庫建置檔位於 `supabase/migrations/`，批次程式位於 `supabase/functions/twss-sync-batch/`。完整結構、排程與重新部署方式請見 [docs/BACKEND.md](docs/BACKEND.md)。同步權杖與伺服器密鑰不可放進 GitHub；公開前端只使用 Supabase publishable key。

## 部署到 Supabase、GitHub 與 Vercel

1. 先執行 `npm test`。
2. 依 [docs/BACKEND.md](docs/BACKEND.md) 部署 Supabase migration 與 `twss-sync-batch`。既有專案因 v16.3 新增較早時間戳的 bootstrap migration，必須先 dry-run，再使用 `supabase db push --include-all`；全新專案使用一般 `supabase db push`。
3. 將本專案所有檔案上傳至 GitHub Repository，包含 `.github/`、`api/`、`public/`、`src/`、`scripts/`、`data/`、`supabase/` 與 `vercel.json`。
4. 在 Vercel 選擇 **Add New → Project**，匯入 Repository。
5. Framework Preset 選 **Other**，Root Directory 保持 `./`。
6. Build Command 使用 `npm run build`，Output Directory 使用 `public`。`vercel.json` 已把 `/api/*.js` 設為 300 秒，符合目前 Vercel Hobby Functions 上限。
7. 確認 Supabase 的 `stock_sync_state.details.version` 與排行榜 `analysis_version` 已是 v16.3 後，再在 GitHub **Actions** 執行一次 **Update Taiwan market snapshot → Run workflow**。

平日排程在台北時間 22:30 執行。它只從已受中央配額帳本保護的 Supabase 後端匯出 `public/data/latest.json` 與不可覆寫的 `data/snapshots/YYYY-MM-DD.json`，不會再從 GitHub Actions 額外直連 FinMind；Vercel 會因 GitHub commit 自動重新部署。GitHub 排程以 UTC 儲存且只在預設分支執行，實際啟動時間可能因 Actions 佇列略有延遲。

### 選用的環境變數

`FINMIND_TOKEN` 與選用的 `FINMIND_TOKEN_SECONDARY` 只應設在 Supabase Edge Function 的伺服器環境或 Supabase Vault，不要放到公開前端或 GitHub Actions。第二組憑證使用獨立 600 次／60 分鐘帳本；若未設定，次要排程會安全略過，絕不重用第一組 Token 冒充第二份額度。

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
- `GET /api/market-data?type=ranking-backtest`
- `GET /api/market-data?type=sources`
- `GET /api/health`

`deep` 與 `history` 只讀持久後端，不會因 `refresh=1` 繞過中央 API 配額。其他官方全市場端點加入 `refresh=1` 可略過短期快取；日常使用不應頻繁加入。

資料健康與缺漏診斷不屬於公開 API。管理員請在 Supabase Edge Function 日誌搜尋 `[admin-data-health]`；`twss_public_data_health()` 與 `twss_public_missing_data(limit)` 只允許 `service_role` 執行。

網站管理員登入後可從頁首或帳戶視窗開啟「管理員後台日誌」。全新專案部署 migration 後，請在 Supabase SQL Editor 將既有登入帳號加入管理員名單；不要把特定 Email 或 UUID 寫進公開原始碼：

```sql
insert into public.app_admins (user_id, username)
select id, 'owner'
from auth.users
where lower(email) = lower('YOUR_ADMIN_EMAIL')
on conflict (user_id) do update
set username = excluded.username, active = true;
```

撤銷管理權限可執行 `update public.app_admins set active = false where user_id = 'USER_UUID';`，下一次管理請求會立即被拒絕。

## 目前不能假裝已取得的資料

ETF 估計淨值與折溢價使用 TWSE MIS 公開檔。追蹤誤差、完整內扣費用與成分集中度目前仍沒有已串接且格式一致的免金鑰來源；v16.3 會據實顯示缺口並降低 ETF 信心，不會拿公司基本面代替。

TDCC 公開下載檔提供目前一週的全市場持股級距；歷史趨勢必須靠每日快照逐週累積。產業 20 日相對強弱也必須靠持續快照建立，初期只使用市場指數與當日產業廣度。

## 免責聲明

本專案僅供資料研究與軟體示範，不構成投資建議、買賣邀約、報酬保證或任何受託管理。公開資料可能延遲、更正、缺漏或調整格式；使用者應在重要決策前回到原始公告核對。
