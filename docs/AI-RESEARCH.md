# v16.4 獨立 Gemini AI 研究層

## 設計原則

AI 是補充研究，不是第二套選股引擎。資料流只有單向：

`stock_analysis_cache（唯讀） → 候選門檻與成本閘門 → Gemini 結構化摘要 → ai_stock_research → 股票明細頁`

`twss-ai-research` 不會寫入 `stock_analysis_cache`、`opportunity_score_history`，也不會匯入或呼叫 `opportunity-engine.js`。v16.4 測試會核對量化核心檔案的 SHA-256，防止 AI 功能意外改動原模型。

## 哪些股票會分析

同時符合下列條件才有資格：

- 深度狀態為 `ready`
- `official=true`
- 分析版本為 `16.3-ultimate-data-audit`
- 機會分數至少 65
- 資料信心至少 70%
- 輸入資料、Gemini 模型或 AI schema 與上一份報告不同

每日預設選 12 檔，分組配額為上市 5、上櫃 5、ETF 2；某一組不足時，空缺才由其他組的合格候選補上。資料庫的 `twss_reserve_ai_calls` 使用 advisory lock 原子保留每日額度，即使重複 cron 或手動觸發也不會超過 `AI_DAILY_LIMIT`，且 SQL 端永遠硬限制在 20 次以內。

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
- `AI_DAILY_LIMIT`：選用，預設 12，可設 1～20

排程本身不寫死檔數，會讀取 `AI_DAILY_LIMIT`；未設定時仍為 12。資料庫函式另有 20 次硬上限，重複排程也無法超過。

CLI 方式：

```sh
supabase secrets set GEMINI_API_KEY=YOUR_KEY GEMINI_MODEL=gemini-3.5-flash AI_DAILY_LIMIT=12
supabase functions deploy twss-ai-research
```

`supabase/config.toml` 對此函式設定 `verify_jwt=false`，因為 pg_cron 無使用者 JWT；函式本身會先以 Vault 內的 `twss_sync_token` 驗證 `x-twss-sync-token`，缺少或錯誤都回 HTTP 401。

平日排程為 UTC 10:20，也就是台灣時間 18:20。沒有 `GEMINI_API_KEY` 時，排程只把狀態標為 `configured:false`，不保留額度、不呼叫 Gemini，也不影響任何原功能。

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

未被選中時回傳 `available:false`；這是成本控制的預期狀態。
