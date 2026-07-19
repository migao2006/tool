# 產品與 UI 規範

> 2026-07-19 現況：頁面與資料契約已建立，但 `predictionApiBaseUrl` 尚未接上正式模型快照。正式模型欄位顯示 `—`，系統維持 `RESEARCH_ONLY`；Supabase 資料累積摘要不等於可推薦模型。完整狀態見 [`current-status.md`](current-status.md)。

## 一、固定使用者頁面

固定維持四個使用者頁面：

1. 今日總覽
2. 5 日候選股
3. 個股決策詳情
4. 自選股

底部導覽只顯示：

- 總覽
- 5 日候選
- 自選

個股詳情只能由股票項目進入，不占底部導覽。

## 二、UI 原則

- 使用繁體中文及台灣常用詞彙。
- 優先支援 iPhone 單手操作。
- 觸控區至少 44×44 px。
- 正確處理 safe area。
- 重要資訊不得只使用顏色表示。
- 技術稽核資料可折疊，但不得刪除。
- 2／3／10 日不得顯示為可操作切換；未支援 horizon 必須清楚拒絕。

所有頁面必須處理：

- `loading`
- `empty`
- `stale`
- `API_ERROR`
- `HARD_FAIL`
- `RESEARCH_ONLY`
- `FAIL`

沒有資料時只顯示：

- `—`
- 尚無資料
- 尚未更新

不得使用假股票、假機率、假報酬或 placeholder 數字。

## 三、顯示語意

排名模型是唯一排序來源。前端不得重新計算 `final_score`。

Rank Score 只能表示當日橫斷面排名百分位，不是：

- 上漲機率
- 預期報酬
- 模型信心
- 勝率

P10／P50／P90 是條件報酬分位數，不是最低、平均、最高報酬或保證區間。

沒有獨立 expected return 模型及 OOS 校準時，不得顯示「預期報酬」或「EV」。

## 四、狀態契約

系統狀態：

- `PASS`
- `RESEARCH_ONLY`
- `FAIL`

個股決策：

- `CANDIDATE`
- `WATCH`
- `NO_TRADE`

候選資格：

- `ELIGIBLE`
- `EXCLUDED`

資料品質：

- `PASS`
- `WARN`
- `HARD_FAIL`

強制關係：

- `HARD_FAIL` 必須進入 `excluded` 集合並標示 `EXCLUDED`，不得混入正式候選排序。
- 系統為 `FAIL` 時不得產生 `CANDIDATE`。
- `RESEARCH_ONLY` 必須清楚標示為研究用途。
- `WATCH` 不等於正式推薦。
- `NO_TRADE` 不等於資料錯誤。

## 五、頁面內容

### 今日總覽

顯示：

- `as_of_date` 與 `decision_at`
- `horizon=5`
- `market_direction` 的 UP／NEUTRAL／DOWN 機率
- `market_regime`
- `forecast_market_volatility`
- `market_exposure_cap`
- `CANDIDATE`／`WATCH`／`NO_TRADE` 與 hard fail 數量
- 前 3～5 檔候選
- `model_version`、`training_end_date`、`cost_profile_version`
- `PASS`／`RESEARCH_ONLY`／`FAIL`
- Supabase 原始資料累積摘要；必須與模型就緒度分開顯示

首頁右上角保留研究設定抽屜，只允許修改交易成本、容量與部位上限等公開研究設定。模型超參數、標籤門檻、校準器及 locked holdout 不得由一般使用者修改。

模型驗證報告以全螢幕抽屜顯示 Walk-forward、locked holdout、NDCG、Rank IC／ICIR、校準、quantile coverage、成本敏感度、基準比較與已知限制，不新增底部入口。尚無真實結果時只能顯示尚未執行。

### 5 日候選股

只依 Rank Score 或 `global_rank` 排序。

至少顯示：

- `symbol`、股票名稱、`market`、`industry`
- Rank Score、`global_rank`、`industry_rank`
- `calibrated_p_up`／`calibrated_p_neutral`／`calibrated_p_down`
- `net_q10`／`net_q50`／`net_q90`
- `estimated_round_trip_cost`
- `data_quality_status`
- `decision`
- 主要 `reason_codes`

Hard fail 股票只能出現在獨立排除清單。

可篩選上市／上櫃、產業、決策、資料品質、流動性、Rank Score、校準後上漲機率與 cost profile。ETF 暫不出現在普通股票候選頁。前端不得把 Rank Score、機率、分位數、波動或市場狀態重新加權。

### 個股決策詳情

依序顯示：

1. Data quality
2. Tradability
3. Liquidity 與 capacity
4. Market exposure
5. Calibrated probability
6. Net quantile
7. Rank eligibility
8. Position limits

每個 gate 必須顯示：

- 通過狀態
- 實際值
- 門檻
- `reason_code`
- 來源日期

個股頁另顯示排名、校準後方向機率、gross／net 分位數、區間寬度、成本、波動、下行風險、ADV20、容量限制及完整稽核資訊。稽核至少保留模型版本、feature schema hash、資料快照、label version、成本與校準版本、training end date、Git commit、source dates 與 latest available time。

目前 gate adapter 尚未完整保留 `source_date`，追溯畫面也尚未完整接入 dataset snapshot、label version 與 Git commit；這些是正式 `PASS` 前必須補齊的契約缺口，不得從 UI 自行推算。

### 自選股

只追蹤後端結果，不重新計算排名。

顯示排名、決策、三分類機率、分位數、資料品質、原因及前一交易日變化。

登入／帳戶入口放在自選股標題下方：未登入顯示 Email＋密碼登入與建立帳號；已登入顯示帳戶狀態、登出及自選內容。自選股只追蹤後端快照，不新增持倉損益或自行重算排名。

當系統為 `RESEARCH_ONLY` 或 `FAIL`，候選與自選股不得顯示虛構正式數值；只顯示缺漏原因、資料日期、累積狀態及 `—`。
