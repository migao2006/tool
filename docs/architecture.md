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

## 三、模型拆分

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

## 四、拆分標準

應拆分的情況：

- 同時負責兩項以上主要工作。
- 需要因不同原因修改。
- 無法獨立測試。
- 包含大量共享狀態。
- 頁面同時處理 UI、API 與資料轉換。
- 模型同時處理訓練、推論及部署。

不得為拆分而建立大量只有 import、轉傳或重新命名功能的檔案。
