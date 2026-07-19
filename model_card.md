# Alpha Lens 5 日短波段選股 MVP 模型卡

> 最後核對：2026-07-19，Git commit `d32c3de47f7c119f1d9e231851cd5697fb3696ca`。動態資料與部署現況見 [`docs/current-status.md`](docs/current-status.md)。

## 狀態

- 系統狀態：`RESEARCH_ONLY`
- 正式 horizon：`5`
- 模型版本：尚未訓練
- training_end_date：N/A（尚未訓練）
- locked holdout：尚未執行

目前已由三組隔離的 FinMind credential 將真實歷史日線封存至 private Cloudflare R2；
2026-07-19 完整稽核涵蓋 1,687 個 objects、1,941,388 列，TWSE 1,080 檔與 TPEX 607 檔。
Supabase 保存 queue、manifest 與稽核摘要；但資料仍是目前股票池排程產生的
`UNVERIFIED / RAW_LANDING_ONLY / RESEARCH_ONLY` 原始資料，尚不可視為可靠的 point-in-time
訓練集。目前另已實作 TAIEX 總報酬基準、上市價量 feature artifact、研究資料組裝與 runner 的程式及契約，
但相關 feature gate 關閉、Production workflow 尚未執行，也尚未產生實際 benchmark／feature／model artifact。
不得將原始封存、單元測試或研究 runner 解讀為正式績效。

上市價量研究 schema 固定為 17 個特徵，schema hash：
`8e256243dbe0018a7a96a637b989e2338dcf06a8f2e9a9d42faf888c7f54cd53`。

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

- 已有真實 FinMind 歷史 OHLC 原始封存，但尚未完成歷史身分、未還原交易價格、公司行動、交易狀態及下市股票的 point-in-time 驗證。
- 目前普通股日線封存完整性通過，但 ETF 尚未納入普通股票模型，且尚未形成可靠的歷史股票池快照。
- 歷史公司行動／停復牌流程仍受 verified identity catalog gate 阻擋，不能冒充 point-in-time 證據。
- 正式 `label_factory` 尚未接入研究組裝器；目前研究輸出保留 `FORMAL_LABEL_FACTORY_NOT_USED`。
- 個股標籤使用 t+1 open 到第 5 個持有交易日 close，但 TAIEX 歷史基準只有 close 值，現行研究 adapter 的路徑尚未對齊。
- Dataset／benchmark provenance 尚有 caller 傳入欄位，未由 Parquet metadata、R2 hash 與 manifest snapshot 全面強制推導。
- 尚無真實 bid／ask，無法驗證漲跌停成交或滑價模型。
- 現有 R2 日線為 2021-07-19～2026-07-17，尚不足以同時提供至少 5 年 expanding train、calibration、test 與 12 個月 locked holdout；正式規劃應準備約 7 年以上可驗證資料。
- 尚未產生任何可發布的候選股、績效或預期報酬。
