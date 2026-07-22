# 架構與依賴規範

本文件補充根 `AGENTS.md` 的程式邊界。實際現況以 `docs/architecture.md` 與程式碼為準；不得把目標目錄誤稱為已完成實作。

## 依賴方向

允許的主要方向為：

```text
pages
  -> components / controllers
  -> services / use cases
  -> decision / models / calibration
  -> features / labels / validation / backtest
  -> data contracts / domain types
```

- `pages` 不得直接呼叫模型、SQL、R2 或 Supabase。
- `components` 不得依賴 `pages`，也不得自行建立資料庫或模型 client。
- `models`、`features`、`labels`、`calibration` 不得依賴 UI、router、瀏覽器狀態或資料庫 SDK。
- 外部資料必須透過具名 client、adapter 或 repository；domain logic 不得依賴供應商回傳格式。
- 禁止循環依賴、深層模組修改全域 UI state，或用跨層 import 繞過公開契約。

## 模組責任

- `src/data/`：來源 client、point-in-time 契約、正規化、repository 與 object storage。
- `src/features/`：只使用當下可得資料產生可稽核特徵。
- `src/labels/`：統一交易路徑、成本後報酬與標籤。
- `src/models/`：排名、方向、分位數、市場與風險模型各自獨立。
- `src/calibration/`：方向機率及分位數區間校準。
- `src/decision/`：gate、Top-K、容量與部位限制；不得重新排名。
- `src/validation/`：purged walk-forward、時間切割與統計評估。
- `src/backtest/`：成交、成本、限制、cohort、現金與持倉模擬。
- `src/pages/`、`src/components/`、`src/styles/`：顯示與互動，不包含資料或模型業務規則。

## 資料流

```text
GitHub Actions / isolated runner
  -> provider clients
  -> ingestion and validation
  -> private R2 immutable Parquet
  -> Supabase queue / manifest / audit / UI summary
  -> canonical research dataset
  -> purged walk-forward research output
```

前端不得直接讀寫 R2、供應商 API 或 `service_role`。R2 client 只負責 object I/O；Supabase repository 只負責資料庫契約，不得彼此複製。

## 拆分準則

在下列情況優先拆分：兩項以上主要責任、不同原因修改、無法獨立測試、大量共享狀態、UI/API/轉換混寫，或模型同時處理訓練與發布。

不得為符合行數而建立大量只做 import、重新命名或轉傳呼叫的碎片。共用 artifact、metadata、horizon 與 schema 驗證只保留一份。

## 跨模組契約

- API、資料表、artifact 與 reason code 使用版本化 schema。
- 時間戳必須帶時區；內部標準為 UTC，台股交易日及 UI 為 `Asia/Taipei`。
- Horizon、label、feature schema、calibrator、成本與模型 artifact 必須相互綁定。
- 動態載入、檔名掃描與 workflow 路徑屬隱性依賴，刪檔前必須納入搜尋。
