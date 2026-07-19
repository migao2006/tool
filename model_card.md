# Alpha Lens 5 日短波段選股 MVP 模型卡

> 最後核對：2026-07-20。OOS 驗證 workflow：[`29690820942`](https://github.com/migao2006/tool/actions/runs/29690820942)；最新橫截面研究推論 workflow：[`29695406502`](https://github.com/migao2006/tool/actions/runs/29695406502)；最新特徵 workflow：[`29693937930`](https://github.com/migao2006/tool/actions/runs/29693937930)；發布 commit：`be9ca59c4bbae18de88cd95b080ceecb4c60fda3`。動態資料與阻塞現況見 [`docs/current-status.md`](docs/current-status.md)。

## 狀態

- 系統狀態：`RESEARCH_ONLY`
- Horizon：`5`
- Scope：`TWSE_PRICE_ONLY`
- Model version：`twse-price-research-h5-v1`
- Training end date：`2024-06-18`
- Locked holdout：保留 170,032 列，尚未執行

這是已實際執行的 5-fold purged walk-forward 研究結果，不是假資料或訓練集表現。排名模型沒有優於 20 日動能基準，平均 Rank IC 為負，因此未通過正式驗收，不得視為正式推薦或獲利保證。

## 資料與追蹤

| 欄位 | 值 |
| --- | --- |
| Prepared records | 1,196,162 |
| Prepared Parquet SHA-256 | `9ca63d003f082948013545f2755bb0d4dea145d94aaebbcd358cd93f40b480be` |
| Dataset snapshot | `22f6747e395b2a893ea297496558b05bd59e10751ec6a27d7d8ad3560aa88c22` |
| Feature schema hash | `8e256243dbe0018a7a96a637b989e2338dcf06a8f2e9a9d42faf888c7f54cd53` |
| Source hash | `18c6aac3780bea72be2ebdae2803fbe86b8a42436f60101d6412199fc11a6701` |
| Label version | `twse-research-unadjusted-open-close-5d-v1` |
| Benchmark | `TWSE_TAIEX_PRICE_INDEX` |
| Benchmark version | `rwd.en.TAIEX.MI_5MINS_HIST.v1@snapshot:4c58a09fd1bbccc21416948eff8d31f77c31ba8568e2392493d0050f674c52c9` |
| Cost profile | `tw_stock_swing_v1:base_cost` |
| Random seed | `20260718` |
| LightGBM | `4.6.0` |
| scikit-learn | `1.9.0` |

上市研究 schema 包含 17 個價量特徵：1／2／3／5／10／20／60 日報酬、隔夜跳空、日內報酬、ATR14、RV20、下行波動 20、最大回撤 20、ADV20、週轉率均值 20、量能異常 20 與 Amihud20。

## 模型

- 排名：LightGBM `LGBMRanker`，objective `lambdarank`；唯一排序來源。
- 方向：LightGBM multiclass；以時間分離的 calibration 資料做 temperature scaling。
- 分位數：三個 LightGBM quantile models，分別預測 P10／P50／P90。
- 方向機率與分位數只作研究輸出及 gate，不重新加權排名。

## Walk-forward 結果

### 排名

五個 fold 各有 63 個 OOS 評估日期。

| 指標 | Rank model | 20 日動能基準 |
| --- | ---: | ---: |
| NDCG@10 | 0.311856 | 0.330156 |
| NDCG@20 | 0.305487 | 0.317444 |
| NDCG@50 | 0.287796 | 0.293994 |
| Precision@10 | 0.397460 | 0.402222 |
| Precision@20 | 0.391429 | 0.393968 |
| Precision@50 | 0.378413 | 0.377143 |
| Rank IC | -0.054552 | -0.023127 |
| ICIR | -0.358336 | -0.181064 |

Rank model 的 NDCG@10／20／50 與 Rank IC 均未優於 20 日動能基準，正式排名驗收未通過。

### 三分類方向

| 指標 | Fold 平均 |
| --- | ---: |
| Log loss | 1.037198 |
| Macro-F1 | 0.333102 |
| ECE | 0.030459 |
| Calibrated log loss | 1.042601 |
| Uncalibrated log loss | 1.043852 |
| Brier DOWN | 0.240387 |
| Brier NEUTRAL | 0.204621 |
| Brier UP | 0.179355 |

### 條件報酬分位數

| 指標 | Fold 平均 |
| --- | ---: |
| P10 breach rate | 12.1255% |
| P90 exceedance rate | 9.9223% |
| P10～P90 empirical coverage | 77.9522% |
| Mean interval width | 12.0048% |
| Pinball loss P10 | 0.009660 |
| Pinball loss P50 | 0.020166 |
| Pinball loss P90 | 0.010663 |
| Raw crossing rate | 0 |
| Final crossing rate | 0 |

P10／P50／P90 是條件報酬分位數，不是最低、平均、最高報酬，也不是獲利保證。

## 歷史 OOS 驗證快照

- `prediction_run_id`：`1`
- `as_of_date`：`2025-05-02`
- `decision_at`：`2025-05-02T17:00:00+08:00`
- 預測列數：672 檔上市股票
- 決策：`CANDIDATE=0`、`WATCH=0`、`NO_TRADE=672`
- Hard fail：0
- Prediction snapshot SHA-256：`f4fa5a50ebaa3f4820caadaf02c70525a7b6e93fd89d1fa89fbaac21cc7840d9`
- GitHub artifact：`8443586850`，digest `57eb16f26d50e2408020c51a4e1bef2f179e998819baf2f550bfc088c92e6b69`

Production Supabase 與前端可以讀取這批歷史 OOS 研究結果；全部列依保守決策政策保持 `NO_TRADE`。

## 最新橫截面研究推論

- Workflow：[`29701335309`](https://github.com/migao2006/tool/actions/runs/29701335309)
- Feature workflow：[`29693937930`](https://github.com/migao2006/tool/actions/runs/29693937930)
- `prediction_run_id`：`4`
- `as_of_date`：`2026-07-17`
- `decision_at`：`2026-07-17T17:00:00+08:00`
- Evaluation scope：`RETROSPECTIVE_RESEARCH_INFERENCE`
- 預測列數：1,068 檔上市股票
- 決策：`CANDIDATE=0`、`WATCH=0`、`NO_TRADE=1,068`
- 公開 API 資料品質：1,068 筆 `WARN`，0 筆 hard fail
- Industry coverage：0／1,068
- Decision gate rows：8,544；每檔固定 8 層
- Feature artifact SHA-256：`24c90589d51de6b0c06f084ca977c4bfb99993f91164d65b3bad33bce3c73aac`
- Model bundle SHA-256：`c41b76df09decf6be62da3cc59012597c7fd889d4980e43c14eb7cca70de5ca7`
- Prediction snapshot SHA-256：`4581af6f96eb56791a498343784e484a3c604ef7c32f549ffdbbfc7dce60f505`
- Snapshot artifact SHA-256：`605c19a53b4321e307848e4affa081c4a760601a3a0186a26192036c61395eee`
- GitHub artifact：`8446597593`，digest `b06a8280e9780f19378f682ed4ad55ff9017fb684cbe1dd9abc953d7d9948199`

模型 bundle 由最後一個 walk-forward fold 依固定規則建立，沒有用最新橫截面選模；相同 artifact、設定與 seed 的 bundle identity 可重現。這批資料是最新日期的回溯研究推論，不是新的 OOS 評估。Production API 已實測回傳 HTTP 200、1,068 檔且每檔恰好 8 層 fail-closed 研究 gate；缺少可交易性、市場曝險或部位輸入時不得推測通過。全部列固定為 `NO_TRADE`，不得描述為正式候選股、即時可交易建議或獲利保證。

## 標籤與交易路徑

本次研究 label 為 `twse-research-unadjusted-open-close-5d-v1`：個股與 TAIEX 價格指數均使用 t+1 open 至第 5 個持有交易日 close，個股再扣 `tw_stock_swing_v1:base_cost`。TAIEX 是 price index、不是 total-return index；這個 label 尚未解決 point-in-time 公司行動及正式可成交性，不是正式 executable total-return LabelFactory 產物。

正式目標仍為：

- 訊號：t 日所有資料實際發布後的 `decision_at`。
- 進場：t+1 交易日可成交開盤。
- 出場：進場後第 5 個交易日收盤。
- `R_net = R_gross - 買賣手續費 - 賣出證交稅 - 滑價 - 流動性／市場衝擊成本`。
- `alpha = R_net - 對應市場基準報酬`。

## Locked holdout 與正式驗收

Locked holdout 的 170,032 列因 `FROZEN_UNTIL_RESEARCH_DESIGN_IS_LOCKED` 尚未執行。只有在歷史 point-in-time 身分、公司行動、可交易性、正式 label、成本回測與模型設計凍結，且排名模型先於 development OOS 通過基準後，才能執行一次 locked holdout。

目前沒有正式完整成本 execution backtest、年化報酬、Sharpe、最大回撤或容量績效；不得推測或補寫這些數字。

## 已知限制

- 歷史身分仍使用 current security mapping，存在生存者偏誤與代號重用風險。
- 公司行動、停復牌、處置／變更交易方法及漲跌停可成交性尚未完成 point-in-time 驗證。
- 研究版 TAIEX 與個股已對齊進出場日期，但 TAIEX 仍是 price index 而非 total-return benchmark。
- Label 使用未還原 open-close 研究報酬，不是完整 executable total return。
- 尚無真實 bid／ask，無法驗證實際 spread、漲跌停成交與市場衝擊。
- 尚未執行 locked holdout 及完整 execution backtest。
- 排名模型未優於 20 日動能基準且 Rank IC 為負，因此系統必須維持 `RESEARCH_ONLY`。
- 最新快照是 `RETROSPECTIVE_RESEARCH_INFERENCE`，不是新的 OOS 評估；模型 training end 仍為 2024-06-18。
- 最新 1,068 筆均缺少可驗證的歷史產業分類，不能產生正式產業排名。
- 八層研究 gate 可稽核既有真實輸入，但尚未完成正式 cross-sectional Top-K 與部位配置；缺少可交易性、市場曝險或部位輸入的 gate 必須顯示未通過，不得自行補值。
- 上櫃須使用獨立股票池與櫃買基準；ETF 須使用獨立追蹤基準、成本與模型。兩者目前尚未進入正式訓練或前端候選清單。
