# Alpha Lens 5 日短波段選股 MVP 模型卡

## 狀態

- 系統狀態：`RESEARCH_ONLY`
- 正式 horizon：`5`
- 模型版本：尚未訓練
- training_end_date：尚無資料
- locked holdout：尚未執行

目前專案沒有可供可靠訓練的真實歷史台股 point-in-time 資料，因此本次交付只建立可訓練、可回測、可每日推論的契約與程式架構。不得將任何單元測試資料解讀為正式績效。

## 決策架構

1. `data_quality` 與可交易性 hard gate。
2. `rank_model` 產生唯一個股排序。
3. 校準後三分類機率與 net P10／P50／P90 只作交易門檻。
4. 市場模型只控制總曝險。
5. 波動模型只控制部位大小。
6. 回測使用 t+1 可成交開盤、5 個交易日後收盤退出及 staggered cohorts。

## 標籤

- 訊號：t 日所有資料實際發布後的 `decision_at`。
- 進場：t+1 交易日可成交開盤。
- 出場：進場後第 5 個交易日收盤。
- `R_net = R_gross - 買賣手續費 - 賣出證交稅 - 滑價 - 流動性／市場衝擊成本`。
- `alpha = R_net - 對應市場基準報酬`。

上市與上櫃分別使用版本化基準；ETF 不與普通股混合訓練。

## 模型候選

- 排名：LightGBM LambdaMART；基準為隨機、5／20 日動能、線性回歸排序、LightGBM regress-then-rank。
- 方向：Logistic Regression 基準、LightGBM multiclass challenger，另行做時間序列校準。
- 分位數：P10／P50／P90 Quantile LightGBM，先預測 gross executable return，再扣成本。
- 市場方向：Logistic Regression；regime 使用 trailing-only 透明規則。
- 波動：trailing、EWMA、HAR 與 LightGBM；LightGBM 不穩定勝出時回退基準。

## 驗收門檻

所有特徵必須滿足 `available_at <= decision_at`；train／calibration／test label window 必須零重疊。只有 locked holdout、排名、機率校準、分位 coverage、波動與完整成本回測同時符合設定門檻後，狀態才能由 `RESEARCH_ONLY` 升為 `PASS`。

## 已知限制

- 尚無真實未還原 OHLC、公司行動、歷史交易狀態及下市股票資料。
- 尚無真實 bid／ask，無法驗證漲跌停成交或滑價模型。
- 尚無 5 年以上 expanding-window 訓練樣本與 12 個月 locked holdout。
- 尚未產生任何可發布的候選股、績效或預期報酬。

