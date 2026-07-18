架構一定要分開，不可以把大量程式擠在同一個檔案裡。

# 專案開發規範

本專案是「台股 2～10 個交易日短波段預測系統」，目前唯一正式產品範圍為「5 個交易日短波段選股 MVP」。所有修改必須可驗證、可追溯、可維護，並以真實資料與時間正確性為前提。

## 一、規則優先順序

發生衝突時依下列順序處理：

1. 資料安全、時間正確性、禁止捏造及禁止洩漏機密。
2. 使用者在當次任務中的明確要求。
3. 本文件的產品範圍、架構邊界及發布限制。
4. 保留既有正常功能，採用最小且可回復的修改。
5. 開發速度與便利性。

不得因趕工而加入假資料、跳過必要驗證、破壞既有功能或將大量邏輯堆進單一檔案。

## 二、目前產品範圍

### 2.1 正式功能

- 第一版固定使用 `horizon=5`。
- API、型別及元件必須接受 `horizon` 參數，以便日後擴充 3、10、2 日獨立模型。
- 2、3、10 日模型完成前，不得提供可操作切換、假結果或暗示已可使用。
- ETF 暫不混入普通股票候選清單或模型；上市與上櫃以篩選器區分。
- 不新增管理員、自動下單、持倉損益或複雜投資組合功能。

### 2.2 頁面與導覽

固定維持四個使用者頁面：

1. 今日總覽
2. 5 日候選股
3. 個股決策詳情
4. 自選股

底部導覽只顯示「總覽、5 日候選、自選」。個股詳情只能由股票項目進入，不占底部導覽。

### 2.3 UI 原則

- 使用繁體中文、精簡文案及清楚資訊層級。
- 優先支援 iPhone 單手操作；觸控區至少 44×44 px，正確處理 safe area。
- 所有頁面必須處理 loading、empty、stale、API error、hard fail、`RESEARCH_ONLY` 及 `FAIL`。
- 沒有資料時只顯示「—」、「尚無資料」或「尚未更新」。禁止用假股票、假機率、假績效或 placeholder 冒充正式結果。
- 個股技術稽核資料可預設折疊，但不得刪除。

## 三、前端顯示契約

### 3.1 全域規則

- 排名模型是唯一個股排序來源；前端不得重新加權產生 `final score`。
- Rank Score 只能解釋為「當日橫斷面排名百分位」，不是機率、報酬率或模型信心。
- P10／P50／P90 是條件報酬分位數，不是最低、平均、最高報酬，也不是獲利保證。
- 沒有獨立 expected return 模型或 OOS 校準映射時，不得顯示「預期報酬」或「EV」。
- 不得顯示精確未來股價、虛構 AI 信心或未經 OOS 驗證的結果。
- `data_quality` hard fail 股票不得進入正式推薦清單。

### 3.2 今日總覽

只顯示決策摘要：資料日期、決策時間、5 日市場方向機率、市場狀態、預測波動、曝險上限、決策數量、hard fail 數量、通過門檻的前 3～5 檔股票、模型與成本版本，以及 `PASS`／`RESEARCH_ONLY`／`FAIL`。

模型驗證報告與研究設定使用彈窗或抽屜，不另建頁面。一般使用者不得修改模型超參數、校準參數、標籤門檻或 locked holdout。

### 3.3 5 日候選股

- 正式順序只使用 Rank Score 或 `global_rank`。
- 至少顯示股票識別、市場、產業、全市場與產業排名、校準後三分類機率、`net_q10/q50/q90`、交易成本、資料品質、決策及主要 `reason_codes`。
- 可篩選市場、產業、決策、資料品質、流動性、Rank Score、`calibrated_p_up` 與 cost profile。
- 被 hard fail 排除的股票只能在獨立抽屜顯示原因，不得混入推薦。

### 3.4 個股決策詳情

頁首顯示決策、主要原因、資料日期、決策時間及 horizon。依序呈現：

1. data quality hard gate
2. tradability gate
3. liquidity 與 capacity gate
4. market exposure gate
5. calibrated probability gate
6. net quantile gate
7. rank eligibility gate
8. position 與 capacity limits

每個 gate 必須顯示通過狀態、實際值、門檻及 `reason_code`。頁面另須保留排名、方向機率、gross/net quantiles、風險容量、模型版本、特徵 schema、成本版本、來源日期與資料品質等稽核資訊。

### 3.5 自選股

- 自選股只追蹤後端結果，不重新計算排名。
- 顯示 Rank Score、全市場排名、決策、三分類機率、`net_q10/q50/q90`、資料品質、原因，以及與前一交易日相比的排名與決策變化。
- 可篩選全部、`CANDIDATE`、`WATCH`、`NO_TRADE`。

## 四、程式架構

### 4.1 模組責任

- 每個檔案只負責一項主要職責。
- 頁面只組合元件；元件不得直接包含模型或資料庫邏輯；資料層不得依賴 UI。
- 共用邏輯只能保留一份，禁止複製貼上相同計算、格式化、篩選或標籤程式。
- 檔案超過約 300 行、元件超過約 150 行，或同時負責兩種以上工作時，應優先拆分。
- 不得將所有頁面、樣式或互動集中在單一 HTML、CSS、JavaScript 或 Python 檔案。
- 不得無故重寫專案；修改必須小範圍、可測試、可回復。

### 4.2 目錄邊界

```text
src/
  pages/          # 頁面組合
  components/     # 共用 UI 元件
  styles/         # tokens、共用及頁面樣式
  core/           # router、state、設定與型別
  data/           # API client、schema、時間對齊及資料品質
  labels/         # 共用標籤與交易路徑
  features/       # 特徵計算
  models/         # stock、market、risk 模型
  calibration/    # 機率與分位數校準
  decision/       # 透明決策政策
  validation/     # walk-forward、指標及洩漏檢查
  backtest/       # 成本、成交限制及績效計算
tests/            # 對應模組測試
```

目錄名稱可依技術棧調整，但不得建立內容仍互相耦合的假分層。

## 五、資料、模型與決策

### 5.1 Point-in-time 資料

- 所有特徵必須滿足 `available_at <= decision_at`。
- 財報、月營收、事件與公司行動使用實際公布時間，不得用所屬期間或修正後資料回填歷史。
- 國際市場資料依台灣實際可取得時間對齊；不得使用尚未發生的同日美股收盤資料。
- 隔夜與盤中報酬分開；外資、投信與自營商資料分開。
- 上市、上櫃與 ETF 使用適當基準並分開評估；ETF 不與普通股混合訓練。
- 歷史股票池應納入下市、停牌及失敗公司，避免生存者偏誤。
- 關鍵行情、公司行動或交易狀態缺漏時必須 hard fail。

### 5.2 模型責任

- 排名、方向三分類、報酬分位數、波動風險、市場狀態與 Triple Barrier 必須是獨立模組。
- 排名模型決定個股順序；方向機率與分位數只負責交易 gate；市場模型只控制總曝險；波動模型只控制風險與部位。
- `decision_policy` 只負責 gate、Top-K、容量及部位限制，不建立另一套加權排名。
- 不得以精確股價為主要輸出、不得保證獲利、不得以訓練集結果冒充正式績效。

### 5.3 驗證與回測

- 使用 purged walk-forward、rolling 或 expanding window，禁止 random split 及 random K-fold。
- 同一 `decision_date` 不得拆到不同 fold；preprocessing 只能在每個 fold 的訓練資料 fit。
- test 與 locked holdout 不得用來選特徵、門檻、成本情境或超參數。
- 回測須涵蓋 t+1 可成交開盤、完整費稅、最低手續費、滑價、流動性成本、漲跌停、無法成交、公司行動、容量與 staggered cohorts。
- 資料不足或驗收未通過時，只能輸出 `RESEARCH_ONLY` 或 `FAIL`，不得捏造數字。

## 六、登入與資料庫安全

- 登入只使用 Email＋密碼；支援登入、建立帳號及登出，不提供忘記密碼或密碼重設。
- Supabase 負責 Auth、Email 確認與 Session；不接入其他寄信或驗證碼服務。
- Auth UI、controller、service 與樣式必須分離，不得堆入主 `app.js`。
- 前端只能使用 Supabase publishable key。禁止提交 `service_role`、secret、密碼或 access token。
- 個人資料表必須啟用 RLS，並以 `auth.uid()` 限制資料擁有者。
- 登入或資料庫未連接時，顯示真實原因並停用不可能成功的操作，不得模擬完成。

## 七、工具鏈與自動檢查

目前可用工具鏈包含 Git、GitHub CLI、Node.js、npm、pnpm、Python、uv、pytest、Ruff、basedpyright、pre-commit、Playwright、Biome、SQLFluff、actionlint、Gitleaks、pip-audit、Supabase CLI 與 Vercel CLI。工具已安裝不代表自動授權部署、修改遠端資料、變更資料庫或改寫專案設定。

### 7.1 Python

- Python 環境與套件優先使用 `uv`；專案依賴寫入 `pyproject.toml` 並以 `uv.lock` 鎖定，不得依賴本機全域套件才能執行。
- 使用 Ruff 做格式化與 lint、basedpyright 做型別檢查、pytest 做測試、pip-audit 做相依套件漏洞檢查。
- 未有明確必要時，不再加入 Black、Flake8、isort、mypy、Poetry 或 pip-tools 等重疊工具。
- 格式化、型別與安全掃描不能取代標籤、交易成本、時間切割及資料洩漏測試。

### 7.2 前端與瀏覽器

- 前端套件管理統一使用 `pnpm`，不得同時提交 npm 或 Yarn lockfile。
- 使用 Biome 檢查及格式化 JavaScript、CSS、JSON；使用 Playwright 執行真實瀏覽器互動測試。
- 全域 Biome 只供本機操作。正式接入專案時，必須在 `package.json` 鎖定版本、提交 `pnpm-lock.yaml` 與 `biome.json`，並排除 `src/vendor`、壓縮檔及其他第三方產物。
- 已使用 Playwright 時，不新增 Selenium、Cypress 或 Puppeteer，除非有已記錄且 Playwright 無法滿足的需求。
- 瀏覽器測試至少覆蓋主要導覽、登入狀態、空資料、API 錯誤及 iPhone viewport；不得使用假預測資料讓測試通過。

### 7.3 SQL、工作流程與機密

- Supabase SQL 使用 SQLFluff 的 PostgreSQL dialect 做針對性檢查；不得讓 formatter 未經審查大量改寫 migration 或 schema。
- GitHub Actions workflow 使用 actionlint 檢查；CI 執行指令應與本機一致，不得假設 runner 已安裝任何全域工具。
- Gitleaks 用於提交前與 CI 機密掃描；pip-audit 用於 Python 相依安全檢查。掃描結果不得在公開輸出中完整顯示 secret。
- 任何已曝光的 API key、token 或密碼都必須輪替；加入 ignore 或刪除目前檔案不能消除 Git 歷史中的洩漏。
- pre-commit hook 必須由版本化的 `.pre-commit-config.yaml` 管理；自動修正後要重新檢查差異，不得覆蓋使用者的無關修改。

### 7.4 任務啟動偵測與自動化

- 開始工作時，只偵測本次任務相關工具，不必每次掃描全部工具；可使用 `Get-Command` 與 `<tool> --version` 確認實際可用狀態。
- 若目前程序找不到指令，先檢查 Windows User／Machine PATH 與既有安裝位置。長時間執行中的 Codex 或終端可能仍使用舊 PATH，不得因此直接重裝工具；重新啟動應用程式或開啟新終端後再確認。
- 相關工具可用且行為位於當次任務授權範圍內時，直接使用且不反覆詢問：Git 使用 `git`、GitHub 使用 `gh`、Python 環境與指令使用 `uv`／`uv run`、前端使用 `pnpm`、瀏覽器測試使用 Playwright、Supabase 管理使用 `supabase`。
- 優先自動完成安全且範圍內的專案結構與 Git 差異檢查、格式化、lint、型別檢查、測試、瀏覽器互動、Console／Log 檢查、截圖與 API 診斷。
- 只有需要登入、缺少權限、接觸機密、執行破壞性操作、進行未明確授權的遠端狀態變更，或必須由使用者決定產品方向時，才要求使用者介入。
- 工具清單代表已偵測到的開發能力，不代表永久可用或自動授權；實際使用前仍須針對本次任務確認。Docker 目前不列為已安裝工具。
- 部署與遠端資料庫變更仍須遵守第六章及第九章；未經當次明確授權不得操作 Vercel。

## 八、工作流程與驗證尺度

1. 修改前先讀取相關程式、schema、測試及 Git 差異。
2. 先確認輸入、輸出與模組邊界，再做最小必要修改。
3. 保留既有正常功能及使用者修改，不覆蓋無關變更。
4. 驗證程度與風險相稱；文件或小型 UI 修改做針對性檢查，Auth、資料庫、模型、回測及發布需執行足以排除明顯風險的測試。
5. 已有一次可靠檢查能證明結果時，不反覆執行無關的完整測試或瀏覽器截圖。
6. 只能回報實際執行過的測試；缺少真實資料時列出缺口，不以合成結果冒充正式績效。
7. 溝通只保留開始、重要階段、阻塞與交付；不必每句附完成度或等待時間。

## 九、Git 與發布限制

- 本專案只允許使用 Git 提交並推送至 GitHub。
- 未經使用者在當次任務明確授權，禁止操作 Vercel 或任何其他部署平台，包括 CLI、API、MCP、建立、提升、回復及刪除部署。
- GitHub 推送不等於授權外部平台部署；若整合會自動觸發外部部署，必須先說明。
- 每次提交只包含本次任務相關檔案；提交前檢查差異、測試、未追蹤檔案及機密。
- GitHub 推送若受登入、權限、憑證或網路阻擋，直接回報，不得改用其他平台繞過。

## 十、完成條件

- 模組責任清楚，沒有新增巨型檔案、假分層或循環依賴。
- UI、資料、模型、決策、驗證與回測沒有互相混寫。
- 輸出可追溯至資料日期、來源、模型版本與成本版本。
- 缺漏資料明確顯示，hard fail 不會進入正式推薦。
- 不存在已知的 look-ahead bias、survivorship bias、時間錯置或明顯資料洩漏。
- 必要測試通過，Git 差異已檢查，且只宣告實際完成的工作。
