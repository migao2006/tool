# Extract Daily-Bar Publication Source Contracts

## Status

PARTIAL

## Goal

將 daily-bar publication 的四個純資料契約從
`src/data/ingestion/daily_bar_publication.py` 抽出至
`src/data/daily_bar_publication_contracts.py`，由舊模組明確 import 並
re-export，完整保留既有公開行為與 import path。

## Confirmed Context

- 目前沒有已確認的功能缺陷，本次只做行為不變的模組抽取。
- 舊模組混合純資料契約與 Supabase、Parquet、R2、manifest、publication service 責任。
- 現有未追蹤的 `tasks/completed/2026-07-22-select-first-reconstruction-target.md`
  屬本任務開始前的分析紀錄，本次未修改。
- 最多允許兩輪自動修復。

## In Scope

- 抽出 `DAILY_BAR_PUBLICATION_SCHEMA_VERSION`。
- 抽出 `DAILY_BAR_PUBLICATION_CONTENT_TYPE`。
- 抽出 `DailyBarPublicationSourceRow`。
- 抽出 `DailyBarPublicationSourceSnapshot`。
- 在舊模組保留明確 import/re-export。
- 在既有 publication 測試補足 characterization、contract 與相容性覆蓋。
- 比較固定輸入的 mapping、例外型別、例外訊息與 class identity。

## Allowed Files

1. `tasks/active/TASK.md`
2. `src/data/daily_bar_publication_contracts.py`
3. `src/data/ingestion/daily_bar_publication.py`
4. `tests/test_daily_bar_publication.py`
5. `tasks/completed/2026-07-22-extract-daily-bar-publication-source-contracts.md`

## Out of Scope

- 重建 publication service。
- 修改 Supabase、Parquet、R2、manifest、I/O 或 reason codes。
- 修改 schema version、content type、欄位、驗證門檻或依賴版本。
- 修改 workflow、其他 caller 或 Allowed Files 以外的任何檔案。
- 修復其他缺陷、commit、push、建立 PR、部署或正式資料操作。

## Constraints

- 常數名稱和值、dataclass 欄位順序與型別、建構方式、validation invariant、
  `ValueError` 型別與訊息、mapping、equality 與 serialization 行為均須一致。
- 舊 import path 必須繼續可用；新舊 import 必須取得相同 class object。
- 不得手動修改 class `__module__`，除非找到明確 pickle 或反射證據。
- 若需要第六個檔案，立即停止並回報。
- 任何失敗先停止後續驗證，只修復本次造成的問題，最多兩輪。

## Execution Plan

1. 執行 Git preflight 並確認既存變更。
2. 讀取必要產品、架構、決策、目標程式與測試。
3. 補足 characterization 與 contract tests。
4. 先執行新增測試，確認測試設計有效。
5. 建立新契約模組並移除舊模組的重複定義。
6. 由舊模組明確 import/re-export，不遷移其他 caller。
7. 比較固定輸入、輸出、例外與 mapping。
8. 依序執行 focused、fast、full verification。
9. 記錄實際結果、封存任務並將 active task 恢復為 NONE。

## Validation Commands

1. `uv run --system-certs --extra test pytest -q tests/test_daily_bar_publication.py`
2. `uv run --system-certs --extra test pytest -q tests/test_twse_archive_feature_dataset.py -k publication`
3. `uv run --with "ruff==0.15.22" ruff check src/data/daily_bar_publication_contracts.py src/data/ingestion/daily_bar_publication.py tests/test_daily_bar_publication.py`
4. `uv run --with "basedpyright==1.39.9" basedpyright src/data/daily_bar_publication_contracts.py src/data/ingestion/daily_bar_publication.py tests/test_daily_bar_publication.py`
5. `python scripts/check_agents_length.py`
6. `git diff --check`
7. `git diff --name-status`
8. `pwsh -File scripts/verify-fast.ps1`
9. `pwsh -File scripts/verify-full.ps1`

## Definition of Done

- 新契約模組已建立，舊模組保留相容 import/re-export。
- 所有指定 contract、publication 與 research dataset 測試通過。
- Ruff、basedpyright、Agent instruction、Git、fast 與 full verification 通過，
  或 full 只揭露經證實與本次無關的既有失敗。
- 沒有未解釋的新舊行為差異。
- 沒有修改 Allowed Files 以外的檔案。
- 沒有正式環境操作。

## Results

- 已建立 `src/data/daily_bar_publication_contracts.py`，只公開指定的兩個常數與兩個 frozen dataclass。
- 舊模組已移除四個重複定義，改為明確 import；既有名稱仍由舊模組直接取得相同 class object。
- 新增 9 個 characterization／contract tests；連同既有 round-trip test 共 10 tests 通過。
- 固定輸入的常數、class identity、欄位、equality、canonical mapping、Parquet mapping、ValueError 型別與訊息均由測試鎖定，未發現未解釋差異。
- 預定 TDD red：首次執行 publication 測試 exit 1，唯一原因為新模組尚未建立的 `ModuleNotFoundError`；建立新模組後同命令 exit 0。
- `uv run --system-certs --extra test pytest -q tests/test_daily_bar_publication.py`：實作後 exit 0，10 passed。
- `uv run --system-certs --extra test pytest -q tests/test_twse_archive_feature_dataset.py -k publication`：exit 0，1 passed。
- `uv run --with "ruff==0.15.22" ruff check src/data/daily_bar_publication_contracts.py src/data/ingestion/daily_bar_publication.py tests/test_daily_bar_publication.py`：exit 0。
- `uv run --with "basedpyright==1.39.9" basedpyright src/data/daily_bar_publication_contracts.py src/data/ingestion/daily_bar_publication.py tests/test_daily_bar_publication.py`：exit 1；既有 round-trip test 的 `MemoryStore` 與 `MemoryManifestRepository` 不符合 service 具體型別。該呼叫與原有 `# type: ignore[arg-type]` 均不在本次 diff 變更區塊內，分類為本次修改前已存在。
- 依失敗規則未修復既有 basedpyright 問題，未執行後續 Agent instruction、Git diff、fast 或 full verification。
- 修復輪數 0；沒有修改 Allowed Files 以外的 tracked paths。
- 未修改 `__module__`。Repository 內沒有 pickle／反射相容性證據；新建物件的 class module path 會改為新契約模組，舊 import path 仍可解析相同 class object。
- 未 commit、push、建立 PR、部署或修改正式資料／遠端資源。
