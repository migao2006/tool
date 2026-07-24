# 當日證券狀態快照

> 2026-07-24 核對：此流程只累積當日觀測，不能補出完整歷史交易狀態；Production schema 的唯一 source of truth 是 `supabase/migrations/`，不是 `supabase/schema/` 參考 SQL。

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
使 tradability 必要證據不完整；Decision Policy 必須回
`MISSING_REQUIRED_DATA`、`decision=null`，系統維持 `RESEARCH_ONLY`。不得把
`altered_trading_method_flag` 當成 `full_cash_delivery_flag`，也不得以今日狀態回填
歷史決策。

## 執行

本機先以 migration chain 重建及 lint，不得直接依序執行 `supabase/schema/001`～`006`：

```powershell
pnpm exec supabase db reset --local --no-seed
pnpm exec supabase db lint --local --schema public,market_data --level warning --fail-on error
```

再依場別執行 dry-run 或隔離環境寫入：

```powershell
uv run python -m scripts.import_security_snapshot --market TWSE --dry-run
uv run python -m scripts.import_security_snapshot --market TPEX --dry-run
uv run python -m scripts.import_security_snapshot --market TWSE
uv run python -m scripts.import_security_snapshot --market TPEX
```

省略 `--market` 只保留給需要兩個場別來源日期完全一致的 legacy 操作；正式排程
不得使用它。GitHub Actions 的 `Import current security snapshot` 預設手動 dry-run；
排程在平日台北時間 20:05 以 `TWSE`、`TPEX` 兩個 `fail-fast=false` matrix job
獨立解析來源日期、驗證、寫入及保存 artifact。一個場別延遲或失敗不會阻擋另一個
場別，且不得改查或寫入另一市場。每個 job 仍會在第一次 Supabase 寫入前完成該場別
所有來源的抓取與驗證，避免供應商中途失敗留下部分批次。

單場別正式寫入要求該場別公司資料的來源日期等於 `snapshot_date`。週末、休市日或
所選市場尚未更新時會在第一筆資料庫寫入前停止；dry-run 保留診斷結果。legacy
雙場別模式才要求上市與上櫃日期一致，並使用
`SNAPSHOT_DATE_NOT_CONFIRMED_BY_BOTH_MARKETS`。

快照只有在 `snapshot_date` 恰好等於政策 `as_of_date`、來源完整且
`available_at <= decision_at` 時，才可能成為正式 tradability 證據。排程於晚間取得的
同日狀態不可倒填至當日 17:00 決策；它仍是可稽核的晚到觀測，不是可用政策輸入。
