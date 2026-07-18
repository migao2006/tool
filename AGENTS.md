# 專案代理核心規範

本專案是「台股 2～10 個交易日短波段預測系統」，目前唯一正式產品範圍為「5 個交易日短波段選股 MVP」。

執行任何任務前，先閱讀本檔案，以及與任務相關的 `docs/` 規範。不得為與任務無關的內容載入或修改其他模組。

## 一、規則優先順序

發生衝突時依下列順序處理：

1. 資料安全、時間正確性、禁止捏造及禁止洩漏機密。
2. 使用者當次任務的明確要求。
3. 本專案的產品範圍、架構邊界及發布限制。
4. 保留既有正常功能，採用最小且可回復的修改。
5. 開發速度與便利性。

不得因趕工而：

- 加入假資料或假績效。
- 使用未來資料。
- 跳過必要驗證。
- 破壞既有功能。
- 覆蓋無關修改。
- 關閉 TLS、RLS、Auth 或其他安全機制。
- 將大量邏輯集中於單一檔案。

## 二、自主執行授權

代理可在本專案及已連結的 GitHub、Vercel、Supabase、Cloudflare R2 資源內，自行決定安全且合理的執行順序，不必逐項請示。

代理可自行：

- 讀寫專案程式、設定及文件。
- 安裝或更新必要依賴。
- 執行格式化、lint、型別檢查及測試。
- 建立分支、提交、推送及 PR。
- 檢查並修復 CI。
- 建立 Preview、部署及重新部署。
- 建立並套用非破壞性 migration。
- 管理 RLS、Auth、Edge Functions。
- 管理本專案 private R2 bucket 內的 object 與必要非破壞性設定。
- 設定必要環境變數。
- 檢查 GitHub Actions、Vercel 及 Supabase logs。
- 修復失敗流程並重新驗證。

可回復且位於本專案範圍內的操作應直接完成，並留下 Git、PR、migration、deployment 或 workflow 紀錄。

只有以下情況需要使用者介入：

- 登入或雙因素驗證。
- 缺少必要帳號或憑證。
- 新增付費或訂閱。
- 刪除專案、網域或正式資料。
- 不可回復或大規模破壞性操作。
- 操作跨出本專案。
- 產品方向存在會實質影響結果的選擇。

## 三、專案級可觀測性與權限

代理可讀取本專案的：

- Repository 結構、Git 歷史、分支及提交。
- PR、Issue、review comments。
- GitHub Actions logs、checks 及 artifacts。
- Vercel Preview、Production、build logs 及 runtime logs。
- Supabase schema、migration、RLS、Auth、Functions 及 logs。
- Cloudflare R2 bucket 設定狀態、object metadata、容量與操作結果。
- 環境變數名稱、適用環境及是否已設定。

代理可建立或更新本專案的：

- 分支、提交、PR、Issue 及 workflow。
- Preview 與 Production deployment。
- Migration、RLS、Edge Functions。
- 本專案 private R2 bucket 內的 object 與專案級設定。
- Development、Preview、Production 環境變數。

代理可以設定、更新及輪替 secret，但不得：

- 顯示或回傳 secret 明文。
- 列出 token、密碼或私鑰。
- 將機密寫入程式、log、Commit、PR、Issue 或聊天。
- 取得帳務、組織／Cloudflare Account 擁有者或跨專案權限。

## 四、產品核心限制

- 第一版正式支援值只有 `horizon=5`。
- API、型別及元件必須接受 `horizon`。
- 其他 horizon 未完成前，必須回傳 `UNSUPPORTED_HORIZON`。
- 不得使用 5 日模型冒充 2、3 或 10 日模型。
- ETF 不得混入普通股票候選清單或訓練資料。
- 不新增管理員、自動下單、持倉損益或複雜投資組合功能。
- 不得顯示精確未來股價、虛構 AI 信心或保證獲利。
- 自動回補的多年歷史行情以壓縮 Parquet 保存於 private Cloudflare R2；Supabase 只保存任務控制、object manifest、稽核 metadata 與前端摘要。
- 未完成 point-in-time 身分、公司行動及可交易性驗證的歷史資料必須維持 `RAW_LANDING_ONLY / RESEARCH_ONLY`，不得直接用於正式模型或推薦。
- 前端不得直接存取 R2、`service_role` 或任何資料供應商憑證；資料必須經後端 service／repository 讀取。

## 五、核心架構規則

- 每個檔案只負責一項主要職責。
- 頁面只組合元件。
- UI 不得包含模型、SQL 或資料庫邏輯。
- 資料層不得依賴 UI。
- 排名、方向、分位數、波動、市場及 Triple Barrier 必須分開。
- 共用邏輯只能保留一份。
- 禁止循環依賴及跨層捷徑引用。
- 禁止巨型檔案及假分層。
- 檔案約超過 300 行、元件約超過 150 行，或同時承擔多項責任時，優先拆分。
- 行數只是警示，不得拆成大量只有轉傳功能的小檔案。

## 六、修改流程

1. 先讀取相關程式、schema、測試、logs 及 Git 差異。
2. 確認輸入、輸出、模組責任及受影響範圍。
3. 採用最小且可回復的修改。
4. 保留既有正常功能及使用者的無關修改。
5. 執行與風險相稱的驗證。
6. 檢查 Git 差異、未追蹤檔案及機密。
7. 使用 Git 留下紀錄並推送至 GitHub。
8. 只能回報實際執行過的測試與操作。

## 七、相關規範

依任務閱讀：

- 產品與 UI：[`docs/product-ui.md`](docs/product-ui.md)
- 程式架構：[`docs/architecture.md`](docs/architecture.md)
- 資料與模型：[`docs/data-model.md`](docs/data-model.md)
- 資料匯入：[`docs/data_import.md`](docs/data_import.md)
- R2 歷史封存：[`docs/r2-historical-archive.md`](docs/r2-historical-archive.md)
- Auth 與安全：[`docs/security.md`](docs/security.md)
- 工具、Git 與發布：[`docs/tooling-release.md`](docs/tooling-release.md)

## 八、完成條件

只有符合以下條件才能宣告完成：

- 沒有新增巨型檔案、假分層或循環依賴。
- UI、資料、模型、決策、驗證及回測沒有混寫。
- 缺漏資料有明確顯示。
- Hard fail 不會進入正式推薦。
- 輸出可追溯至資料日期、模型版本、成本版本及 Git commit。
- 不存在已知 look-ahead bias、survivorship bias 或明顯資料洩漏。
- 必要測試已實際執行。
- Git 差異及機密已檢查。
- 未通過正式驗收時，狀態為 `RESEARCH_ONLY` 或 `FAIL`。
