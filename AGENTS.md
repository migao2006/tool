架構一定要分開，不可以把大量程式擠在同一個檔案裡。

# 專案開發指引

本專案是「台股 2～10 個交易日短波段預測系統」。所有開發必須以模組化、可驗證、可維護為優先，先理解既有架構再修改，不得為了快速完成而持續堆疊單一 HTML、CSS、JavaScript 或 Python 檔案。

## 溝通與進度回報

- 只在開始工作、完成重要階段、遇到阻塞或交付結果時提供簡短進度，不需每句話附上完成度與等待時間。
- 需要進度資訊時，以一行簡短說明目前狀況、約略完成度與必要等待時間即可，不得重複貼上相同狀態。
- 最終回覆只保留完成內容、必要限制與下一個必要動作，不重複列出冗長的過程摘要。
- 尚缺外部設定、使用者確認、資料、金鑰、網域或驗證結果時，不得宣告整體功能已完成。
- 使用者要求快速執行時，優先完成可交付結果，避免不影響結論的額外檢視與重複說明。

## 最高優先原則

1. 每個檔案只負責一項主要職責；頁面、元件、樣式、狀態、資料存取、模型、標籤、驗證與回測必須分層。
2. 檔案超過約 300 行、元件超過約 150 行，或同時處理兩種以上職責時，應先拆分再新增功能。
3. 不得把所有頁面塞進同一份 HTML，也不得把所有樣式或互動塞進單一 CSS、JavaScript 檔案。
4. 共用邏輯只能有一份；禁止複製貼上相同元件、格式化、篩選或計算程式。
5. 修改範圍要小且可回復，保留現有可正常運作的功能，不得無故重寫整個專案。

## 建議目錄責任

依實際技術棧調整名稱，但必須維持以下邏輯邊界：

```text
src/
  pages/          # 首頁、機會股、個股分析、自選股
  components/     # 導覽、卡片、分頁、篩選器、空狀態等共用 UI
  styles/         # tokens、base、components、各頁樣式
  core/           # router、state、設定與共用型別
  data/           # API client、資料來源、schema、時間對齊與完整性檢查
  features/       # ranking、direction、distribution、risk、market-regime
  models/         # 訓練、推論與模型版本管理
  validation/     # walk-forward、指標、校準與資料洩漏檢查
  backtest/       # 成本、滑價、成交限制與績效計算
tests/            # 對應各模組的測試
```

不得建立只有名稱不同、內容仍彼此耦合的假分層。頁面只能組合元件；元件不得直接寫模型或資料庫邏輯；資料層不得依賴 UI。

## UI 架構

- 固定維持 4 個頁面：今日總覽、5 日候選股、個股決策詳情、自選股。
- 底部導覽固定只有 3 個入口：總覽、5 日候選、自選。
- 個股決策詳情只能由股票項目進入，不占用底部導覽。
- 第一版只開放 5 個交易日 MVP；所有元件、API client 與型別介面必須接受 `horizon`，但固定傳入 `horizon=5`，不得建立可操作的 2／3／10 日切換。
- ETF 暫不出現在普通股票候選頁；上市與上櫃使用候選頁篩選，不得拆成額外頁面。
- 優先支援 iPhone 單手操作，觸控區至少 44×44 px，正確處理 safe area。
- 使用繁體中文、清楚的資訊層級與精簡文案，移除開發用文字和無必要裝飾。
- 沒有資料時只顯示「—」、「尚無資料」或「尚未更新」，禁止填入假股票、假機率或假績效。

## 登入與帳戶架構

- 登入方式只允許 Email＋密碼；UI 必須支援登入、建立帳號與登出，不提供忘記密碼或密碼重設流程。
- 登入介面使用獨立元件、流程控制、服務層與專用樣式，不得塞入既有 `app.js` 或主樣式檔。
- Supabase 負責帳戶、Email 確認、Session 與確認信；不得接入第三方寄信服務、密碼重設或另建驗證碼機制。
- 前端不得提供 Recovery 畫面，也不得呼叫 `resetPasswordForEmail`、密碼型 `updateUser` 或處理 `PASSWORD_RECOVERY` 事件。
- 前端只能使用 Supabase publishable key；`service_role` 與 secret key 禁止寫入前端、Git 或公開部署檔案。
- 建立帳號使用 Supabase 確認連結，並設定正確 Site URL、Redirect URL、寄送頻率限制與 CAPTCHA／防濫用措施。
- 自選股、持倉與其他個人資料必須在登入後才能存取；資料表必須啟用 RLS，政策需以 `auth.uid()` 驗證資料擁有者。
- 登入服務尚未連接或設定不完整時，UI 必須明確顯示不可用原因並停用提交，不得模擬登入成功或寄信成功。

## 資料與模型邊界

- 上市、上櫃與 ETF 必須分開使用合適基準，不可全部套用加權指數。
- 外資、投信與自營商資料必須分開；隔夜報酬與盤中報酬必須分開。
- 所有特徵只能使用預測當下已知資料，外部市場資料必須依台灣可取得時間對齊。
- 財報、月營收與事件資料使用實際公布時間，不得回填尚未公布的修正值。
- 訓練、驗證與測試必須依時間先後切割，使用 walk-forward／rolling／expanding window，禁止隨機打亂時間序列。
- 排名、三分類、分位數、風險、市場狀態與 Triple Barrier 必須是獨立模型或模組，不得用一個模型包辦全部任務。
- 不得以精確股價作為主要輸出，不得以訓練集結果冒充正式績效，不得保證獲利。

## 開發流程

1. 修改前先讀取相關頁面、元件、資料 schema、測試與 Git 差異。
2. 先定義輸入、輸出與模組邊界，再開始寫程式。
3. 新功能必須放入正確模組；若現有檔案已過大，先安全拆分。
4. 每次只完成一個可驗證的小階段，不同功能使用不同提交。
5. 驗證程度必須與修改風險相稱；小型文案或版面調整只做必要檢查，高風險的登入、資料、模型與部署修改才增加完整驗證。
6. 部署前確認正式檔案與 Git 版本一致，且沒有截斷標記、測試文字、假資料或未追蹤變更。

## 驗證尺度

- 不做與本次修改無關的全面審查，不重複執行已通過且未受影響的測試。
- 小型 UI、文字與位置調整通常只需差異檢查及一次針對性互動確認。
- 登入、安全性、資料庫、模型、交易回測與正式部署仍須做足以避免明顯風險的驗證。
- 一次針對性檢查已能證明結果時，不再額外開啟多個瀏覽器、重複截圖或反覆委派相同審查。

## 完成條件

- 模組責任清楚，沒有新增巨型檔案或循環依賴。
- UI、資料、模型、驗證與回測互不混寫。
- 所有資料都有日期、來源與模型版本可追溯。
- 缺漏資料會明確顯示，不會被預設值掩蓋。
- 不存在明顯 look-ahead bias、survivorship bias 或時間對齊錯誤。
- 測試與部署驗證通過後，才可宣告完成。

## 十七、前端頁面與顯示規則

本次前端以「5 個交易日短波段選股 MVP」為唯一正式功能。

不得為尚未完成的 2、3、10 日模型建立可操作頁面，也不得用假資料填補。所有前端元件、API client 及型別介面必須接受 `horizon` 參數，但第一版固定傳入 `horizon=5`。

未來其他模型正式完成後，才開放 2／3／5／10 日切換。

前端保留四個使用者頁面：

1. 今日總覽
2. 5 日候選股
3. 個股決策詳情
4. 自選股

底部導覽只顯示：

- 總覽
- 5 日候選
- 自選

個股決策詳情由點擊股票進入，不放入底部導覽。

不得新增管理員頁面。

### 一、今日總覽

顯示：

- `as_of_date`
- `decision_at`
- `horizon=5`
- `market_direction` 的 `UP`／`NEUTRAL`／`DOWN` 機率
- `market_regime`
- `forecast_market_volatility`
- `market_exposure_cap`
- 今日 `CANDIDATE`／`WATCH`／`NO_TRADE` 數量
- `data_quality` hard fail 數量
- Rank Score 最高且通過決策門檻的前 3～5 檔股票
- `model_version`
- `training_end_date`
- `cost_profile_version`
- 系統驗證狀態：`PASS`／`RESEARCH_ONLY`／`FAIL`

首頁提供「查看模型驗證報告」按鈕，以全螢幕彈窗或抽屜顯示：

- Walk-forward 結果
- locked holdout 結果
- `NDCG@10`／`20`／`50`
- Rank IC 與 ICIR
- 機率校準結果
- quantile coverage
- 成本敏感度
- 與基準模型比較
- 已知限制

不得為模型驗證另建底部導覽頁面。

### 二、5 日候選股

正式候選股排序只能使用 `rank_model` 輸出的 Rank Score 或 `global_rank`。

不得在前端將 Rank Score、`p_up`、`q50`、波動度或市場狀態重新加權成 final score。

每檔股票至少顯示：

- `symbol`
- 股票名稱
- `market`
- `industry`
- Rank Score
- `global_rank`
- `industry_rank`
- `calibrated_p_up`
- `calibrated_p_neutral`
- `calibrated_p_down`
- `net_q10`
- `net_q50`
- `net_q90`
- `estimated_round_trip_cost`
- `data_quality_status`
- `decision`
- 主要 `reason_codes`

Rank Score 必須明確標示為「當日橫斷面排名百分位」，不得標示成上漲機率、預期報酬或模型信心。

P10／P50／P90 必須標示為條件報酬分位數，不得稱為最低、平均、最高報酬或獲利保證。

若沒有獨立 `expected_return_model` 或經 OOS 校準的報酬映射，前端不得顯示「預期報酬」或「期望值 EV」。

候選頁可以篩選：

- 上市／上櫃
- 產業
- `CANDIDATE`／`WATCH`／`NO_TRADE`
- 資料品質
- 流動性分組
- Rank Score
- `calibrated_p_up`
- cost profile

ETF 暫不出現在普通股票候選頁。

`data_quality` hard fail 股票不得出現在正式推薦清單。頁面可以另外顯示排除數量，點擊後以抽屜顯示股票及 `reason_codes`。

### 三、個股決策詳情

頁面頂部顯示：

- `decision`：`CANDIDATE`／`WATCH`／`NO_TRADE`
- 主要 `reason_codes`
- `as_of_date`
- `decision_at`
- `horizon`

依 `decision_policy` 順序顯示：

1. `data_quality` hard gate
2. tradability gate
3. liquidity 與 capacity gate
4. `market_exposure_cap`
5. calibrated direction probabilities
6. net quantile thresholds
7. rank eligibility
8. position and capacity limits

每一層必須顯示：

- 通過或未通過
- 實際值
- 使用門檻
- `reason_code`

個股頁包含下列區塊：

排名：

- Rank Score
- `global_rank`
- `global_rank_percentile`
- `industry_rank`
- `industry_rank_percentile`

方向機率：

- `calibrated_p_up`
- `calibrated_p_neutral`
- `calibrated_p_down`
- `calibration_version`

報酬分位數：

- `gross_q10`
- `gross_q50`
- `gross_q90`
- `net_q10`
- `net_q50`
- `net_q90`
- `interval_width`
- `calibration_status`
- `estimated_round_trip_cost`

風險及容量：

- `forecast_volatility`
- `downside_risk`
- `ADV20`
- 最大可下單金額
- 單股上限
- 單產業上限
- `market_exposure_cap`
- `cost_profile`

稽核資訊：

- `model_version`
- `feature_schema_hash`
- `cost_profile_version`
- `training_end_date`
- `source_dates`
- `latest_available_at`
- `data_quality_status`
- `reason_codes`

技術稽核資訊可以預設折疊，但不得刪除。

不得顯示精確未來股價、虛構的 AI 信心分數、final score 或未經 OOS 驗證的預期報酬。

### 四、自選股

自選股頁只負責追蹤，不重新計算排名。

顯示：

- `symbol`
- Rank Score
- `global_rank`
- `decision`
- `calibrated_p_up`／`neutral`／`down`
- `net_q10`／`q50`／`q90`
- `data_quality_status`
- `reason_codes`
- 與前一交易日相比的排名及決策變化

可以篩選：

- 全部
- `CANDIDATE`
- `WATCH`
- `NO_TRADE`

本次不新增持倉損益、自動下單或複雜投資組合頁面。

### 五、研究設定

不得新增獨立設定頁。

在首頁右上角提供研究設定抽屜，允許設定：

- `commission_discount`
- `minimum_fee`
- `estimated_order_notional_ntd`
- `max_adv_participation`
- `cost_profile`
- 單股部位上限
- 單產業上限
- 最大市場總曝險

模型超參數、校準參數、標籤門檻及 locked holdout 不得讓一般使用者直接修改。

### 六、前端狀態

所有頁面必須完整處理：

- loading
- empty
- stale data
- data quality hard fail
- API error
- `RESEARCH_ONLY`
- `FAIL`
- 尚未完成模型
- 無正式候選股

資料不足或模型未通過驗收時，必須顯示 `RESEARCH_ONLY` 或 `FAIL`，不得以舊資料、隨機資料或 placeholder 冒充正式預測。
