# 程式架構規範

> 2026-07-19 已依 `d32c3de` 核對。下列先記錄現有目錄，再說明允許的演進方向；不得把尚未建立的模組寫成已完成。完整狀態見 [`current-status.md`](current-status.md)。

## 一、目錄邊界

```text
src/
  api/
  auth/
  backtest/
  calibration/
  components/
  config/
  core/
  data/
    archive/
    canonical/
    ingestion/
    object_storage/
    providers/
    research/
  decision/
  features/
  labels/
  models/
  monitoring/
  pages/
  pipeline/
  quality/
  styles/
  trading/
  validation/
tests/
```

目錄名稱可依技術棧調整，但責任不可混合。

## 二、依賴方向

```text
pages
  ↓
components / controllers
  ↓
services / use cases
  ↓
decision / models / calibration
  ↓
features / labels / validation / backtest
  ↓
data contracts / domain types
```

規則：

- pages 不得直接呼叫模型、SQL、R2 或 Supabase。
- components 不得依賴 pages。
- models、features、labels、calibration 不得依賴 UI 或資料庫 SDK。
- 外部 API 與資料庫必須透過 client、adapter 或 repository 接入。
- 禁止循環依賴。
- 禁止深層模組直接修改全域 UI state。

## 三、歷史資料儲存與執行邊界

```text
GitHub Actions scheduler／owner-dispatched orchestrator
  ↓
provider client → ingestion / validation
  ├─→ private Cloudflare R2：immutable Parquet 原始封存
  └─→ Supabase：queue、manifest、稽核 metadata、首頁摘要
```

- 多年歷史行情不得經由瀏覽器或 Vercel 前端直接寫入；只有 GitHub Actions 後端 worker 可以執行回補。
- Owner 手動完整更新只由 `manual-full-update.yml` 呼叫既有 Import 與 Daily reusable workflows；
  aligned-date resolution、missing-market selection、ranking、Staging／Production publication
  與 validation 仍由既有實作負責。操作與 fail-closed 摘要契約見
  [`manual-full-update.md`](manual-full-update.md)。
- R2 client 只負責 object I/O；Supabase repository 只負責任務、manifest 與摘要，不得互相複製實作。
- 三個 FinMind credential worker 可並行下載，但共用任務清單只能由 primary worker 建立，首頁摘要只能由單一 finalizer 更新。
- 瀏覽器頁面及元件模組只能透過 service/API 取得已授權的聚合結果，不得直接讀取 R2 object、Supabase SQL 或機密。

目前研究資料流為：

```text
R2 raw Parquet
  → manifest／完整性驗證
  → TWSE 價量 feature artifact
  → research dataset assembler
  → purged walk-forward research runner
  → RESEARCH_ONLY artifact
```

基準、補充資料、事件證據及 feature workflow 的程式已建立，但 feature gate 尚未開啟，且 Production migration 尚未套用。生產回補只能由 GitHub Actions 執行；本機 script 只用於 dry-run、測試或隔離環境。

## 四、模型拆分

目前模型責任已分成下列檔案：

```text
models/
  metadata.py
  model_contracts.py
  stock/
    rank_model.py
    direction_model.py
    quantile_return_model.py
  market/
    market_model.py
  risk/
    volatility_model.py
```

當單一模型的訓練、推論或 schema 複雜度增加時，可以在維持公開契約相容下再拆成：

- train
- predict
- schema
- 對應測試

共用的 artifact、metadata、horizon 驗證及 schema 驗證應集中於 `models/metadata.py`、`models/model_contracts.py` 或後續明確的 common 模組，不得在各模型重複實作。Triple Barrier 屬第二階段，尚未建立正式模型模組。

目前 dataset assembler 的 dataset／benchmark provenance 仍有 caller 傳入欄位。正式使用前必須建立 typed artifact adapter，從 Parquet metadata、R2 object hash 與同一 manifest snapshot 自動驗證及衍生來源，不得接受任意 caller 聲明。

## 五、拆分標準

應拆分的情況：

- 同時負責兩項以上主要工作。
- 需要因不同原因修改。
- 無法獨立測試。
- 包含大量共享狀態。
- 頁面同時處理 UI、API 與資料轉換。
- 模型同時處理訓練、推論及部署。

不得為拆分而建立大量只有 import、轉傳或重新命名功能的檔案。

2026-07-19 行數稽核仍有多個檔案超過約 300 行，包括下列優先檢視項目；這不代表可在無關任務中任意重寫：

- `src/pipeline/twse_research_row_assembler.py`
- `src/data/ingestion/historical_daily_bar_archive_service.py`
- `src/data/ingestion/supabase_writer.py`
- `src/data/ingestion/historical_parquet_serializer.py`
- `src/data/point_in_time_dataset.py`
