# 工具、Git 與發布規範

> 2026-07-19 已依本機、專案設定與 GitHub Actions 核對。工具存在不等於 CI 已強制執行；發布與 migration 現況見 [`current-status.md`](current-status.md)。

## 一、可用工具

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

- PowerShell 7
- jq
- yq
- fd
- fzf
- Docker Desktop（含 Docker Engine 與 Docker Compose）
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

2026-07-19 已實際確認 PowerShell `7.6.3`、jq `1.8.2`、yq `4.53.3`、
fd `10.4.2`、fzf `0.74.1`、Docker Engine `29.6.1`、Docker Compose
`5.3.0`、Docker Desktop 與 Supabase 本機容器可正常運作；目前 Supabase
CLI 為 `2.109.1`。Biome 已全域安裝，但專案尚無 `biome.json`；
pre-commit 也尚無專案設定檔。這兩者不得描述為已完整接入專案。

PowerShell 7 作為 Windows 自動化腳本的優先 shell；jq 用於 JSON 查詢，
yq 用於 YAML 查詢，fd 用於檔案名稱搜尋，fzf 主要供互動式終端搜尋。
搜尋 repository 內文字仍優先使用 `rg`。

Docker 工具狀態：`AVAILABLE`。可直接使用 `docker` 與 `docker compose`；
本次已用 `docker info` 確認 CLI 可連線至 Docker Desktop Engine。

### Docker 使用原則

- 涉及 Supabase schema、migration 或 rollback 時，優先使用 Docker Desktop
  啟動的 Supabase Local 完成隔離驗證，再操作 Staging。
- 開始前使用 `docker info` 確認 CLI 與 Engine 均可連線；只有安裝 CLI
  但 Engine 未啟動，不得標示 Docker 可用。
- 本機服務已啟動時應共用既有容器，不得為每個測試重複建立環境。
- Docker 驗證不能取代 Staging、migration history、RLS、rollback 與
  Production 發布閘門。

## 二、CI 已強制的驗證

`Project tests` workflow 目前強制：

- Python：`pytest`，pytest-xdist 最多 4 process，使用 `loadfile` 分配。
- 前端：Playwright 2 workers，共用一次本機 web server。
- PR：依受影響檔案選擇 Python／前端範圍。
- 非 PR 與每週排程：完整 Python 與前端回歸。
- 安裝：uv 與 pnpm lockfile／cache。

Ruff、basedpyright、Biome、actionlint、Gitleaks、SQLFluff、pip-audit 與 pre-commit 是可用或發布前工具，但目前沒有全部納入 `Project tests` required check。只有實際執行過的項目才能在交付報告中標示通過。

## 三、Windows 憑證

### PATH 重新載入

若工具剛由 WinGet 安裝，而目前 Codex／PowerShell 程序仍使用舊 PATH，
先在該命令工作階段重新載入 Windows 的系統與使用者 PATH：

```powershell
$machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$env:Path = "$machinePath;$userPath"
```

重新載入後仍找不到指令，才視為未安裝；不應在資料回補或 migration
執行期間僅為更新 PATH 而重啟電腦。

### TLS 與系統憑證

uv 遇到憑證問題時使用：

```powershell
uv run --system-certs <command>
```

pnpm 遇到憑證問題時使用：

```powershell
$env:NODE_OPTIONS = "--use-system-ca"
```

禁止關閉 TLS 或設定 `strict-ssl=false`。

## 四、Git

修改前檢查 Git 差異，提交前檢查：

- Staged files
- Untracked files
- 測試結果
- 機密
- 無關修改

每次提交只包含本次任務相關內容。

所有修改必須使用 Git 留下紀錄並推送至 GitHub。GitHub push／PR／merge 是唯一人工發布路徑；Vercel 的 GitHub 整合自動觸發可以接受，但不得直接以 Vercel CLI 執行 Production deploy 或 promote。

## 五、Migration

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

2026-07-19 的具體狀態：

- 本機共有 28 個 migration 檔案；Docker Supabase 完整 reset 與 lint 已通過。
- Staging history 已對齊 28 筆，截止
  `20260719090300_allow_late_retrieval_for_current_security_snapshot.sql`。
- Production history 已對齊 27 筆，截止
  `20260719081157_defer_unavailable_supplemental_datasets.sql`。
- `20260719090300` 尚未套用至 Production；必須先通過 GitHub 發布閘門。

## 六、發布閘門

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

## 七、歷史回補發布閘門

修改 FinMind、R2、Supabase queue／manifest 或歷史回補 workflow 時，合併前至少確認：

- reusable workflow 的 credential slot 保持隔離，不使用 `secrets: inherit`。
- 日線流程只有一個 worker 建立共用 task queue，且只有一個 finalizer 更新首頁摘要；其他流程必須依自己的冪等契約驗證，不可套用錯誤的日線規則。
- Ruff、basedpyright、pytest、actionlint 與 Gitleaks 通過。
- Supabase migration 已 dry run，函式權限仍只授予 `service_role`。
- 測試執行中 primary、secondary、tertiary 與 finalizer 全部成功。
- R2 manifest 的 object／symbol／row／byte 統計增加，且狀態仍為 `UNVERIFIED / RAW_LANDING_ONLY / RESEARCH_ONLY`。
- `historical_production_eligible_count` 不得因單純完成原始封存而增加。

驗證失敗時可以保留已完成的 immutable R2 object 與 manifest，但必須修復 workflow 後重新執行；
不得刪除成功資料、竄改統計或把部分成功宣稱為完整回補。

TAIEX 歷史基準、補充資料、歷史事件證據與上市 feature dataset 是 dormant／feature-gated workflow。合併程式與正式啟用是兩個不同發布階段；未完成 migration 及隔離環境驗證前不得啟用。
