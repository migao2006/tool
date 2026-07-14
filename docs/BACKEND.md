# v16.2 持久化後端

這一版把「一次只深度驗證 10 檔」改成可續跑的資料管線。GitHub 靜態快照仍是前端備援；正式頁面會合併 Supabase 已累積的深度結果，因此完成檔數會隨排程增加，而不是每次從零開始。

## 資料流程

1. `universe` 取得 TWSE、TPEx、MOPS 的全市場快照並寫入 `stock_master`、`stock_snapshots`。
2. `deep_listed`、`deep_otc`、`deep_etf` 各自依初篩分數與股票代號排序。
3. 每次最多處理 2 檔，成功後保存歷史資料、評分與下一個 `cursor_offset`。
4. 單檔失敗記錄在 `last_error`，同批其他股票仍可完成；下一次從游標繼續。
5. 前端讀取 `stock_analysis_cache`，與 `public/data/latest.json` 合併後分成上市、上櫃、ETF 三榜。

全市場母體與目前正式排程分開：母體包含所有可辨識股票及 ETF；深度候選另套用流動性、風險與必要資料門檻。因此上櫃母體數與 `deep_otc.total_items` 不必完全相同。

## 排程

`20260714091000_schedule_persistent_stock_sync.sql` 使用 UTC 設定：

| 工作 | UTC | 台灣時間 | 每批 |
| --- | --- | --- | ---: |
| 全市場更新 | 平日 06:45 | 平日 14:45 | 全市場一次 |
| 上市深度 | 每小時 05、35 分 | 每小時 05、35 分 | 2 檔 |
| 上櫃深度 | 每小時 15、45 分 | 每小時 15、45 分 | 2 檔 |
| ETF 深度 | 每小時 25、55 分 | 每小時 25、55 分 | 2 檔 |

台灣與 UTC 的分鐘相同，只有小時相差 8 小時。三組刻意錯開，FinMind 仍由單一佇列控制在約 1.35 秒以上的請求間隔。

## 資料與單位

- 價量：最多 280 個交易日。
- 月營收：最多 40 個月；評分正式需求至少 24 個月。
- 財務：最多 12 季。
- 法人與融資融券：各最多 30 個交易日。
- FinMind 損益表資料視為單季值；現金流量表的年內累計值才做 Q2～Q4 差分。
- 現金轉換採 `近四季營業現金流合計 ÷ 近四季淨利合計`。不足四季時才顯示最新季替代值，並標示 `cashConversionBasis`。
- 資料庫保存來源原始數值，畫面端才依欄位轉成張、百分比、億元或倍數。
- 排行榜 JSON 不重複內嵌 280 日價量；明細頁從 `stock_price_history` 另讀，避免候選數增加後 API 回應過大。

## 權限

- `anon` 與 `authenticated` 只有公開市場資料表的 `SELECT` 權限。
- 所有新資料表都啟用 RLS，沒有公開寫入 policy。
- 批次函式使用 Supabase 伺服器密鑰寫入；密鑰只存在 Edge Runtime 環境。
- pg_cron 的 `x-twss-sync-token` 由 Vault 產生與保存，原始碼沒有權杖明文。
- `twss-sync-batch` 雖設定 `verify_jwt = false`，函式本身會先呼叫 service-role-only 的 `twss_verify_sync_token`；缺少或錯誤權杖會回傳 HTTP 401。

公開的 `sb_publishable_...` key 只用於受 RLS 保護的讀取，可放在前端；`sb_secret_...`、service role key 與 Vault 權杖不可提交到 GitHub。

## 從原始碼重新部署

需要 Supabase CLI 1.215.0 以上，並先把 repository 連結到正確專案：

```sh
supabase login
supabase link --project-ref lfkdkdyaatdlizryiyon
supabase db push
supabase functions deploy twss-sync-batch
```

`supabase/config.toml` 已指定自訂 entrypoint 與 `verify_jwt = false`。不可移除函式內的 Vault 權杖驗證。

若是在另一個 Supabase 專案重建，必須同步修改：

- `src/backend-store.js` 的公開 project URL／publishable key
- `20260714091000_schedule_persistent_stock_sync.sql` 的函式 URL
- `supabase/config.toml` 的 `project_id`

不要把新專案的伺服器密鑰寫進任何檔案。

## 查看進度

在 SQL Editor 可用只讀查詢確認狀態：

```sql
select job_key, status, cycle_date, total_items, processed_count,
       cursor_offset, last_symbol, last_error, last_success_at
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

第一輪尚未跑完並不是錯誤；`processed_count` 與 `cursor_offset` 持續增加，且 `last_error` 為空，即代表正常累積。
