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
