# 資料與模型規範

> 2026-07-19 現況仍為 `RESEARCH_ONLY`。本規範同時列出正式目標與目前缺口；不得把研究管線已實作解讀為正式資料集已產生。詳見 [`current-status.md`](current-status.md)。

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
- `security_state_snapshots` 保存 private R2 狀態 object 的 manifest；未完整觀察停牌、處置、變更交易方法、全額交割及分盤等欄位時不得 VERIFIED。
- `historical_corporate_action_observations` 保存事件生命週期；`company_action_coverage_observations` 另存完整含無事件證明。查無事件列不等於完整 coverage。
- Canonical 日線必須保留 R2 object、archive SHA-256、來源 revision／payload hash、原始 `first_observed_at`／`available_at`、身分 revision 與 publication rule version。
- 第一版 `canonical_dataset_objects` 只允許 `CANONICAL_RESEARCH_ONLY` 且強制 `model_eligible_row_count=0`；正式資料必須由後續獨立且經驗證的 builder 契約產生。
- 原始資料的取得時間不得回改成歷史日期。若資料在決策時間後才首次取得，該列只能維持 `RESEARCH_ONLY`。
- 就緒度分成兩層：`canonicalization_ready` 只檢查建構前的 PIT 證據交集，不得要求先存在 canonical 成品；`dataset_build_ready` 另檢查建構後是否真的產生 model-eligible canonical rows。這可避免「必須先有成品才允許建構成品」的循環。
- 即使兩層資料閘門全部通過，模型仍須完成 walk-forward、locked holdout 與成本後驗收，才可能標記為 `PASS`。
- 掛牌身分必須使用穩定的 `listing_period_id`，每筆來源證據另以 `listing_evidence_id` 追蹤。VERIFIED 證據必須同時核對市場、資產類型、股票代號及 ISIN。
- `OFFICIAL_PUBLICATION_AT` 可使用實際發布時間；`VERSIONED_SNAPSHOT` 只能從 `first_observed_at` 起使用；`FIRST_OBSERVED_AT_RETRIEVAL` 一律維持研究用途。
- Archive integrity 與 dataset readiness 必須使用同一 manifest snapshot hash；該 hash 必須涵蓋來源、期間、使用範圍、狀態、reason codes 及所有會改變資料語意的欄位。
- 就緒判斷必須驗證 archive symbol、掛牌身分、交易日曆、交易狀態、公司行動與 canonical row 的實際交集，不得只比較彼此無關的總筆數。交集 coverage 尚未持久化前狀態固定為 BLOCKED。

目前上市研究 feature schema 固定為 17 個價量特徵，schema hash 為 `8e256243dbe0018a7a96a637b989e2338dcf06a8f2e9a9d42faf888c7f54cd53`。特徵包含 1／2／3／5／10／20／60 日報酬、隔夜跳空、日內報酬、ATR14、RV20、下行波動 20、最大回撤 20、ADV20、週轉率均值 20、量能異常 20 與 Amihud20。

這個 feature／research runner 仍有下列限制：

- 身分映射使用目前 security master，存在生存者偏誤，不能形成正式歷史股票池。
- 研究組裝器目前從個股日線推導可用交易日，尚未綁定完整、經驗證的交易所日曆。
- 正式 `label_factory` 尚未接入；研究列保留 `FORMAL_LABEL_FACTORY_NOT_USED`。
- 個股路徑是 t+1 open 到第 5 個持有交易日 close，現有 TAIEX close-only 基準是 t close 到 exit close，路徑尚未對齊。
- 部分 dataset／benchmark provenance 仍由 caller 傳入，尚未從 Parquet metadata、R2 hash 與 manifest snapshot 強制推導。
- 正式 backtest、daily inference、真實 walk-forward 與 locked holdout 均未執行。

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
