# 目前實作與阻塞狀態

> 更新日期：2026-07-20（Asia/Taipei）
>
> 文件基準：`be9ca59`；OOS 驗證 workflow 使用 `29690820942`，最新特徵與研究推論 workflow 使用 `29693937930`、`29695406502`
>
> 系統狀態：`RESEARCH_ONLY`

本文件只記錄已由實際 workflow、資料庫、artifact 或稽核結果證實的現況。資料管線已能累積原始行情、產生研究資料集，並完成第一次真實 5 日 purged walk-forward 訓練與 Production 研究快照發布。排名模型未優於 20 日動能基準，平均 Rank IC 也為負；locked holdout 尚未執行，因此不得產生正式 `CANDIDATE` 或把研究產物描述為正式推薦。

## 一、環境與 Migration

### Supabase Staging

- 已建立每月費用為 `$0` 的獨立 Staging 專案 `alpha-lens-staging`。
- Project ref：`kretvnnfavndkmckyidl`。
- 專案狀態：`ACTIVE_HEALTHY`。
- Staging migration history 已與 Production 對齊，共 31 筆 migrations。
- 最新 migration 為
  `20260719152201_publish_research_snapshot_atomically.sql`。
- 新約束已實測允許來源日期後才取得的快照，仍拒絕未來快照日期，且驗證資料無殘留。
- `supabase db lint --linked --level error`：0 個 schema error。
- Supplemental task transaction RPC 與研究快照原子發布 RPC contract：`PASS`。
- 原子發布 RPC 已完成 transaction rollback 演練；`anon` 與 `authenticated` 不可執行，只有 `service_role` 可執行。
- Staging 只用於隔離驗證；它不是 Supabase Pro Branching，也不是 Production。

### Supabase Production

- Production migration history 已與 Staging 對齊，共 31 筆 migrations，最新為
  `20260719152201_publish_research_snapshot_atomically.sql`。
- Production `db lint` 沒有 schema error；原子發布 RPC 權限已驗證為 service-role only。

### 本機隔離環境

- Docker Engine `29.6.1`、Docker Compose `5.3.0` 與 Docker Desktop 已驗證可用。
- Supabase Local 已用 Docker 完整重建 31 個 migrations。
- 新 security snapshot 約束、rollback 及 `supabase db lint` 已實際通過。

## 二、已封存及已產生的真實資料

### 歷史普通股日線行情

GitHub Actions run `29677606085` 的 R2 完整稽核結果：

| 項目 | 已驗證數量 |
| --- | ---: |
| Parquet objects | 1,971 |
| 總列數 | 2,183,917 |
| 總位元組 | 295,007,049 |
| TWSE symbols | 1,080 |
| TPEX symbols | 891 |

- Object 與 manifest 的完整性稽核為 `PASS`。
- 這批資料仍是 `RAW_LANDING_ONLY`、`POINT_IN_TIME_UNVERIFIED`、`RESEARCH_ONLY`。
- 完整性 `PASS` 只代表 object、hash 與 manifest 可讀且一致，不代表可直接用於正式模型。

2026-07-20 的 Production manifest 即時統計已增至 4,054 個 `daily_bars` objects、
3,882,062 列。這是資料庫 manifest 統計，不等同於重新完成 4,054 個 objects 的全量
R2 integrity audit；正式完整性證據仍以上述 run `29677606085` 為準。

### 台股交易日曆觀測

- Supabase 已保存 2,077 筆 calendar observations。
- 觀測範圍為 2018-01-02 至 2026-07-17。
- 目前仍屬研究排程提示；尚未完成可驗證開收盤時間、臨時休市及 decision cutoff 的正式 point-in-time 契約。

### TAIEX 歷史基準

GitHub Actions run `29678818649`：

- 執行成功。
- 已產生 1 個 benchmark Parquet object。
- 共 1,214 列。
- 範圍為 2021-07-19 至 2026-07-17。
- 現況仍是 `RESEARCH_ONLY`、`POINT_IN_TIME_UNVERIFIED`、`NOT_EXECUTION_PATH_ALIGNED`。
- 基準目前是 close-based 歷史序列，尚未與股票的 `t+1 可成交開盤進場／第 5 個交易日收盤退出` 路徑完全對齊。

### 上市股票研究特徵

[GitHub Actions run `29693937930`](https://github.com/migao2006/tool/actions/runs/29693937930) 已在 commit
`be9ca59c4bbae18de88cd95b080ceecb4c60fda3` 產生 v2 特徵 artifact：

| 項目 | 已驗證結果 |
| --- | ---: |
| 執行狀態 | success |
| Dataset version | `twse-archive-price-volume-5d-v2` |
| Feature rows | 1,908,104 |
| Symbols | 1,080 |
| Source archives | 2,009 |
| 最新橫截面 | 2026-07-17 |
| Parquet bytes | 274,902,797 |
| Hash／read-back | PASS |

v2 新增並驗證 `decision_close_price`，供每日推論依真實收盤價重新計算交易成本；原有 17 個
模型特徵與 feature schema hash 保持不變。Provenance：

- Parquet SHA-256：`24c90589d51de6b0c06f084ca977c4bfb99993f91164d65b3bad33bce3c73aac`。
- Dataset snapshot：`c349a800d40dd73319c27fa39ca42107252230f1c14606919d7b6d90f52a919f`。
- Parquet schema SHA-256：`a53d4976fb779f89054786e2f960d355f4f4426a90eb4a46eadce251c1c22dad`。
- Model feature schema hash：`8e256243dbe0018a7a96a637b989e2338dcf06a8f2e9a9d42faf888c7f54cd53`。
- Source archive snapshot：`5438e7435de331b27ad2723eeee2544641e0e2520a56ebd949bbaac08b259407`。
- GitHub artifact：`8444804465`，digest `70143a1cb7f8ecb4905c67787830c991fded7ab89f913d5b1ce46dca3c92b19b`。

這份 artifact 已完成 schema、hash 與 read-back 驗證，但只能用於研究。主要 reason codes：

- `CURRENT_SECURITIES_SURVIVORSHIP_MAPPING`
- `HISTORICAL_IDENTITY_NOT_POINT_IN_TIME`
- `TRADING_SESSIONS_DERIVED_PER_SYMBOL`
- `RESEARCH_SCHEDULING_HINT`
- `LABELS_NOT_ASSEMBLED`
- `BENCHMARK_ARCHIVE_NOT_CONNECTED`

因此其狀態必須維持：

- `usage_scope=FEATURE_RESEARCH_ONLY`
- `point_in_time_status=UNVERIFIED`
- `label_status=LABELS_NOT_ASSEMBLED`
- `system_status=RESEARCH_ONLY`

### 上市 5 日歷史 OOS 研究結果

[GitHub Actions run `29690820942`](https://github.com/migao2006/tool/actions/runs/29690820942) 已於 2026-07-19 成功完成完整訓練與發布：

| 項目 | 已驗證結果 |
| --- | ---: |
| Prepared records | 1,196,162 |
| Purged walk-forward folds | 5 |
| OOS 評估日期／fold | 63 |
| Locked holdout rows（保留未執行） | 170,032 |
| 最新 OOS research predictions | 672 |
| Supabase `prediction_run_id` | 1 |
| `as_of_date` | 2025-05-02 |
| `decision_at` | 2025-05-02 17:00:00 +08:00 |
| Model version | `twse-price-research-h5-v1` |
| Training end date | 2024-06-18 |

排名平均結果：

| 指標 | Rank model | 20 日動能基準 |
| --- | ---: | ---: |
| NDCG@10 | 0.311856 | 0.330156 |
| NDCG@20 | 0.305487 | 0.317444 |
| NDCG@50 | 0.287796 | 0.293994 |
| Rank IC | -0.054552 | -0.023127 |
| ICIR | -0.358336 | -0.181064 |

Rank model 在上述 NDCG 與 Rank IC 指標均未優於 20 日動能基準，未通過正式排名驗收。方向模型的 fold 平均 log loss 為 1.037198、macro-F1 為 0.333102、ECE 為 0.030459；分位數模型的 P10 breach 為 12.1255%、P90 exceedance 為 9.9223%、P10～P90 coverage 為 77.9522%，校準前後 crossing rate 均為 0。

Production Supabase 已保存 672 筆研究預測；全部依保守政策發布為 `NO_TRADE`，沒有 hard fail。這些列可供 UI 顯示歷史 OOS 研究結果，但不得解讀為當日正式推薦。

Artifact／provenance：

- GitHub artifact：`8443586850`，digest `57eb16f26d50e2408020c51a4e1bef2f179e998819baf2f550bfc088c92e6b69`。
- Prepared Parquet SHA-256：`9ca63d003f082948013545f2755bb0d4dea145d94aaebbcd358cd93f40b480be`。
- Dataset snapshot：`22f6747e395b2a893ea297496558b05bd59e10751ec6a27d7d8ad3560aa88c22`。
- Feature schema：`8e256243dbe0018a7a96a637b989e2338dcf06a8f2e9a9d42faf888c7f54cd53`。
- Source hash：`18c6aac3780bea72be2ebdae2803fbe86b8a42436f60101d6412199fc11a6701`。
- Prediction snapshot：`f4fa5a50ebaa3f4820caadaf02c70525a7b6e93fd89d1fa89fbaac21cc7840d9`。
- Label：`twse-research-unadjusted-open-close-5d-v1`。
- Benchmark：`TWSE_TAIEX_PRICE_INDEX`，版本 `rwd.en.TAIEX.MI_5MINS_HIST.v1@snapshot:4c58a09fd1bbccc21416948eff8d31f77c31ba8568e2392493d0050f674c52c9`。
- Cost profile：`tw_stock_swing_v1:base_cost`。

### 最新上市橫截面研究推論

[GitHub Actions run `29695406502`](https://github.com/migao2006/tool/actions/runs/29695406502) 已使用最新驗證特徵橫截面、最後一個 walk-forward fold 的凍結模型 bundle，完成研究推論並以單一 transaction 原子發布至 Production Supabase：

| 項目 | 已驗證結果 |
| --- | ---: |
| Evaluation scope | `RETROSPECTIVE_RESEARCH_INFERENCE` |
| `as_of_date` | `2026-07-17` |
| `decision_at` | `2026-07-17T17:00:00+08:00` |
| 預測列數 | 1,068 |
| Supabase `prediction_run_id` | 2 |
| Model version | `twse-price-research-h5-v1` |
| Training end date | `2024-06-18` |
| 決策 | `CANDIDATE=0`、`WATCH=0`、`NO_TRADE=1,068` |
| 系統狀態 | `RESEARCH_ONLY` |
| 公開 API 資料品質 | 1,068 筆 `WARN`，0 筆 hard fail |
| Industry coverage | 0／1,068 |

完整性核對：股票與 global rank 均無重複、排名為 1～1,068 連續整數、三分類機率總和為 1、
毛／淨 P10≤P50≤P90，且 `latest_available_at <= decision_at`。Provenance：

- Feature artifact SHA-256：`24c90589d51de6b0c06f084ca977c4bfb99993f91164d65b3bad33bce3c73aac`。
- Model bundle SHA-256：`b588f93a9d43639b7329155aafff3f3d31c00dd6e78875618e426f8dd8f50156`。
- Prediction snapshot SHA-256：`0b1f116e64ccdfb3880acd352b95913e03fb8419c24196f6f4d6b2e1458b088a`。
- Snapshot artifact SHA-256：`ff9707336a27315bcf5d087b24b7c30aaa2d94b2807b59a80cd570fdd9532914`。
- GitHub artifact：`8444923880`，digest `044985dba1fdc7c94c60e9a4c52cf8225a0f2edc4e9ca7d8e201c7f823b00f9f`。

這是回溯研究推論，不是新的 OOS 驗證，也未執行正式 `decision_policy`。全部列保留
`RESEARCH_ONLY_NO_FORMAL_DECISION_POLICY` 並固定為 `NO_TRADE`；不得描述為正式候選股、
即時交易訊號或獲利保證。

## 三、Supplemental 回補現況

2026-07-20 Production manifest 與 task 統計：

| Dataset | Objects／rows | 任務狀態 |
| --- | ---: | --- |
| `institutional_flows` | 1,080／1,178,617 | 1,080 `SUCCEEDED` |
| `margin_short` | 1,008／1,173,917 | 1,008 `SUCCEEDED`、66 `PENDING`、6 `RETRY` |
| `adjusted_bars` | 0／0 | 1,080 `RETRY`；現有 FinMind free tier 不可用 |

法人資料已完成目前上市 campaign 的原始封存，但尚未接入本次 17 個價量特徵。融資券仍有
72 個任務未完成；`adjusted_bars` 仍沒有 Production object。不得把原始封存數量解讀為
point-in-time 或正式模型可用度。

## 四、Point-in-time 身分流程

- Production 已有 1,971 筆 `security_history` 與 1,080 筆 `security_listing_periods`。
- Current listing identity 證據仍固定為 `UNRESOLVED / RESEARCH_ONLY`，不是歷史 point-in-time 身分。
- 仍需歷史上市／下市期間、代號重用、ISIN／公司識別、產業 vintage 與來源實際發布時間證據。

## 五、目前仍屬硬性阻塞的項目

以下任何一項未解決時，都不得把模型狀態升級為 `PASS`：

1. 歷史 point-in-time security identity 尚未完成，現有特徵仍使用 current securities mapping，存在生存者偏誤與代號重用風險。
2. 交易日曆只有 2,077 筆研究觀測，尚未具備正式 session open／close、臨時休市及 decision cutoff 的可稽核歷史證據。
3. 公司行動、停復牌、處置／變更交易方法及可成交性歷史尚未完整驗證。
4. 仍有 843 筆下市觀測未解析，不能安全建立完整歷史股票池。
5. `adjusted_bars` 尚未取得；除權息、減資、分割與總報酬處理仍不足以支援正式 executable return。
6. 法人原始 archive 已完成目前上市 campaign，但尚未接入特徵；融資券尚有 72 個任務，`adjusted_bars` 仍為 0。
7. 研究資料已將股票與 TAIEX 價格指數統一為 `t+1 open → 第 5 個交易日 close`，但 TAIEX 仍是 price index、不是 total return，且整條路徑仍未完成正式 PIT／公司行動驗證。
8. Prepared artifact 與研究標籤雖已完成 hash／read-back 並實際執行 5-fold purged walk-forward，但仍是 `POINT_IN_TIME_UNVERIFIED`，且使用研究版未還原 open-close label，不是正式 LabelFactory 的 executable total-return label。
9. 研究資料已能支援這次 expanding train、calibration、test、purge 與保留 170,032 列 locked holdout；但歷史身分、公司行動與可交易性證據仍不足，不能將資料期間足夠解讀為正式 PIT coverage 足夠。
10. Purged walk-forward、溫度機率校準與分位區間校準已完成第一次真實執行；排名未優於 20 日動能基準，locked holdout 與完整 execution backtest 尚未執行。
11. 最新 1,068 筆推論沒有產業資料、正式 decision-policy gate、market model、locked holdout 或完整 execution backtest；只能顯示研究輸出。

## 六、目前可以與不可以做的事

目前可以：

- 持續以 append-only 方式累積及稽核 R2 原始歷史資料。
- 產生具有 provenance、schema、hash 與 read-back 的研究 artifact。
- 在 UI 預設顯示 2026-07-17 的 1,068 筆最新橫截面研究排序、方向機率及條件報酬分位數。
- 保留 2025-05-02 的 672 筆歷史 OOS 驗證快照，與最新回溯研究推論分開追溯。
- 在 Staging 驗證 migration、RPC contract 與 rollback。
- 在 `RESEARCH_ONLY` 狀態下檢查資料缺漏及準備正式標籤輸入。

目前不可以：

- 顯示正式候選股或宣稱模型已可交易。
- 將 Rank Score、方向機率或分位數包裝成保證報酬。
- 將已完成的研究 OOS 結果描述為正式樣本外績效、正式候選股或即時預測。
- 以 workflow success 代替資料列數、archive 數量及 point-in-time 驗證。

## 七、下一個安全執行順序

1. 完成研究快照的前端 gate 語意修正：沒有正式 gate 時只顯示「決策政策尚未執行」，不得誤稱 rank／direction／quantile model 不存在。
2. 補齊歷史 listing periods、代號重用、ISIN、產業 vintage 與下市解析，不得把 current snapshot 當歷史真相。
3. 完成剩餘融資券任務，建立可驗證的 adjusted price／公司行動／交易狀態來源，再把 supplemental 資料納入 fold 內特徵工程。
4. 補齊可驗證交易日曆、可成交性及 TAIEX total-return benchmark 契約。
5. 建立正式 horizon=5 executable total-return labels，重新執行 purged walk-forward 並改善未通過的排名模型。
6. 研究設計、特徵與門檻凍結且排名通過基準後，才執行一次 locked holdout 與完整成本回測；未達門檻時繼續維持 `RESEARCH_ONLY` 或標示 `FAIL`。
