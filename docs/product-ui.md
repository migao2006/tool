# 產品與 UI 規範

## 一、正式頁面

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
- `EXCLUDED`

資料品質：

- `PASS`
- `WARN`
- `HARD_FAIL`

強制關係：

- `HARD_FAIL` 必須對應 `EXCLUDED`。
- 系統為 `FAIL` 時不得產生 `CANDIDATE`。
- `RESEARCH_ONLY` 必須清楚標示為研究用途。
- `WATCH` 不等於正式推薦。
- `NO_TRADE` 不等於資料錯誤。

## 五、頁面內容

### 今日總覽

顯示：

- 資料日期與決策時間
- Horizon
- 市場方向機率
- 市場狀態
- 預測波動
- 曝險上限
- 決策數量與 hard fail 數量
- 前 3～5 檔候選
- 模型及成本版本
- 系統狀態

### 5 日候選股

只依 Rank Score 或 `global_rank` 排序。

至少顯示：

- 股票識別、市場、產業
- 全市場及產業排名
- 三分類校準機率
- `net_q10/q50/q90`
- 交易成本
- 資料品質
- 決策
- 主要 `reason_codes`

Hard fail 股票只能出現在獨立排除清單。

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

### 自選股

只追蹤後端結果，不重新計算排名。

顯示排名、決策、三分類機率、分位數、資料品質、原因及前一交易日變化。
