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
