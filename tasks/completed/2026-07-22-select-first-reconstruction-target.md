# Select First Reconstruction Target

## Status

COMPLETE

## Goal

分析現有 Repository，選出第一個適合漸進式重建的檔案或
緊密耦合元件，建立明確契約、影響範圍與後續微任務計畫。

本階段不得修改產品程式碼。

## Confirmed Context

- 專案存在大型檔案、責任混合、檔案散亂及既有 Bug。
- 不允許一次重寫整個 Repository。
- 每次只能處理一個檔案或一個緊密耦合元件。
- 每個實作微任務最多修改 5 個 tracked files。
- 最多允許兩輪自動修復。
- 不得自行處理範圍外問題。
- 不得 Commit、Push、建立 PR 或部署。

## In Scope

- 讀取 Repository 結構。
- 分析大型檔案與模組責任。
- 找出直接呼叫者與執行入口。
- 檢查現有測試與契約。
- 選出第一個重建目標。
- 建立該目標的下一份微任務草案。

## Out of Scope

- 修改產品程式碼。
- 搬移產品檔案。
- 刪除任何 tracked file。
- 修復既有 Bug。
- 修改測試、CI、資料庫、部署或依賴。
- 執行完整 Repository 重構。

## Constraints

- 不得把推測標示為已確認事實。
- 不得只根據檔案行數決定重建順序。
- 必須檢查 import、呼叫者、動態載入、Workflow 與 Git 歷史。
- 優先選擇責任清楚、依賴較少、可獨立測試的目標。
- 不得優先處理模型、正式資料發布或高風險 Migration。
- 不得修改本次任務開始前已存在的無關變更。

## Execution Plan

1. 執行 Git preflight。
2. 讀取 AGENTS.md 與必要架構文件。
3. 找出大型檔案及責任混合模組。
4. 評估依賴、呼叫者、測試與風險。
5. 依證據選出第一個重建目標。
6. 提出下一個實作微任務，但本次不執行。

## Validation Commands

git status --short --branch
git diff --name-status
git diff --check

## Definition of Done

- 已選出唯一的第一個重建目標。
- 已列出該目標的目前責任。
- 已列出直接呼叫者及動態載入風險。
- 已列出需要保留的公開契約。
- 已列出缺少的測試。
- 已估算下一個任務的修改檔案。
- 下一個任務預計不超過 5 個 tracked files。
- 本階段未修改任何產品程式碼。

## Results

- 唯一目標：從 `src/data/ingestion/daily_bar_publication.py` 漸進抽出 daily-bar publication 的純來源契約群組；不重建發布服務、R2、Supabase、manifest repository、CLI 或資料庫契約。
- 選擇依據：原檔同時承擔來源 DTO 與驗證、Supabase 查詢、Parquet 序列化、R2 完整性驗證、manifest 組裝及發布協調；純來源契約本身只依賴標準函式庫，適合先隔離。檔案長度只是警訊，不是選擇依據。
- 保留公開契約：`DAILY_BAR_PUBLICATION_SCHEMA_VERSION`、`DAILY_BAR_PUBLICATION_CONTENT_TYPE`、`DailyBarPublicationSourceRow`、`DailyBarPublicationSourceSnapshot` 的既有 import path、欄位、驗證、mapping 輸出與例外行為；舊模組必須保留相容 re-export。
- 直接產品 caller：`src/data/research/daily_bar_publication_snapshot.py` 使用兩個常數與 `DailyBarPublicationSourceRow`；`src/data/research/archive_feature_rows.py` 使用 `DailyBarPublicationSourceRow`；`scripts/publish_daily_bar_publication_snapshots.py` 是發布服務的 CLI 入口並透過舊模組使用契約。
- 測試 caller：`tests/test_daily_bar_publication.py` 覆蓋 500 列 immutable Parquet/R2 round trip；`tests/test_twse_archive_feature_dataset.py` 覆蓋 publication row 進入特徵資料且維持 `available_at <= decision_at`。
- Dynamic loading：在 `src/`、`tests/`、`scripts/`、`.github/` 中未找到以 importlib、`__import__`、pkgutil 或檔名慣例動態載入此模組的證據。
- Workflow：`.github/workflows/daily-research-model.yml` 明確監看舊模組路徑與 `src/data/research/**`；下一任務保留並修改舊相容模組，因此該次變更仍會命中既有 path filter。移除 adapter 前必須重新檢查並更新 workflow path。
- Git 歷史：`git log --follow` 只找到 `0c78686` 新增此檔，未找到 rename 歷史；無證據支持刪除舊 import path。
- 已有測試缺口：未直接鎖定 source row/snapshot 的所有 ValueError 邊界、canonical/parquet mapping 完整 schema、舊新 import identity，以及相同固定輸入在抽出前後的例外型別與訊息。
- 下一微任務草案：新增 `src/data/daily_bar_publication_contracts.py`，只移入兩個常數與 source row/snapshot 契約；舊檔以明確 import/re-export 保持相容；在既有 publication 測試加入契約與相容性 characterization。不得遷移 caller、改 reason code、改 schema、改 workflow 或改 I/O。
- 建議 allowed files：`tasks/active/TASK.md`、`src/data/daily_bar_publication_contracts.py`、`src/data/ingestion/daily_bar_publication.py`、`tests/test_daily_bar_publication.py`、`tasks/completed/2026-07-22-extract-daily-bar-publication-source-contracts.md`。
- 下一微任務預估最多 5 個 tracked paths；不需要刪除檔案。
- 本次驗證：`git status --short --branch` exit 0；`git diff --name-status` exit 0；`git diff --check` exit 0；`python scripts/check_agents_length.py` exit 0（80/100 行、5,127/16 KiB、合計 22,074/28 KiB）。
- 本次只修改任務紀錄；未修改產品程式碼、測試、CI、資料庫、部署或依賴，也未 commit、push、建立 PR 或部署。
