# v17.2 持久化後端與研究工作台（量化核心仍為 v16.3）

這一版把「一次只深度驗證 10 檔」改成可續跑的資料管線。GitHub 靜態快照仍是前端備援；正式頁面會合併 Supabase 已累積的深度結果，因此完成檔數會隨排程增加，而不是每次從零開始。

## 資料流程

1. `universe` 取得 TWSE、TPEx、MOPS 的全市場快照並寫入 `stock_master`、`stock_snapshots`。
2. `deep_listed`、`deep_otc`、`deep_etf` 各自依初篩分數與股票代號排序。
3. 冷資料無 Token 時上市／上櫃／ETF 每次最多處理 6／6／19 檔，有 Token 時最多 11／11／23；歷史可重用時公司批次可提高到 10／10 或 22／22。實際數量會依滑動 60 分鐘剩餘額度縮小。成功後保存歷史資料、評分與下一個進度。
4. API 回傳成功但必要內容為空或落後期別時，保留 last-good 並設為修復候選；每批最多四分之一槽位處理這類缺口。財報快取只有 income、balance、cashflow 三者都有來源覆蓋時才可重用。
5. 單檔失敗會保存 `error_kind`、`attempt_count`、`next_retry_at`；同批其他股票仍可完成，新股票優先於退避中的失敗股票。
6. 前端優先讀取 `stock_analysis_cache`；`public/data/latest.json` 是同版本後端匯出備援，不合併舊模型結果。
7. 一組深度游標完整跑完後才寫入 `opportunity_ranking_cycles.status = final`；排名變化、同業比較與回測都不讀取尚未完成的日期。
8. 完成正式週期後，資料庫只用既有 `stock_price_history` 評估已成熟訊號，不增加 FinMind 或其他外部 API 請求。

當期 TWSE／TPEx 月營收橫斷面若少於交易母體，公司批次會把一半候選名額優先給 `raw_data.revenue` 缺漏者；逐檔歷史成功後會回寫 `stock_snapshots`，下一輪便恢復正常分數排序。這個補缺不另開旁路，所有 FinMind 呼叫仍先由中央滑動配額帳本保留。

全市場母體與目前正式排程分開：母體包含所有可辨識股票及 ETF；深度候選另套用流動性、風險與必要資料門檻。因此上櫃母體數與 `deep_otc.total_items` 不必完全相同。

## 單檔歷史日線按需補齊（v16.3-ui5）

排行榜尚未輪到深度驗證的股票，可能已有當日行情，但 `stock_price_history` 還沒有足夠日線。v16.3-ui5 的明細路由會先讀 Supabase；完整技術面以至少 120 筆為補抓目標，畫面少於 60 筆時不冒充完整技術資料。只有該股票確實缺漏時，才向 `twss-sync-batch?mode=history` 發出一次按需補抓；已確認為新上市且歷史本來較短者會保存完成標記，不會每次開啟都重抓。

按需補抓與排程共用資料庫中央滑動配額帳本：先取得單檔分散式租約、再次檢查資料庫，再原子保留 1 次 FinMind 額度，以單次 `TaiwanStockPrice` 請求取得日線，合併該檔較新的 TWSE／TPEx 官方快照後立刻 upsert 到 `stock_price_history`。因此同時開啟同一檔只會有一個補抓者，之後所有人皆由後端重用。互動補抓另限每小時 30／60 次，且為排程保留 10／20 次額度；仍不會繞過每 60 分鐘 300／600 次總上限。

若目前 60 分鐘額度已滿，函式回傳 HTTP 202、`code: HISTORY_PENDING` 與可重試時間，表示已知的配額等待狀態；不再把「尚未累積」偽裝成 HTTP 502。真正的上游錯誤才會標記為 `HISTORY_UPSTREAM_ERROR`，方便把資料尚未輪到、配額等待與供應商故障分開稽核。

## 排程

`20260714091000_schedule_persistent_stock_sync.sql` 使用 UTC 設定：

| 工作 | UTC | 台灣時間 | 每批 |
| --- | --- | --- | ---: |
| 全市場更新 | 平日 06:43 | 平日 14:43 | 全市場一次 |
| 上市深度 | 每小時 01、21、41 分 | 每小時 01、21、41 分 | 冷資料最多 6；可重用 10；有 Token 時 11／22 |
| 上櫃深度 | 每小時 08、28、48 分 | 每小時 08、28、48 分 | 冷資料最多 6；可重用 10；有 Token 時 11／22 |
| ETF 深度 | 每小時 15、35、55 分 | 每小時 15、35、55 分 | 最多 19；有 Token 23 |

台灣與 UTC 的分鐘相同，只有小時相差 8 小時。三組錯開 6～7 分鐘；FinMind 使用兩個通道並以 0.5 秒錯開啟動。每批開始前會透過資料庫 advisory lock 統計最近 60 分鐘的所有保留量，無 Token 上限 300、有 Token 上限 600；額度不足就縮小批次或等待，不會在整點邊界超額。此上限已依 [FinMind 官方說明](https://finmind.github.io/quickstart/) 核對。

冷公司資料一次最多消耗 8 次 FinMind 呼叫；營收與財報可重用時為 4 次；ETF 為 1 次。三組每 20 分鐘的 claim cap 分別是無 Token 50／50／19、有 Token 88／88／23，再由中央帳本做最後裁切。無 Token 的錯開排程會逼近 300 次／60 分鐘，最後一批依剩餘量自動縮小；有 Token 時同理逼近 600。這讓單一 Edge invocation 保持在 [Supabase Free plan 150 秒 wall-clock 上限](https://supabase.com/docs/guides/functions/limits)內，同時把可用額度用滿。

## 資料與單位

- 價量：最多 280 個交易日。
- 價量使用目前 FinMind 帳號層級可取得的 `TaiwanStockPrice`，並補入較新的 TWSE／TPEx 同日官方盤後 OHLCV。`TaiwanStockPriceAdj` 需要較高帳號權限，因此不再讓它阻斷整批技術面；近 40 日若有超過 35% 的疑似公司行動跳空，該檔技術評分會被隔離並標示原因。
- 月營收：最多 40 個月；評分正式需求至少 24 個月。
- 財務：最多 12 季。
- 法人與融資融券：各最多 30 個交易日。
- FinMind 損益表資料視為單季值；現金流量表的年內累計值才做 Q2～Q4 差分。
- 現金轉換採 `近四季營業現金流合計 ÷ 近四季淨利合計`。不足四季時才顯示最新季替代值，並標示 `cashConversionBasis`。
- 資料庫保存來源原始數值，畫面端才依欄位轉成張、百分比、億元或倍數。
- 排行榜 JSON 不重複內嵌 280 日價量；明細頁從 `stock_price_history` 另讀，避免候選數增加後 API 回應過大。
- `stock_sync_state` 的資料庫租約避免 cron 與手動工作重複選中同一批股票。
- 每日清理超過 60 日的全市場原始快照，並保留較長的點時分數與必要歷史，避免 Free-plan 儲存無上限增長。

## 權限

- `anon` 與 `authenticated` 只有公開市場資料表的 `SELECT` 權限。
- 所有公開市場資料表（包含 `stock_master`、`stock_snapshots`）都啟用 RLS，只有 public-read policy，沒有公開寫入 policy。
- `stock_sync_state` 不開放給 `anon`／`authenticated`；`stock_analysis_cache` 僅授權研究結果欄位，原始錯誤、租約、重試與修復狀態保留給管理端。
- 批次函式使用 Supabase 伺服器密鑰寫入；密鑰只存在 Edge Runtime 環境。
- pg_cron 的 `x-twss-sync-token` 由 Vault 產生與保存，原始碼沒有權杖明文。
- `twss-sync-batch` 雖設定 `verify_jwt = false`，POST 排程／手動同步仍會先呼叫 service-role-only 的 `twss_verify_sync_token`；缺少或錯誤權杖會回傳 HTTP 401。公開 GET 只開放 `mode=history`、合法股票代號與月份範圍，寫入仍由函式內的 service role 執行，且必須先通過股票主檔與中央配額檢查。

公開的 `sb_publishable_...` key 只用於受 RLS 保護的讀取，可放在前端；`sb_secret_...`、service role key 與 Vault 權杖不可提交到 GitHub。

## v17 管理診斷、同業與長期驗證

- `twss_public_data_health()`：僅限 `service_role`，彙整各來源日期、分組覆蓋率、修復數與正式評分日數。
- `twss_public_missing_data(limit)`：僅限 `service_role`，依每檔 `sourceDiagnostics` 與 `repair_reasons` 判定可重試、上游異常、官方期別落後、來源沒有或不適用。
- `twss_get_stock_context(symbol)`：同市場、同產業百分位與正式排名歷史；同產業少於 5 檔才使用同市場備援。
- `twss_evaluate_matured_backtests(group, model)`：service-role-only，使用訊號日後第一個交易日開盤價與第 5／10／20 個交易日收盤價，保存至 `opportunity_backtest_outcomes`。
- `twss_public_ranking_backtest(model)`：只在該市場與期間已有至少 25 個成熟訊號日時公開統計，否則回傳 `insufficient_history`。

同業與回測等公開 RPC 使用 `security invoker` 並沿用資料表 RLS；健康、缺漏、寫入與評估函式只授權 `service_role`。每次受權杖保護的同步工作都會以 `[admin-data-health]` 寫入精簡管理日誌，一般網站不提供健康中心或同步狀態端點。後端驗證不倒填後來公布的財報或營收，也不使用訊號日收盤價假設成交。

## 從原始碼重新部署

使用目前版 Supabase CLI；先執行 `supabase db push --help`，確認可用 `--dry-run` 與 `--include-all`。官方旗標定義見 [Supabase CLI `db push`](https://supabase.com/docs/reference/cli/introduction#supabase-db-push)。

### 更新既有正式專案

v16.3 新增 `20260714040000_base_schema.sql`，它的時間戳早於部分已在原專案套用的 migration。既有專案若只執行一般 `db push`，CLI 可能把它視為 out-of-order；必須先 dry-run 檢查，再明確使用 `--include-all`：

```sh
supabase login
supabase link --project-ref lfkdkdyaatdlizryiyon
supabase db push --dry-run --include-all
supabase db push --include-all
supabase functions deploy twss-sync-batch
```

`20260714040000_base_schema.sql` 使用 `create table if not exists`、policy 存在檢查與可重複的權限設定，因此補套到既有專案不會清空資料。不要使用 `db reset --linked`，那會重建遠端資料庫。

部署既有專案前先執行 `supabase migration list` 並保留 dry-run。若 CLI 回報本地與遠端 migration history 不同步，請依 CLI 顯示的版本使用官方 `supabase migration repair`／`db pull` 流程對齊後再推送；不可用 linked reset，也不可直接忽略 history 錯誤重跑。

### 建立全新 Supabase 專案

全新專案沒有 out-of-order 歷史，先完成下方「更換專案」清單，再使用一般推送：

```sh
supabase login
supabase link --project-ref YOUR_PROJECT_REF
supabase db push --dry-run
supabase db push
supabase functions deploy twss-sync-batch
```

若有 FinMind Token，只設在 Edge Function secrets；不要放進 GitHub 或 Vercel 公開環境：

```sh
supabase secrets set FINMIND_TOKEN=YOUR_TOKEN
supabase functions deploy twss-sync-batch
```

`supabase/config.toml` 已指定自訂 entrypoint 與 `verify_jwt = false`。不可移除函式內的 Vault 權杖驗證。

若是在另一個 Supabase 專案重建，必須在 `db push` 與 Vercel 部署前同步修改：

- `supabase/config.toml` 的 `project_id`
- 所有 migration 內的 Edge URL，包括 `https://<project-ref>.supabase.co/functions/v1/twss-sync-batch`；後面的排程 migration 會覆寫前面的工作，不能只改一個檔案
- `src/backend-store.js` 與 `scripts/export-backend-snapshot.mjs` 的預設 project URL／publishable key，或在 Vercel／GitHub Repository Variables 設定 `SUPABASE_URL`、`SUPABASE_PUBLISHABLE_KEY`
- `src/market-data.js` 的舊 `twss-market-data` 備援 URL；此舊函式不包含在本 repository，沒有部署時應視為可選備援，不可誤認為主要資料源
- `vercel.json` 的 Content-Security-Policy `connect-src`

可先執行下列搜尋，直到不再殘留舊 project ref；公開 publishable key 可以出現在前端，但伺服器 secret/service-role key 絕不可提交：

```sh
rg -n "lfkdkdyaatdlizryiyon|sb_publishable_" src scripts supabase vercel.json
```

`data_sync_status` 是舊版遺留且 v16.3 未使用的表名；fresh migration 不再依賴它。正式同步狀態只讀 `stock_sync_state`。

## 查看進度

在 SQL Editor 可用只讀查詢確認狀態：

```sql
select job_key, status, cycle_date, total_items, processed_count,
       cursor_offset, last_symbol, last_error, last_success_at,
       details ->> 'version' as worker_version
from public.stock_sync_state
order by job_key;
```

各榜已完成數量：

```sql
select group_name, count(*)
from public.stock_analysis_cache
where status = 'ready'
group by group_name
order by group_name;
```

正式評分日與成熟回測進度：

```sql
select score_date, group_name, status, scored_count, official_count
from public.opportunity_ranking_cycles
order by score_date desc, group_name;

select group_name, horizon_days, count(distinct signal_date) as matured_signal_days,
       count(*) as observations
from public.opportunity_backtest_outcomes
group by group_name, horizon_days
order by group_name, horizon_days;
```

第一輪尚未跑完並不是錯誤；`processed_count` 與 `cursor_offset` 持續增加，且 `last_error` 為空，即代表正常累積。

發佈 v16.3 前還要確認分析版本與資料缺漏原因：

```sql
select analysis_version, group_name, status, count(*)
from public.stock_analysis_cache
group by analysis_version, group_name, status
order by analysis_version, group_name, status;

select group_name,
       count(*) filter (where stock ->> 'revenue' is null) as missing_monthly_revenue,
       count(*) filter (where analysis -> 'financial' ->> 'revenue' is null) as missing_quarterly_revenue
from public.stock_analysis_cache
where status = 'ready'
group by group_name
order by group_name;
```

月營收缺漏要再對照 `analysis.missing` 與 `analysis.sourceDiagnostics.revenue`；季營業額則對照 `analysis.financial.revenueStatus`。來源未回傳、歷史不足、去年同期為零、金融業口徑不可比與 API 失敗是不同狀態，不可一律當成 0。只有 `analysis_version = '16.3-ultimate-data-audit'` 的 ready rows 才會進正式 v16.3 排行榜。
