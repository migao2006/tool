---
name: repository-verification
description: 驗證 Alpha Lens repository 的代理指令、受影響測試、Git 差異與完整回歸。
---

# Repository Verification

使用時機：完成程式、文件、清理或 repository 結構變更後。依風險選擇聚焦、fast 或 full；不得把未執行項目標示為通過。

## 前置檢查

1. 執行 `git status -sb` 與 `git diff --name-status`。
2. 確認既有使用者修改與本次範圍分開。
3. 不顯示 `.env`、token、密碼或任何 secret 值。

## 代理指令檢查

執行：

```powershell
python scripts/check_agents_length.py
```

成功輸出必須包含根 `AGENTS.md` 行數、16 KiB 大小及合併指令 28 KiB 大小。任何上限超標都必須失敗。

## 聚焦驗證

- Python：`uv run --system-certs pytest <affected tests>`。
- 前端：使用既有 Playwright web server，執行受影響 spec。
- Migration：先在 Docker Supabase Local reset/lint，再依發布規則操作 Staging。
- 文件與清理：檢查連結、引用、動態載入與 `git diff --check`。

## Fast verification

```powershell
pwsh -File scripts/verify-fast.ps1
```

Fast 必須檢查代理指令上限、直接契約測試與 `git diff --check`。失敗時立即停止並保留完整錯誤。

## Full verification

環境允許時執行：

```powershell
pwsh -File scripts/verify-full.ps1
```

Full 在 fast 之後執行完整 pytest 與 Playwright。需要瀏覽器、Docker 或外部服務時，如實說明可用性；不得以假結果取代。

## Windows 憑證

uv 使用 `--system-certs`；Node 遇到企業憑證鏈時，只在該工作階段設定 `$env:NODE_OPTIONS = "--use-system-ca"`。禁止停用 TLS 或設定 `strict-ssl=false`。

## 最終檢查

1. 執行 `git diff --check`。
2. 檢查 `git diff --stat`、`git diff --name-status` 與未追蹤檔。
3. 確認沒有意外刪除、產生物、機密或與任務無關的修改。
4. 清楚列出已通過、失敗、跳過及受環境阻擋的驗證。
