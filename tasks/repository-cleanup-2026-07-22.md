# Repository restructuring and cleanup report

日期：2026-07-22

## Deleted Files

本次沒有刪除 tracked file。盤點未找到能同時通過引用、設定、動態載入、歷史及替代方案檢查的確定廢棄檔案；不為了增加刪除數量而移除用途不明或受保護內容。

## Retained Cleanup Candidates

### Path: `scripts/backtest.py`

- Why it may be obsolete: 只把參數轉傳至 `src.pipeline.cli`，repository 內沒有直接引用。
- Why deletion is not yet safe: 可能是使用者或外部排程保留的相容 CLI entry point；Git 歷史顯示它與初始研究管線同時建立。
- Required evidence: 發布文件、外部排程與實際使用紀錄確認都已改用 `src.pipeline.cli backtest`。

### Path: `scripts/train.py`

- Why it may be obsolete: 只把參數轉傳至共用 pipeline CLI，repository 內沒有直接引用。
- Why deletion is not yet safe: 可能是人工訓練命令的既有相容入口，刪除會造成 repository 外使用者失敗。
- Required evidence: 確認所有本機操作說明與外部 runner 已改用 `src.pipeline.cli train`。

### Path: `scripts/infer_daily.py`

- Why it may be obsolete: 只把參數轉傳至共用 pipeline CLI，repository 內沒有直接引用。
- Why deletion is not yet safe: 檔名符合可能由排程或人工執行的穩定 entry point，repository 搜尋無法證明外部未使用。
- Required evidence: 核對所有排程、runbook 與 shell history 已遷移至 `src.pipeline.cli infer`。

### Path: `model_card.md`

- Why it may be obsolete: 與 `model_card.json` 表達部分相同資訊。
- Why deletion is not yet safe: README 與根 AGENTS 明確連結此人類可讀模型卡。
- Required evidence: 先建立可由 JSON 穩定產生且保留完整說明的替代閱讀流程，再更新所有連結。

### Path: `model_card.json`

- Why it may be obsolete: 與 Markdown 模型卡內容部分重複。
- Why deletion is not yet safe: README 將它列為機器可讀模型卡，後續 promotion 或外部工具可能依賴結構化格式。
- Required evidence: 契約搜尋與發布 consumer 稽核證明沒有機器端讀取者。

### Path: `src/vendor/sentry-10.66.0.min.js`

- Why it may be obsolete: 屬 vendored 產生物，可由套件來源重新取得。
- Why deletion is not yet safe: `index.html` 直接載入，Playwright 也攔截該確切路徑；目前是 Production runtime dependency。
- Required evidence: 先完成受控替代載入、CSP 與離線/錯誤監控驗證。

### Path: `src/vendor/supabase-2.110.7.min.js`

- Why it may be obsolete: 屬 vendored SDK bundle，可由套件管理器產生。
- Why deletion is not yet safe: `src/data/supabase-sdk-loader.js` 直接以確切檔名動態載入，E2E 測試也依賴該路徑。
- Required evidence: 先完成 bundler 或新 loader 遷移及 Auth 全流程驗證。

### Path: `supabase/.gitignore`

- Why it may be obsolete: repository 根目錄已有 `.gitignore`。
- Why deletion is not yet safe: 子目錄規則額外排除 Supabase `.branches`、`.temp` 與 dotenvx local key 檔，並非完全重複。
- Required evidence: 根規則完整涵蓋相同範圍，且 Supabase CLI 不再需要 scoped ignore。

## Confirmed Retentions

- `requirements.lock`：仍由多個資料匯入與 readiness workflows 安裝及快取，不可由 `uv.lock` 取代後直接刪除。
- `docs/*.md`：是領域事實與目前狀態文件；`.ai/*.md` 是精簡代理指令，責任不同。
- GitHub workflows、migrations、schema、lockfiles、model cards、provenance 與 completed task records 均依受保護規則保留。

## Cleanup Summary

- Files deleted: 0
- Directories removed: 0 tracked directories
- Local generated cleanup: 1 ignored coverage file and 30 ignored cache/build directories removed after verification
- Files added to `.gitignore`: 3 local cache patterns (`.ruff_cache/`, `.mypy_cache/`, `.pyright/`)
- Uncertain files retained: 8
