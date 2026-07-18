# 資料與模型規範

## 一、時間正確性

所有特徵必須滿足：

```text
available_at <= decision_at
```

財報、月營收、事件及公司行動必須使用實際公布及可取得時間。

不得使用：

- 所屬期間代替公布時間。
- 修正後資料回填歷史。
- 尚未發生的同日美股收盤。
- 事後才知道的交易狀態。

系統內部時間使用 UTC；台股交易日及畫面顯示使用 `Asia/Taipei`。

禁止使用無時區 datetime 進行資料對齊。

## 二、資料範圍

- 上市、上櫃及 ETF 分開處理。
- ETF 不與普通股票混合訓練。
- 隔夜及盤中報酬分開。
- 外資、投信及自營商資料分開。
- 歷史股票池必須包含下市、停牌及失敗公司。
- 關鍵行情、公司行動或交易狀態缺漏時必須 hard fail。

## 三、模型責任

- 排名模型：唯一排序來源。
- 方向模型：提供校準後三分類機率。
- 分位數模型：提供條件報酬分布。
- 市場模型：控制總曝險。
- 波動模型：控制風險及部位。
- Triple Barrier：研究交易路徑及事件標籤。
- `decision_policy`：負責 gate、Top-K、容量及部位限制。

`decision_policy` 不得建立另一套加權排名。

## 三之一、歷史封存契約

- 新增的多年日線原始資料以 ZSTD 壓縮 Parquet 保存於 private Cloudflare R2，object key 與內容雜湊必須可重現及稽核。
- Supabase `market_data.historical_archive_objects` 只保存 object 位置、來源期間、列數、雜湊、資料品質與版本 metadata，不保存同一份 R2 原始列副本。
- `historical_daily_bar_landing` 只保留尚未封存或受控稽核所需的暫存列，也可以保持空白；首頁統計以 R2 manifest 的最新 logical slice 為準，且不得把 retry 或 revision 重複計數。
- R2 object 驗證完成後才可寫入 manifest；任一 size、SHA-256 或 metadata 驗證失敗時必須 fail closed 並讓任務重試。
- `UNVERIFIED / RAW_LANDING_ONLY / RESEARCH_ONLY` 只代表已保存原始資料，不代表可訓練、可回測或已消除生存者偏誤。

## 三之二、歷史資料升級與就緒閘門

- R2 原始列不得直接進入特徵、標籤、訓練或回測；必須先通過 manifest／Parquet 完整性、歷史掛牌身分、交易日曆、公司行動涵蓋與 `available_at` 稽核。
- 歷史關聯使用 `security_id + listing_period_id`；`scheduled_market` 只是排程提示，不能單獨證明股票所屬市場或身分。
- `security_listing_periods` 與 `trading_calendar_observations` 是 append-only 證據；後續矛盾只能追加 `CONFLICT`，不得覆寫或回填既有證據。
- Canonical 日線必須保留 R2 object、archive SHA-256、來源 revision／payload hash、原始 `first_observed_at`／`available_at`、身分 revision 與 publication rule version。
- 原始資料的取得時間不得回改成歷史日期。若資料在決策時間後才首次取得，該列只能維持 `RESEARCH_ONLY`。
- 每日就緒度稽核只回答資料是否可交給 dataset builder；即使資料閘門全部通過，模型仍須完成 walk-forward、locked holdout 與成本後驗收，才可能標記為 `PASS`。

## 四、決策順序

1. Data quality
2. Tradability
3. Liquidity
4. Capacity
5. Market exposure
6. Calibrated probability
7. Net quantile
8. Rank eligibility
9. Top-K
10. Position limits

每個 gate 必須回傳：

- `passed`
- `actual_value`
- `threshold`
- `reason_code`
- `source_date`

## 五、模型追蹤

正式 artifact 至少記錄：

- 模型名稱及版本
- Horizon
- 訓練起訖日
- Feature schema hash
- Dataset snapshot
- Label version
- Cost profile version
- Calibration version
- Git commit
- Random seed
- Library versions

缺少必要追蹤資料時，不得標記為 `PASS`。

## 六、驗證與回測

必須使用 purged walk-forward、rolling 或 expanding window。

禁止：

- Random split
- Random K-fold
- 將同一 decision date 拆到不同 fold
- 使用 test 或 holdout 選特徵、門檻或超參數

回測必須考慮：

- t+1 可成交開盤
- 完整費稅
- 最低手續費
- Spread、slippage、impact
- 漲跌停及無法成交
- 停牌及公司行動
- 容量限制
- Staggered cohorts

## 歷史資料正式升級閘門

- R2 Parquet 仍是不可變的原始封存層；完整性通過不等於可供模型訓練。
- 掛牌身分必須使用穩定的 `listing_period_id`，每筆來源證據另以
  `listing_evidence_id` 追蹤。VERIFIED 證據必須同時核對市場、資產類型、
  股票代號及 ISIN。
- `OFFICIAL_PUBLICATION_AT` 可使用實際發布時間；`VERSIONED_SNAPSHOT` 只能
  從 `first_observed_at` 起使用；`FIRST_OBSERVED_AT_RETRIEVAL` 一律維持研究用途。
- 特徵、security master、交易日曆與公司行動證據均須保存
  `available_at`、`first_observed_at`、可用時間依據、修訂 hash 與使用範圍。
- Archive integrity 與 dataset readiness 必須使用完全相同的 manifest
  snapshot hash；LIMITED_SAMPLE 或稽核後發生變動時一律 FAIL。
- 就緒判斷必須驗證 archive symbol、掛牌身分、交易日曆、交易狀態、公司行動
  與 canonical row 的實際交集，不得只比較彼此無關的總筆數。
- 在交集覆蓋 persistence 尚未完成前，就緒狀態固定為 BLOCKED，系統最多只能
  顯示 `RESEARCH_ONLY`。
