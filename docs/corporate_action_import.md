# 公司行動預告匯入

這個階段只保存「首次擷取日起」的 TWSE 與 TPEx 除權息預告版本。它不是歷史公司行動回補，也不能讓模型通過正式驗收；系統狀態固定為 `RESEARCH_ONLY`。

## 資料範圍

- TWSE：`TWT48U_ALL` 除權除息預告。
- TPEx：`tpex_exright_prepost` 除權除息預告。
- MOPS 公司基本資料：只用於當下上市／上櫃普通股身分解析，ETF 不混入普通股模型。
- 只匯入可明確解析的現金股利與股票股利。現金增資認股、分割、減資及畸零股現金替代尚未支援。

來源沒有逐列實際公告時間與付款日，因此：

- `announced_at` 保持 `null`，不可用擷取時間冒充公告時間。
- `first_observed_at` 與 `available_at` 使用實際擷取時間。
- `action_status=ANNOUNCED`、`source_row_complete=false`。
- 同一事件以穩定 `source_event_id` 識別；來源列內容改變時以新的 row-level SHA-256 保存修訂。

## 執行

先做只讀驗證：

```powershell
.venv\Scripts\python.exe -m scripts.import_corporate_actions --dry-run
```

正式寫入需要 `SUPABASE_URL` 與 `SUPABASE_SERVICE_ROLE_KEY`。明確指定的 `snapshot_date` 必須等於所有來源在台北時區的實際擷取日期，避免把現在資料回填到歷史日期。

GitHub Actions 的手動執行預設為 dry-run；排程只累積當前預告快照，不會自動進行無界限的歷史逐股回補。

## 尚未解除的硬限制

- 歷史公司行動 vintage、歷史市場身分及下市公司尚未回補。
- 付款日與股票交付日未知，不能用於正式資金結算回測。
- `daily_bars.company_action_complete` 仍為 `false`。
- 預告事件不會直接當成 realized label；還需事後結果核對與 latest-revision selector。
