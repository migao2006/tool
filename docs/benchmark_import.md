# 市場基準匯入

普通股的上市與上櫃基準分開保存：

- 上市：TWSE 發行量加權股價報酬指數。
- 上櫃：TPEx 櫃買報酬指數。

兩者都是含現金股利的每日收盤總報酬指數，不能互換，也不包含 ETF 基準。

## 第一版範圍

官方 OpenAPI 目前只回傳本月已完成交易日，因此這個工作只會從首次擷取日起累積正式來源版本。每筆資料保存來源、row-level revision hash、完整 payload hash、首次擷取時間與 benchmark version。

這些指數只有每日收盤值，與個股標籤的 `t+1 開盤進場 → 第 5 日收盤出場` 路徑不完全對齊。因此：

- `usage_scope=LABEL_TARGET_ONLY`
- `alignment_status=RESEARCH_ONLY`
- 不得把 close-to-close 指數報酬宣稱為已驗證的可執行 alpha benchmark。
- 模型與回測在對齊規則完成樣本外驗證前仍維持 `RESEARCH_ONLY`。

## 執行

```powershell
.venv\Scripts\python.exe -m scripts.import_benchmarks --dry-run
```

正式寫入需要 Supabase server-side secrets。指定的 `snapshot_date` 必須等於來源的實際擷取日期；TWSE 與 TPEx 的最新 session date 也必須一致。

GitHub Actions 手動執行預設為 dry-run，平日排程只累積當前官方觀測，不會用 current-month endpoint 冒充五年歷史資料。
