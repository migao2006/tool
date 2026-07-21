# 當日證券狀態快照

> 2026-07-19 核對：此流程只累積當日觀測，不能補出完整歷史交易狀態；Production schema 的唯一 source of truth 是 `supabase/migrations/`，不是 `supabase/schema/` 參考 SQL。

這個匯入流程只保存「資料抓取當日可觀察的上市、上櫃普通股狀態」，不會把今日
公司清單回填成歷史股票池，也不會猜測已下市公司、歷史產業分類或公告時間。

## 來源與範圍

- MOPS 公司基本資料：當日普通股身分與產業代碼。
- TWSE：變更交易、停復牌、注意與處置公告。
- TPEx：交易方式、停復牌、注意與處置公告。
- ETF、TDR、衍生商品與無法唯一對應的代號不匯入普通股快照。

每一列使用 `[snapshot_date, snapshot_date + 1)`，並標示
`record_kind=CURRENT_DAILY_SNAPSHOT`。`available_at` 是整組來源最後一筆實際
抓取時間；來源內容另以 composite SHA-256 保存。這些欄位不能被解讀為歷史公布時間。

目前沒有已驗證的全額交割獨立來源，因此 `full_cash_delivery_flag` 寫入 `NULL`。
盤中停牌也不會被日級資料誤寫為正常，而是 `trading_status=UNKNOWN`。這兩種狀況都會
使正式推薦 hard fail，系統維持 `RESEARCH_ONLY`。

## 執行

本機先以 migration chain 重建及 lint，不得直接依序執行 `supabase/schema/001`～`006`：

```powershell
pnpm exec supabase db reset --local --no-seed
pnpm exec supabase db lint --local --schema public,market_data --level warning --fail-on error
```

再執行匯入 dry-run 或隔離環境寫入：

```powershell
uv run python -m scripts.import_security_snapshot --dry-run
uv run python -m scripts.import_security_snapshot
```

GitHub Actions 的 `Import current security snapshot` 預設手動 dry-run；排程只在平日
台北時間 20:05 執行正式寫入。所有來源會在第一次 Supabase 寫入前抓取並驗證完成，
避免供應商中途失敗留下部分批次。

正式寫入另要求上市與上櫃公司資料的來源日期都等於 `snapshot_date`。週末、休市日或
任一市場尚未更新時會在第一筆資料庫寫入前停止；dry-run 則保留診斷結果並加上
`SNAPSHOT_DATE_NOT_CONFIRMED_BY_BOTH_MARKETS`。
