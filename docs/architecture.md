# 程式架構規範

## 一、目錄邊界

```text
src/
  pages/
  components/
  styles/
  core/
  services/
  data/
  labels/
  features/
  models/
  calibration/
  decision/
  validation/
  backtest/
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

- pages 不得直接呼叫模型、SQL 或 Supabase。
- components 不得依賴 pages。
- models、features、labels、calibration 不得依賴 UI 或資料庫 SDK。
- 外部 API 與資料庫必須透過 client、adapter 或 repository 接入。
- 禁止循環依賴。
- 禁止深層模組直接修改全域 UI state。

## 三、歷史資料儲存與執行邊界

```text
GitHub Actions scheduler
  ↓
provider client → ingestion / validation
  ├─→ private Cloudflare R2：immutable Parquet 原始封存
  └─→ Supabase：queue、manifest、稽核 metadata、首頁摘要
```

- 多年歷史行情不得經由瀏覽器或 Vercel 前端直接寫入；只有 GitHub Actions 後端 worker 可以執行回補。
- R2 client 只負責 object I/O；Supabase repository 只負責任務、manifest 與摘要，不得互相複製實作。
- 三個 FinMind credential worker 可並行下載，但共用任務清單只能由 primary worker 建立，首頁摘要只能由單一 finalizer 更新。
- 頁面及 React 元件只能透過 service/API 取得已授權的聚合結果，不得直接讀取 R2 object、Supabase SQL 或機密。

## 四、模型拆分

模型必須分成獨立模組：

```text
models/
  common/
  stock/
    rank/
    direction/
    quantile_return/
  market/
    direction/
    regime/
  risk/
    volatility/
    downside/
  trading/
    triple_barrier/
```

每個模型可分為：

- train
- predict
- schema
- 對應測試

共用的 artifact、metadata、horizon 驗證及 schema 驗證集中於 `models/common/`，不得在各模型重複實作。

## 五、拆分標準

應拆分的情況：

- 同時負責兩項以上主要工作。
- 需要因不同原因修改。
- 無法獨立測試。
- 包含大量共享狀態。
- 頁面同時處理 UI、API 與資料轉換。
- 模型同時處理訓練、推論及部署。

不得為拆分而建立大量只有 import、轉傳或重新命名功能的檔案。
