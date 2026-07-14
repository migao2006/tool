# v16.5 手動 Gemini AI 研究層

## 設計原則

AI 是補充研究，不是第二套選股引擎。資料流只有單向：

`股票明細按鈕 → 登入驗證 → stock_analysis_cache（唯讀） → 快取／成本閘門 → Gemini 結構化摘要 → ai_stock_research`

`twss-ai-research` 不會寫入 `stock_analysis_cache`、`opportunity_score_history`，也不會匯入或呼叫 `opportunity-engine.js`。v16.5 測試會核對量化核心檔案的 SHA-256，防止 AI 功能意外改動原模型。

## 手動按鈕與資料條件

股票明細不再自動查詢或顯示「未列入 AI 名單」。每一檔上市、上櫃、ETF 都會顯示按鈕；按下時只要求：

- 深度狀態為 `ready`
- 分析版本為 `16.3-ultimate-data-audit`
- 深度分析內容不是空值

不再要求 `official=true`、機會分數 65 或資料信心 70%，這些仍只影響原量化排行榜。若該股票尚未完成後端深度分析，按鈕會顯示「深度資料仍在累積」，而不是誤稱未入選。

按鈕先查相同輸入雜湊、模型與 schema 的 14 天快取；命中時零次 Gemini 呼叫。需要新摘要時，`twss_claim_manual_ai_request` 會以 advisory lock 原子處理同檔去重、每人每日 6 次、全站每日預設 12 次及同時最多兩份；SQL 端全站上限永遠不超過 20 次。舊的 `twss-ai-research-weekday` 排程已停用。

## Gemini 能做與不能做的事

能做：

- 將營收、財務品質、法人籌碼、技術價量、估值與資料缺口整理成短摘要
- 列出最多三項支持證據及三項風險證據
- 建立偏多、中性、風險三種 1～8 週觀察情境
- 提醒下一步應追蹤的公開資料

不能做：

- 修改、重算或取代既有分數與排名
- 產生目標價、買進／賣出指令或獲利保證
- 把缺漏值當成 0，或杜撰未提供的新聞與數字
- 將公司營收、EPS、ROE 邏輯套用到 ETF

模型回應強制使用 JSON Schema，後端會再次驗證欄位、枚舉、長度及信心範圍；未通過驗證的結果不會公開。

## 資料表與權限

- `ai_stock_research`：保存可公開的 ready 摘要與內部輸入雜湊／快照。RLS 只讓訪客讀 ready 列，且 column grant 不包含雜湊、輸入快照與狀態欄。
- `ai_research_runs`：內部執行紀錄與錯誤摘要，只有 service role 可用。
- `ai_research_usage`：每日原子保留、成功與失敗呼叫數，只有 service role 可用。
- `stock_sync_state.ai_research`：排程是否已設定、上次執行結果與數量。原排行榜 API 明確排除這個工作，不會改變既有狀態畫面。

## 啟用

不要把金鑰放在 GitHub、Vercel 公開變數、前端 JavaScript 或對話訊息。到 Supabase Dashboard 的 **Edge Functions → Secrets** 新增：

- `GEMINI_API_KEY`：必要
- `GEMINI_MODEL`：選用，預設 `gemini-3.5-flash`
- `AI_DAILY_LIMIT`：選用，全站預設 12，可設 1～20
- `AI_USER_DAILY_LIMIT`：選用，每帳戶預設 6，SQL 硬上限 12

排程本身不寫死檔數，會讀取 `AI_DAILY_LIMIT`；未設定時仍為 12。資料庫函式另有 20 次硬上限，重複排程也無法超過。

CLI 方式：

```sh
supabase secrets set GEMINI_API_KEY=YOUR_KEY GEMINI_MODEL=gemini-3.5-flash AI_DAILY_LIMIT=12 AI_USER_DAILY_LIMIT=6
supabase functions deploy twss-ai-research
```

`supabase/config.toml` 對此函式維持 `verify_jwt=false`，因為同一函式仍保留管理診斷入口。函式內會分流驗證：手動模式必須向 Supabase Auth 驗證真實使用者 JWT；管理模式則必須以 Vault 內的同步權杖驗證。JWT 只解碼而不向 Auth 驗證是不被允許的。

自動排程已取消。沒有 `GEMINI_API_KEY` 時，按鈕只回傳「尚未完成後端設定」，不保留額度、不呼叫 Gemini，也不影響任何原功能。

後端也支援名為 `twss_gemini_api_key` 的 Supabase Vault 備援；Edge Function Secret 永遠優先。Vault 值必須由管理者在正式環境另外建立，migration 與 GitHub 原始碼只包含 service-role-only 讀取函式，絕不包含金鑰本身。

## 查核

```sql
select status, details, last_success_at
from public.stock_sync_state
where job_key = 'ai_research';

select usage_date, reserved_calls, completed_calls, failed_calls
from public.ai_research_usage
order by usage_date desc;

select group_name, count(*), max(generated_at)
from public.ai_stock_research
where status = 'ready'
group by group_name;
```

前端唯讀 API：

```text
GET /api/market-data?type=ai-research&symbol=2330
```

尚未產生時回傳 `available:false`；前端會保留手動按鈕，不會再顯示未列入名單。
