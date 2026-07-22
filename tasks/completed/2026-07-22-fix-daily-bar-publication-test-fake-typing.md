# Fix Daily-Bar Publication Test Fake Typing

## Status

COMPLETE

## Goal

只修正 `tests/test_daily_bar_publication.py` 中傳入
`DailyBarPublicationService` 的兩個既有 test-fake argument-type 診斷，
不改變產品程式、公開契約、fake objects 或 runtime test behavior，並完成前一個
daily-bar publication contract extraction 任務略過的驗證。

## Working Tree Preflight

- Repository root：
  `C:/Users/a0912/Documents/Codex/2026-07-22/agents-md-tasks-active-task-md`。
- Branch：`main`（`main...origin/main`）。
- 已確認沿用同一個 local Git working tree，未建立 worktree、clone、sandbox 或 repository copy。
- 本任務開始時保留的既有路徑：
  - `src/data/ingestion/daily_bar_publication.py`（modified）
  - `tests/test_daily_bar_publication.py`（modified；含前一 extraction 任務新增測試）
  - `src/data/daily_bar_publication_contracts.py`（untracked）
  - `tasks/completed/2026-07-22-extract-daily-bar-publication-source-contracts.md`（untracked）
  - `tasks/completed/2026-07-22-select-first-reconstruction-target.md`（untracked analysis record）
- `tasks/active/TASK.md` 在本任務 preflight 為 `# No active task`／`Status: NONE`。
- 唯一 applicable repository instruction file 為 root `AGENTS.md`；必要 `.ai` 文件、task workflow、
  verification skill、產品檔與測試均已在修改前讀取。

## Existing Diagnostic Evidence

修改測試前執行原始命令，exit code 1，結果恰好為兩個預期錯誤：

```text
tests/test_daily_bar_publication.py:246:15 - error: Argument of type "MemoryStore" cannot be assigned to parameter "store" of type "R2Client" in function "__init__" (reportArgumentType)
tests/test_daily_bar_publication.py:247:20 - error: Argument of type "MemoryManifestRepository" cannot be assigned to parameter "repository" of type "DailyBarPublicationManifestRepository" in function "__init__" (reportArgumentType)
2 errors, 0 warnings, 0 notes
```

`git show HEAD:tests/test_daily_bar_publication.py` 證明 base version 已有
`MemoryStore`、`MemoryManifestRepository` 與同一個 `DailyBarPublicationService`
呼叫；base lines 119–122 的 constructor-line suppression 也已存在。
`git diff --unified=20 -- tests/test_daily_bar_publication.py` 顯示前一 extraction
任務只在該呼叫前加入 contract tests，沒有改動 fake dependency 呼叫。
因此這兩個 diagnostics 是本微任務開始前已存在的 test typing 問題，不是 extraction 行為變更。

## Actual Test-Only Change

將原本放在 `DailyBarPublicationService(` constructor 行上的
`# type: ignore[arg-type]` 移到兩個確切不相容 argument：

- `store=store,  # type: ignore[arg-type]`
- `repository=repository,  # type: ignore[arg-type]`

沒有新增 `Any`、file-level ignore、cast、Protocol 或型別設定變更。這只是讓既有、必要的
test-double boundary suppression 套用到 basedpyright 實際報錯的行；仍建立並傳入相同的
`MemoryStore` 與 `MemoryManifestRepository` 實例，呼叫、fixtures、imports、assertions
與 runtime semantics 完全不變。

## Allowed Files and Final Path Ownership

本微任務只觸及三個 Allowed Files：

1. `tasks/active/TASK.md`：建立 ACTIVE task，完成後恢復標準 `NONE` 內容。
2. `tests/test_daily_bar_publication.py`：只移動兩個精確 argument suppressions；同檔其餘未提交變更屬前一 extraction 任務。
3. `tasks/completed/2026-07-22-fix-daily-bar-publication-test-fake-typing.md`：本完成紀錄。

前一任務的兩個產品檔與兩個歷史紀錄均未修改；既有未追蹤 analysis record
`tasks/completed/2026-07-22-select-first-reconstruction-target.md` 也未修改或移除。

## Product-File Hash Protection

| Product file | Before | After | Result |
|---|---|---|---|
| `src/data/daily_bar_publication_contracts.py` | `2f8208c0fede8aa3a559b8dc48a5ffc4ebe33af3` | `2f8208c0fede8aa3a559b8dc48a5ffc4ebe33af3` | identical |
| `src/data/ingestion/daily_bar_publication.py` | `db28ad27c86cd66ba358f052fe8dfa6120be80b0` | `db28ad27c86cd66ba358f052fe8dfa6120be80b0` | identical |

每次 `git hash-object` 執行的 exit code 均為 0。

## Commands and Exact Exit Codes

### Preflight and evidence

| Command | Exit code | Result |
|---|---:|---|
| `git rev-parse --show-toplevel` | 0 | required root |
| `git status --short --branch` | 0 | branch 與既有變更已確認 |
| `git diff --name-status` | 0 | tracked diff 已確認 |
| `git diff --stat` | 0 |既有 extraction diff 已確認 |
| `git hash-object src/data/daily_bar_publication_contracts.py` | 0 | before hash recorded |
| `git hash-object src/data/ingestion/daily_bar_publication.py` | 0 | before hash recorded |
| `git show HEAD:tests/test_daily_bar_publication.py \| rg -n -C 24 "class MemoryStore\|class MemoryManifestRepository\|DailyBarPublicationService"` | 0 | base call existed |
| `git diff --unified=20 -- tests/test_daily_bar_publication.py` | 0 | extraction diff did not change call |
| `rg -n -C 8 "DailyBarPublicationService" tests/test_daily_bar_publication.py` | 0 | current lines inspected |
| `uv run --with "basedpyright==1.39.9" basedpyright src/data/daily_bar_publication_contracts.py src/data/ingestion/daily_bar_publication.py tests/test_daily_bar_publication.py`（修改前） | 1 | exactly two expected `reportArgumentType` errors |

### Focused validation

| Command | Exit code | Result |
|---|---:|---|
| `uv run --system-certs --extra test pytest -q tests/test_daily_bar_publication.py` | 0 | 10 passed |
| `uv run --with "ruff==0.15.22" ruff check src/data/daily_bar_publication_contracts.py src/data/ingestion/daily_bar_publication.py tests/test_daily_bar_publication.py` | 0 | all checks passed |
| `uv run --with "basedpyright==1.39.9" basedpyright src/data/daily_bar_publication_contracts.py src/data/ingestion/daily_bar_publication.py tests/test_daily_bar_publication.py`（修改後） | 0 | 0 errors, 0 warnings, 0 notes |
| `python scripts/check_agents_length.py` | 0 | 80/100 lines、5127/16 KiB、combined 22074/28 KiB |
| `git diff --check` | 0 | passed；只有既有 Windows LF/CRLF warnings |
| `git diff --name-status` | 0 | reviewed |
| `git status --short --branch` | 0 | reviewed |

`uv run --system-certs --extra test pytest -q tests/test_twse_archive_feature_dataset.py -k publication`
本次未重跑；沿用前一 PARTIAL task 已記錄的 exit code 0，原因是本微任務沒有修改產品實作或該測試。

### Fast and full verification

| Command | Exit code | Result |
|---|---:|---|
| `pwsh -File scripts/verify-fast.ps1` | 0 | 17 tests；Fast verification passed |
| `pwsh -File scripts/verify-full.ps1`（首次） | 1 | 984 passed、1 failed；ACTIVE task status heading 後多一空白行，分類為本微任務 task-format issue |
| `git diff --check`（task-format 修正後） | 0 | passed |
| `pwsh -File scripts/verify-full.ps1`（修正 task-format 後） | 0 | Python 985 passed；Playwright 65 passed；Full verification passed |

首次 full failure 只需在 Allowed file `tasks/active/TASK.md` 移除 `## Status`
與 `ACTIVE` 間的空白行；沒有修改測試或產品，沒有 repository-wide fix，後續 full 已通過。

### Archival closure checks

| Command | Exit code | Result |
|---|---:|---|
| `uv run --system-certs --extra test pytest -q tests/test_codex_workflow_contract.py::test_single_active_task_structure` | 0 | 1 passed；確認 restored `NONE` structure |
| `git hash-object src/data/daily_bar_publication_contracts.py` | 0 | final hash unchanged |
| `git hash-object src/data/ingestion/daily_bar_publication.py` | 0 | final hash unchanged |
| `git diff --check` | 0 | archival state passed |
| `git diff --name-status` | 0 | final tracked paths reviewed |
| `git status --short --branch` | 0 | final tracked and untracked paths reviewed |

## Repair Rounds

Test repair rounds：0／2。初始 test-only correction 後所有 focused commands 首次即通過，
沒有在 focused command 失敗後再次修改 `tests/test_daily_bar_publication.py`。
Full verification 的 ACTIVE task 格式修正不涉及測試檔，因此不計入定義中的 test repair round。

## Final Task State and Permissions

- 本完成紀錄參照並保留前一歷史紀錄
  `tasks/completed/2026-07-22-extract-daily-bar-publication-source-contracts.md`；未修改該 PARTIAL record。
- `tasks/active/TASK.md` 已恢復為標準 `# No active task`／`Status: NONE`。
- 未 commit、push、建立或合併 PR、部署、修改 production、formal data、secrets、DNS、billing、
  branch protection、repository ruleset 或任何遠端資源。
- 未建立新 worktree、clone、cloud sandbox 或 repository copy。

## Remaining Risk

指定 focused、fast 與 full checks 均已通過，沒有尚未驗證的本任務事項或已知剩餘失敗。
工作樹仍故意保留前一 extraction 任務的未提交／未追蹤變更；本任務沒有處理或擴大它們。
