# 台股智選 v19 交付說明

## 升級原則

v19 直接在現有原始碼與部署架構上增量升級，沒有重建整套系統。兩個 Supabase 專案維持原本分工：

| 專案 | 保留用途 | v19 原則 |
| --- | --- | --- |
| CORE | 使用者登入、個人資料、自選股與既有使用者功能 | 不搬移既有資料或資料表，不交換連線用途；既有前端相容性保持不變 |
| MARKET | 股票主檔、行情、歷史資料、分析、排行榜、同步與管理診斷 | 只新增可重建的 v19 讀取模型、官方新聞／公告與必要索引、函式及排程 |

沒有建立第三個 Supabase 專案，沒有搬移或刪除既有資料，也沒有任意更名既有環境變數。v19 的新資料採可重複執行的 Upsert／快照方式產生；背景工作失敗時保留最後一份可用資料，不回滾既有成功工作。

## 1. v19 完整原始碼

完整原始碼仍位於同一個 GitHub repository，並保留原本前端、API、Vercel 設定、Supabase migrations、Edge Functions、同步程式與測試。v19 新功能是向後相容的新增層：

- 首頁 v19 六個資訊區塊與深色／淺色主題。
- 預先計算的排行榜讀取模型、分頁、篩選、搜尋與排序。
- 個股 AI 分析、分數拆解、信心、風險、理由、新聞及歷史資料呈現。
- Vercel v19 公開讀取 API、短期記憶體快取與 CDN stale-while-revalidate 快取。
- MARKET 內的 v19 排行榜快照、官方新聞／公告與安全的公開工作狀態。
- 現有 v16.3 量化模型仍是排名依據；語言或展示層不會自行猜測分數，也不會改寫原排名。

## 2. 新增與修改檔案清單

發布前以最終 release diff 為準；v19 主要範圍如下：

| 狀態 | 檔案／目錄 | 用途 |
| --- | --- | --- |
| 新增 | `api/v19/_shared.js` | v19 API 共用回應、安全標頭與快取控制 |
| 新增 | `api/v19/home.js` | 首頁聚合 API |
| 新增 | `api/v19/rankings.js` | 排行榜分頁、篩選、搜尋與排序 API |
| 新增 | `api/v19/stocks.js` | 個股分析 API |
| 新增 | `src/v19-backend.js` | v19 讀取模型、fallback、日期與分頁邏輯 |
| 新增 | `supabase/migrations/20260716003204_add_v19_read_models.sql` | MARKET v19 增量 schema、索引、RLS、RPC、快照與排程 |
| 新增 | `supabase/functions/twss-v19-news/`, `supabase/functions/_shared/v19-news.js` | 已部署的官方新聞／重大訊息同步 Worker 與可測試正規化規則 |
| 修改 | `public/index.html`, `public/smart.js`, `public/styles.css` | v19 首頁、排行榜、個股分析、主題與漸進式載入 |
| 修改 | `public/app.js`, `public/patch.js`, `public/admin.html` | 版本、相容層與管理畫面增量調整 |
| 修改 | `public/manifest.webmanifest`, `public/sw.js` | PWA v19 資產與快取版本 |
| 新增／修改 | `scripts/v19-test.mjs`, `scripts/smoke.mjs`, `scripts/snapshot-pipeline-test.mjs` | v19 API、安全、資料庫 migration、新聞與前端資料流程驗證 |
| 修改 | `public/admin.js`, `worker/index.js`, `supabase/config.toml`, `vercel.json` | 管理狀態標籤、部署產物、Worker 驗證設定與 v19 Function 設定 |
| 修改 | `package.json`, `README.md` | 版本與升級摘要 |
| 新增 | `docs/V19-DELIVERY.md` | 本交付、部署與回滾說明 |

## 3. 新增資料表 SQL

SQL migration：`supabase/migrations/20260716003204_add_v19_read_models.sql`

只套用至既有 MARKET 專案，主要新增：

- `v19_ranking_snapshots`：以股票、資料日期與模型版本作複合主鍵；保存可預先讀取的排行榜快照。
- `v19_news_items`：以來源與外部識別值防止重複；保存官方新聞、重大訊息及股票關聯。
- 排行榜群組／分數／產業索引，以及新聞日期／股票代號／市場索引。
- `twss_v19_refresh_ranking_snapshot(...)`：四參數、交易鎖與 Upsert 的快照刷新；可明確允許 provisional，但公開正式榜只回傳 `official=true`。
- `twss_v19_rankings_page(...)`：在資料庫端完成固定快照日期、搜尋、產業／市場篩選、七種排序及最多 100 筆的有界分頁。
- `twss_v19_refresh_available_rankings()`：只在來源內容變更時更新可用群組，避免每五分鐘重寫全部快照。
- `twss_v19_public_job_status()`：只公開非敏感的背景工作進度，不包含金鑰與內部錯誤內容。
- final cycle 觸發器與 `twss-v19-news` pg_cron 排程；重試仍以唯一鍵保證冪等。

新增資料表均具有主鍵、必要索引、RLS、明確 grants、資料日期與更新時間。既有表是唯一資料來源，v19 快照可由既有資料重建，不會移動或覆寫原始資料。

## 4. 新增 Vercel 後端說明

v19 在現有 Vercel 專案新增獨立 API 檔案，沒有搬移或更改既有 API 路徑，也沒有強迫建立新的微服務：

- 只執行預先計算結果的快速讀取與組合，不在開頁時重跑全市場分析。
- 同一時間的相同查詢共用記憶體中的 pending request，減少重複查詢。
- 成功回應使用 Vercel CDN `s-maxage` 與 `stale-while-revalidate`；錯誤回應不快取。
- v19 資料表尚未可用時，安全降級讀取既有排行榜快取，前端仍可使用。
- 所有公開 API 僅接受 `GET`／`OPTIONS`，內部錯誤不回傳資料庫診斷或金鑰。

## 5. 新增環境變數清單

v19 沒有更名或移除任何既有環境變數，也沒有新增前端私密金鑰。沿用項目如下：

| 名稱 | 位置 | 用途／限制 |
| --- | --- | --- |
| `SUPABASE_URL` | Vercel／本機建置 | MARKET 公開 Data API URL；沿用既有名稱 |
| `SUPABASE_PUBLISHABLE_KEY` | Vercel／前端允許範圍 | 只可使用 publishable key，受 RLS 與 grants 限制 |
| `SUPABASE_SERVICE_ROLE_KEY` | 僅伺服器端或一次性管理作業 | 不得打包進前端、日誌或 Git；v19 公開 API 不需要它 |
| `finmind_api_token` | MARKET Supabase Vault secret | FinMind 每小時 600 次額度的既有同步憑證；只由伺服器端讀取，不新增前端副本 |
| `twss_sync_token` | 既有 Supabase Vault secret | pg_cron 呼叫內部 Worker 的驗證金鑰，不是前端環境變數 |

CORE 的既有 URL、publishable key 與連線名稱保持原樣。若最終 release 沒有新增環境值，部署平台不需新增變數。

## 6. API 路由清單

### v19 新增路由

| 方法 | 路由 | 說明 |
| --- | --- | --- |
| `GET` | `/api/v19/home` | 首頁排行榜、新聞與背景工作狀態聚合 |
| `GET` | `/api/v19/rankings` | 排行榜；支援 `limit`、`cursor`、`market`、`industry`、`search`、`sort` |
| `GET` | `/api/v19/stocks?symbol=2330` | 單一股票的行情、分數、分析、新聞與資料日期 |

排行榜預設有限筆數，第一次只傳前端需要的資料，後續以 cursor 載入；不會一次把全市場送到前端。

### MARKET 新增 RPC／Worker

- `twss_v19_refresh_ranking_snapshot(text, date, text, boolean)`：僅 `service_role` 可執行。
- `twss_v19_refresh_available_rankings()`：排程刷新可重建排行榜快照。
- `twss_v19_rankings_page(text, text, text, text, integer, integer, text, jsonb)`：RLS 安全的正式榜有界讀取。
- `twss_v19_public_job_status()`：安全公開工作進度。
- `twss-v19-news`：已部署、由內部同步金鑰驗證的新聞／公告 Edge Function。

所有既有 `/api/market-data`、`/api/ai-research`、`/api/health` 與管理 API 保持原路徑與資料格式。

## 7. 測試結果

最終 release 必須記錄實際執行結果，不以文件敘述取代測試：

| 測試 | 指令／範圍 | 最終結果 |
| --- | --- | --- |
| 產物驗證 | `node scripts/validate-artifact.mjs` | 通過 |
| 後端資料流程 | `node scripts/backend-pipeline-test.mjs` | 通過 |
| 後端讀取層 | `node scripts/backend-store-test.mjs` | 通過 |
| 深度資料 | `node scripts/deep-data-test.mjs` | 通過 |
| 量化引擎 | `node scripts/engine-test.mjs` | 通過 |
| 快照流程 | `node scripts/snapshot-pipeline-test.mjs` | 通過 |
| 靜態 smoke | `node scripts/smoke.mjs` | 通過 |
| v19 合約 | `node scripts/v19-test.mjs`：API、游標、日期、RLS、migration、新聞、秘密防洩漏 | 21/21 通過 |
| 瀏覽器／production 驗收 | 首頁、主題、載入更多、個股、自選股、管理員可見性；production 首頁與三個 v19 API | 通過；production 首頁、home、rankings、stocks 均為 200 |
| 資料庫驗收 | MARKET transaction dry-run、正式 migration、RLS、快照、Cron、Worker 冪等；CORE 無 v19 表 | 通過 |

## 8. 已修復問題

- 首頁不再依賴開頁時的全市場即時計算，改讀預先計算快照並保留舊快取 fallback。
- 排行榜支援分頁、載入更多、類型／市場／產業篩選、搜尋與排序，避免一次傳送所有股票。
- 股票頁將交易資料日期、分析產生時間、新聞發布時間、抓取時間與頁面更新時間分開處理。
- 資料未完全同步時可顯示更新中、前一交易日或部分完成狀態，不以程式執行時間冒充交易日期。
- 排行榜與新聞使用唯一鍵、Upsert 與交易鎖，重試不會產生重複寫入。
- v19 公開資料只使用 RLS 與明確 grants；私密金鑰不會放入前端或錯誤回應。
- 背景工作與 v19 API 採局部降級，單一來源失敗不會拖垮首頁或既有正常功能。

## 9. 尚未完成項目

核心 v19 升級沒有未完成的程式、資料庫或部署項目；production 已解除維護模式並完成驗證。後續營運項目只有持續觀察公開資料來源與排程成功率。

## 10. 部署方式

1. 確認目標仍是既有 CORE 與 MARKET 專案，記錄 schema／資料筆數，不執行資料搬移。
2. 在 MARKET 對 migration 做 transaction dry-run，檢查既有 migration history 與 advisory/security advisor；不得套用至 CORE。
3. 先將 `twss-v19-news` 部署至既有 MARKET Edge Functions，確認內部金鑰驗證；再套用 `20260716003204_add_v19_read_models.sql`，避免 Cron 早於 Worker 上線。
4. 確認 RLS、grants、索引、快照筆數、Cron、官方來源 Upsert，以及第二次同步寫入 0 筆的冪等結果。
5. 部署 Vercel preview；驗證首頁、三個 v19 API、分頁游標、fallback、主題、自選股與管理頁權限。
6. 執行第 7 節完整測試。只有全部 release gate 通過後才部署／promote production 並解除維護模式。
7. 驗證 production 首頁、API、PWA 更新、正確資料日期、兩個 Supabase 原用途，以及沒有重複寫入。

## 11. 回滾方式

1. 若前端或 Vercel API 異常，立即將 production 指回上一個已驗證的 Vercel deployment；既有 API 與資料庫仍可運作。
2. 若新聞 Worker 異常，先停用名為 `twss-v19-news` 的 pg_cron，再回滾 Edge Function。不要刪除新聞資料，也不要改動其他同步排程。
3. 若排行榜快照異常，停止 final-cycle v19 快照觸發，應用層回到既有排行榜快取；原始 `opportunity_*` 資料保持不變。
4. v19 migration 是純新增且不應破壞舊版。回滾應先停用新增排程／觸發器並保留新表，避免直接 DROP TABLE 或刪除資料；待離線確認後再決定是否移除新增物件。
5. 回滾後重新驗證 CORE 登入／自選股、MARKET 既有 API、管理員權限、資料日期與 production 首頁，再結束事件。

回滾不會交換兩個 Supabase 專案用途，不會將資料搬回／搬出，也不會更改既有環境變數名稱。
