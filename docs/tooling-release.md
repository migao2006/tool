# 工具、Git 與發布規範

## 一、工具

Python：

- uv
- Ruff
- basedpyright
- pytest
- pip-audit

前端：

- pnpm
- Biome
- Playwright

其他：

- SQLFluff
- actionlint
- Gitleaks
- pre-commit
- Supabase CLI
- Vercel CLI
- GitHub CLI
- Cloudflare dashboard／connector
- Wrangler（只有環境已安裝且可驗證版本時才使用）

不得加入功能重疊工具，除非有明確必要。

## 二、Windows 憑證

uv 遇到憑證問題時使用：

```powershell
uv run --system-certs <command>
```

pnpm 遇到憑證問題時使用：

```powershell
$env:NODE_OPTIONS = "--use-system-ca"
```

禁止關閉 TLS 或設定 `strict-ssl=false`。

## 三、Git

修改前檢查 Git 差異，提交前檢查：

- Staged files
- Untracked files
- 測試結果
- 機密
- 無關修改

每次提交只包含本次任務相關內容。

所有修改必須使用 Git 留下紀錄並推送至 GitHub。

## 四、Migration

以下視為高風險：

- 大表鎖定
- `NOT NULL`
- Unique constraint
- Foreign key
- 欄位型別轉換
- 大量 backfill
- 大幅修改 RLS
- Auth schema 變更
- 無法安全回復的操作

高風險變更應使用分階段 migration、向後相容 schema 及明確 rollback。

### 本機 Supabase 重建與歷史對齊

- 本機首次啟動及 migration 變更後，必須執行
  `pnpm exec supabase db reset --local --no-seed`。
- 重建後必須執行
  `pnpm exec supabase db lint --local --schema public,market_data --level warning --fail-on error`。
- `20260717180000_initial_market_data_baseline.sql` 只供空資料庫重建；
  既有正式資料庫不得重新執行此 baseline。
- 正式資料庫的既有 migration 版本與 SQL 內容必須先完成等價稽核。
  baseline 只能在確認 schema 等價後標記為已套用。
- 在遠端 migration history 尚未完成上述對齊前，禁止執行
  `supabase db push`、`--include-all` 或盲目使用 migration repair。
- 正式推送前，migration 差異必須只包含經驗證、確實尚未套用的
  forward-only migration。

## 五、發布閘門

部署 Production 前必須確認：

- Git 差異及提交範圍正確。
- 必要 lint、型別及測試通過。
- Gitleaks 沒有未處理機密。
- Migration 已在非正式環境驗證。
- 沒有已知 hard fail、時間錯置或資料洩漏。
- Preview 主要流程及 iPhone viewport 已驗證。
- GitHub required checks 通過。
- 已確認回復路徑。

無法完成必要驗證時，只能建立 PR 或 Preview，不得宣告正式發布完成。

## 六、歷史回補發布閘門

修改 FinMind、R2、Supabase queue／manifest 或歷史回補 workflow 時，合併前至少確認：

- reusable workflow 的三個 credential slot 保持隔離，不使用 `secrets: inherit`。
- 只有一個 worker 建立共用 task queue，只有一個 finalizer 更新首頁摘要。
- Ruff、basedpyright、pytest、actionlint 與 Gitleaks 通過。
- Supabase migration 已 dry run，函式權限仍只授予 `service_role`。
- 測試執行中 primary、secondary、tertiary 與 finalizer 全部成功。
- R2 manifest 的 object／symbol／row／byte 統計增加，且狀態仍為 `UNVERIFIED / RAW_LANDING_ONLY / RESEARCH_ONLY`。
- `historical_production_eligible_count` 不得因單純完成原始封存而增加。

驗證失敗時可以保留已完成的 immutable R2 object 與 manifest，但必須修復 workflow 後重新執行；
不得刪除成功資料、竄改統計或把部分成功宣稱為完整回補。
