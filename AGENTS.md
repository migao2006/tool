# 專案代理核心規範

架構一定要分開；拆分必須降低耦合、提升可測試性，不得建立巨型檔案或只有轉傳用途的假分層。

本專案是台股 2～10 個交易日短波段預測系統，目前唯一正式產品範圍為 5 個交易日選股 MVP，模型狀態維持 `RESEARCH_ONLY`，直到資料與樣本外驗收全部通過。

## 必讀文件

依任務閱讀最小必要範圍：

- 架構與依賴：`.ai/architecture.md`
- 產品與顯示契約：`.ai/product.md`
- 既定決策與外部操作：`.ai/decisions.md`
- 審查與清理：`.ai/code-review.md`
- 驗證程序：`.agents/skills/repository-verification/SKILL.md`
- 即時狀態：`docs/current-status.md`、`model_card.md`
- 領域細節：`docs/` 中與任務直接相關的文件

## 優先順序

1. 資料安全、時間正確性、禁止捏造與禁止洩漏機密。
2. 使用者當次任務的明確要求。
3. 產品範圍、架構邊界與發布限制。
4. 保留正常功能及既有無關修改，採最小可回復變更。
5. 開發速度與便利性。

## 不可違反

- 不得加入假資料、假績效、假模型輸出或保證獲利文字。
- 所有特徵必須滿足 `available_at <= decision_at`；不得使用未來資料或修正後資料回填歷史。
- 不得洩漏、讀回、記錄或提交 secret、token、密碼、私鑰及 `service_role`。
- 不得關閉 TLS、RLS、Auth 或其他安全機制來繞過問題。
- 不得覆蓋使用者無關修改；任務開始與結束都要檢查 Git 差異。
- 未經明確授權不得刪除正式資料、R2 object、遠端資源、分支、release 或部署歷史。

## 產品與模型不變條件

- 正式支援值只有 `horizon=5`；介面接受 horizon，但其他值回傳 `UNSUPPORTED_HORIZON`。
- ETF 不得混入普通股票候選清單或訓練資料。
- 排名模型是唯一個股排序來源；方向、分位數、市場與波動模型只負責門檻或曝險。
- `decision_policy` 不得建立任意加權的第二套排名。
- Hard fail 不得產生正式候選；缺資料必須顯示缺漏，不得以 placeholder 數字代替。
- 正式輸出必須可追溯至資料、標籤、特徵、成本、校準、模型與 Git 版本。

## 架構邊界

- UI 不得包含模型、SQL、R2 或資料庫邏輯；pages 只負責組合元件。
- 外部 API、Supabase 與 R2 必須透過 client、adapter 或 repository 接入。
- 排名、方向、分位數、波動、市場、標籤、決策、驗證與回測必須分模組。
- 禁止循環依賴、跨層捷徑與重複共用邏輯。
- 行數只是警示；檔案約 300 行、UI 元件約 150 行或出現多重責任時優先拆分。

## 執行與發布

- 先讀取相關程式、schema、測試、設定與歷史，再修改最小必要範圍。
- 只回報實際執行過的操作與結果；失敗、跳過及環境限制必須明示。
- GitHub 是唯一人工正式發布入口；不得用 Vercel CLI 直接 Production deploy 或 promote。
- Production migration 必須先完成隔離環境驗證、history 對齊與 rollback 演練。
- R2 原始封存預設 immutable；多年 Parquet 存 R2，Supabase 只存控制、manifest、稽核與前端摘要。
- 當次任務禁止 Commit、Push、PR、Pull、部署或正式操作時，該限制優先於一般發布流程。

## 完成條件

- 執行與風險相稱的測試、`git diff --check` 及適用的 fast/full verification。
- 檢查未追蹤檔、意外刪除、broken references 與機密。
- 未通過 point-in-time、purged walk-forward、校準、locked holdout 與完整成本回測時，狀態只能是 `RESEARCH_ONLY` 或 `FAIL`。
- 根 `AGENTS.md` 不得超過 100 行或 16 KiB；合併代理指令不得超過 28 KiB。
