架構一定要分開，不可以把大量程式擠在同一個檔案裡。

# 專案開發指引

本專案是「台股 2～10 個交易日短波段預測系統」。目前唯一正式功能是「5 個交易日短波段選股 MVP」。所有修改必須以模組化、時間正確、可驗證、可追溯及可維護為前提，先理解既有架構再做最小必要修改。

## 一、規則優先順序

發生衝突時，依下列順序判斷：

1. 資料安全、時間正確性、不可捏造及不可洩漏機密。
2. 使用者在當次任務中的明確要求。
3. 本檔案的發布限制、產品契約與架構邊界。
4. 保留既有可正常運作功能並採最小修改。
5. 開發速度與便利性。

不得為了快速完成而犧牲資料正確性、將功能堆進單一檔案、以假資料冒充正式結果，或跳過必要的樣本外驗證。

## 二、溝通與執行方式

- 只在開始工作、完成重要階段、遇到阻塞或交付時提供簡短進度。
- 不需每句話附完成度或等待時間；需要時以一行說明目前狀況、約略完成度及必要等待時間。
- 使用者要求快速執行時，優先完成可交付結果，省略不影響結論的重複檢查與冗長說明。
- 缺少資料、權限、設定、金鑰、網域或驗證結果時，必須明確回報，不得宣告整體完成。
- 最終回覆只列出完成內容、實際驗證、已知限制及唯一必要的下一步。

## 三、版本控制與發布限制

- 本專案只允許透過 Git 將程式碼提交並推送至 GitHub 儲存庫。
- 未經使用者在當次任務中再次明確授權，禁止直接建立、提升、回復或刪除任何 Vercel 部署，也禁止使用 Vercel CLI、API、MCP 或其他主機部署工具。
- GitHub 推送不代表同時授權其他平台自動或手動部署。若 GitHub 整合會觸發外部部署，必須先說明並取得明確同意。
- 發布前只提交本次任務相關檔案，確認 Git 差異、測試結果及工作樹狀態，不得夾帶其他修改。
- GitHub 推送若受登入、憑證、權限或網路問題阻擋，應回報阻塞，不得改用其他部署平台繞過。
- 禁止提交 secret、service role key、密碼、存取權杖或其他非公開憑證。

## 四、模組與目錄邊界

### 4.1 檔案責任

1. 每個檔案只負責一項主要職責；頁面、元件、樣式、狀態、資料存取、模型、標籤、驗證與回測必須分層。
2. 檔案超過約 300 行、元件超過約 150 行，或同時處理兩種以上職責時，應先拆分再新增功能。
3. 不得把所有頁面塞進同一份 HTML，也不得把所有樣式或互動塞進單一 CSS、JavaScript 或 Python 檔案。
4. 共用邏輯只能有一份；禁止複製貼上相同元件、格式化、篩選、標籤或計算程式。
5. 頁面只能組合元件；元件不得直接寫模型或資料庫邏輯；資料層不得依賴 UI。
6. 修改範圍必須小且可回復，不得無故重寫整個專案。

### 4.2 目錄責任

依實際技術棧調整名稱，但必須維持下列邏輯邊界：

```text
src/
  pages/          # 今日總覽、5 日候選股、個股決策詳情、自選股
  components/     # 導覽、卡片、分頁、篩選器、抽屜、空狀態
  styles/         # tokens、base、components、各頁樣式
  core/           # router、state、設定與共用型別
  data/           # API client、schema、時間對齊與完整性檢查
  features/       # ranking、direction、distribution、risk、market-regime
  labels/         # 共用標籤與交易路徑
  models/         # 訓練、推論與模型版本管理
  calibration/    # 機率與分位數校準
  decision/       # 透明決策政策
  validation/     # walk-forward、指標與資料洩漏檢查
  backtest/       # 成本、滑價、成交限制與績效計算
tests/            # 對應各模組的測試
```

不得建立只有名稱不同、內容仍彼此耦合的假分層。

## 五、前端產品契約

### 5.1 正式功能範圍

- 第一版只開放 `horizon=5` 的正式功能。
- 所有前端元件、API client 與型別介面必須接受 `horizon`，但第一版固定傳入 `5`。
- 2、3、10 日模型未完成前，不得建立可操作切換、假資料或暗示功能已可使用。
- 固定只有四個使用者頁面：今日總覽、5 日候選股、個股決策詳情、自選股。
- 底部導覽固定只有三個入口：總覽、5 日候選、自選。
- 個股決策詳情只能由股票項目進入，不占底部導覽。
- 不得新增管理員頁面或獨立模型績效頁。
- ETF 暫不出現在普通股票候選頁；上市與上櫃以候選頁篩選，不拆成額外頁面。

### 5.2 全域顯示規則

- 優先支援 iPhone 單手操作，觸控區至少 44×44 px，並正確處理 safe area。
- 使用繁體中文、清楚資訊層級與精簡文案，移除開發用文字及無必要裝飾。
- 沒有資料時只顯示「—」、「尚無資料」或「尚未更新」，禁止填入假股票、假機率或假績效。
- 所有頁面必須處理 loading、empty、stale data、API error、data quality hard fail、無正式候選股、模型未完成、`RESEARCH_ONLY` 及 `FAIL`。
- 資料不足或模型未通過驗收時，只能顯示 `RESEARCH_ONLY` 或 `FAIL`，不得用舊資料、隨機資料或 placeholder 冒充正式預測。
- Rank Score 必須標示為「當日橫斷面排名百分位」，不得稱為上漲機率、預期報酬或模型信心。
- P10／P50／P90 必須標示為條件報酬分位數，不得稱為最低、平均、最高報酬或獲利保證。
- 沒有獨立 expected return 模型或經 OOS 校準的報酬映射時，不得顯示「預期報酬」或「期望值 EV」。
- 不得顯示精確未來股價、虛構 AI 信心分數、任意加權 final score 或未經 OOS 驗證的報酬。

### 5.3 今日總覽

首頁只顯示決策摘要，不放大型完整表格，至少包含：

- `as_of_date`、`decision_at`、`horizon=5`
- `market_direction` 的 `UP`／`NEUTRAL`／`DOWN` 機率
- `market_regime`、`forecast_market_volatility`、`market_exposure_cap`
- 今日 `CANDIDATE`／`WATCH`／`NO_TRADE` 數量
- data quality hard fail 數量
- Rank Score 最高且通過決策門檻的前 3～5 檔股票
- `model_version`、`training_end_date`、`cost_profile_version`
- 系統驗證狀態：`PASS`／`RESEARCH_ONLY`／`FAIL`

首頁提供「查看模型驗證報告」按鈕，以全螢幕彈窗或抽屜顯示 Walk-forward、locked holdout、`NDCG@10/20/50`、Rank IC、ICIR、機率校準、quantile coverage、成本敏感度、基準比較及已知限制。

首頁右上角可提供研究設定抽屜，僅允許設定：

- `commission_discount`
- `minimum_fee`
- `estimated_order_notional_ntd`
- `max_adv_participation`
- `cost_profile`
- 單股部位上限、單產業上限、最大市場總曝險

一般使用者不得直接修改模型超參數、校準參數、標籤門檻或 locked holdout。

### 5.4 5 日候選股

- 正式排序只能使用 rank model 輸出的 Rank Score 或 `global_rank`。
- 不得在前端將 Rank Score、`p_up`、`q50`、波動度或市場狀態重新加權成 final score。
- data quality hard fail 股票不得出現在正式推薦清單；可另顯示排除數量及 reason codes 抽屜。

每檔股票至少顯示：

- `symbol`、股票名稱、`market`、`industry`
- Rank Score、`global_rank`、`industry_rank`
- `calibrated_p_up`、`calibrated_p_neutral`、`calibrated_p_down`
- `net_q10`、`net_q50`、`net_q90`
- `estimated_round_trip_cost`
- `data_quality_status`、`decision`、主要 `reason_codes`

篩選器可以包含上市／上櫃、產業、`CANDIDATE`／`WATCH`／`NO_TRADE`、資料品質、流動性分組、Rank Score、`calibrated_p_up` 及 cost profile。

### 5.5 個股決策詳情

頁首顯示 `decision`、主要 `reason_codes`、`as_of_date`、`decision_at` 及 `horizon`。

依 decision policy 順序顯示下列 gate，且每一層都要呈現通過／未通過、實際值、門檻與 `reason_code`：

1. data quality hard gate
2. tradability gate
3. liquidity 與 capacity gate
4. `market_exposure_cap`
5. calibrated direction probabilities
6. net quantile thresholds
7. rank eligibility
8. position and capacity limits

個股頁區塊至少包含：

- 排名：Rank Score、`global_rank`、`global_rank_percentile`、`industry_rank`、`industry_rank_percentile`
- 方向：`calibrated_p_up`、`calibrated_p_neutral`、`calibrated_p_down`、`calibration_version`
- 分位數：`gross_q10/q50/q90`、`net_q10/q50/q90`、`interval_width`、`calibration_status`、`estimated_round_trip_cost`
- 風險容量：`forecast_volatility`、`downside_risk`、`ADV20`、最大可下單金額、單股上限、單產業上限、`market_exposure_cap`、`cost_profile`
- 稽核資訊：`model_version`、`feature_schema_hash`、`cost_profile_version`、`training_end_date`、`source_dates`、`latest_available_at`、`data_quality_status`、`reason_codes`

技術稽核資訊可以預設折疊，但不得刪除。

### 5.6 自選股

- 自選股只負責追蹤，不重新計算排名。
- 顯示 `symbol`、Rank Score、`global_rank`、`decision`、校準後三分類機率、`net_q10/q50/q90`、`data_quality_status`、`reason_codes`，以及與前一交易日相比的排名及決策變化。
- 可以篩選全部、`CANDIDATE`、`WATCH`、`NO_TRADE`。
- 本階段不新增持倉損益、自動下單或複雜投資組合功能。

## 六、登入與帳戶契約

- 登入方式只允許 Email＋密碼；UI 支援登入、建立帳號與登出，不提供忘記密碼或密碼重設流程。
- Supabase 負責帳戶、Email 確認、Session 與確認信；不得接入第三方寄信服務或另建驗證碼機制。
- 登入介面使用獨立元件、controller、service 與樣式，不得塞入主 `app.js` 或主樣式檔。
- 前端不得呼叫 `resetPasswordForEmail`、密碼型 `updateUser`，不得處理 `PASSWORD_RECOVERY` 事件或提供 Recovery 畫面。
- 前端只能使用 Supabase publishable key；`service_role`、secret key 及管理權限不得出現在前端、Git 或公開檔案。
- 建立帳號使用 Supabase 確認連結，並設定正確 Site URL、Redirect URL、寄送頻率限制及防濫用措施。
- 個人資料表必須啟用 RLS，政策以 `auth.uid()` 驗證資料擁有者。
- 登入服務未連接或設定不完整時，必須顯示真正原因並停用提交，不得模擬成功。

## 七、資料、模型與決策邊界

### 7.1 Point-in-time 與資料品質

- 所有特徵只能使用 `decision_at` 當下已知資料，必須滿足 `available_at <= decision_at`。
- 財報、月營收、事件及公司行動使用實際公布時間，不得用資料所屬期間或修正後資料回填歷史。
- 國際市場資料必須依台灣可取得時間對齊；同日尚未收盤的美股資料不得用於台股訊號。
- 隔夜報酬與盤中報酬必須分開；外資、投信與自營商也必須分開。
- 上市、上櫃與 ETF 使用合適基準並分開評估；ETF 不與普通股混合訓練。
- 歷史股票池應包含下市、停止交易及失敗公司，避免生存者偏誤。
- 關鍵行情、公司行動或交易狀態缺漏時必須 hard fail，不得以預設值掩蓋。

### 7.2 模型責任

- 排名、三分類、分位數、波動風險、市場狀態與 Triple Barrier 必須是獨立模型或模組，不得由單一模型包辦。
- 排名模型是唯一個股排序來源；方向機率、分位數、波動度與市場狀態不得再次任意加權進排名。
- 市場模型只控制總曝險，不改變個股名次；波動模型只用於風險與部位大小。
- `decision_policy` 只負責 gate、Top-K 與部位限制，不得建立另一套 final score。
- 不得以精確股價作為主要輸出，不得保證獲利，也不得以訓練集結果冒充正式績效。

### 7.3 驗證與回測

- 訓練、校準、驗證與測試必須依時間先後切割，使用 purged walk-forward／rolling／expanding window，禁止 random split 或 random K-fold。
- 同一 `decision_date` 的股票不得拆到不同 fold；preprocessing 只能在各 fold 的訓練資料 fit。
- test 與 locked holdout 不得用於選特徵、門檻、成本情境或超參數。
- 回測必須模擬 t+1 可成交開盤、完整費稅、最低手續費、滑價、流動性成本、漲跌停、無法成交、公司行動、容量與 staggered cohorts。
- 若資料不足或驗收未通過，輸出 `RESEARCH_ONLY` 或 `FAIL`，不得捏造績效數字。

## 八、開發流程

1. 修改前先讀取相關頁面、元件、資料 schema、測試及 Git 差異。
2. 先定義輸入、輸出與模組邊界，再開始寫程式。
3. 新功能放入正確模組；現有檔案已過大時，先安全拆分。
4. 每次完成一個可驗證的小階段，不同功能使用不同提交。
5. 保留現有正常功能及使用者修改，不得覆蓋無關變更。
6. 缺少真實資料時先完成契約、驗證器及測試架構，明確列出缺口，不得用合成結果冒充正式績效。
7. 發布前確認正式檔案與 Git 版本一致，且沒有截斷標記、測試文案、假資料、機密或未追蹤變更。

## 九、驗證尺度

- 驗證程度與修改風險相稱，不做與本次任務無關的全面審查。
- 小型文件、文案或版面調整通常只需差異檢查及必要的針對性確認。
- 登入、安全性、資料庫、模型、交易回測及發布修改必須執行足以排除明顯風險的驗證。
- 一次針對性檢查已能證明結果時，不再重複開啟多個瀏覽器、反覆截圖或執行未受影響的完整測試。
- 只能回報實際執行過的測試與結果，不得把未執行項目寫成通過。

## 十、完成條件

- 模組責任清楚，沒有新增巨型檔案、假分層或循環依賴。
- UI、資料、模型、決策、驗證與回測互不混寫。
- 所有輸出都有資料日期、來源、模型版本與成本版本可追溯。
- 缺漏資料會明確顯示，hard fail 不會進入正式推薦。
- 不存在已知的 look-ahead bias、survivorship bias、時間錯置或明顯資料洩漏。
- 相關測試與必要驗證通過，Git 差異乾淨且交付限制已如實說明。
