# 真實資料匯入要求

> 2026-07-19 核對：只有歷史 `daily_bars` 已實際寫入 Production R2 manifest；TAIEX 歷史基準、補充資料、歷史證據與 feature artifact 目前只有程式與 workflow，尚未執行 Production。完整狀態見 [`current-status.md`](current-status.md)。

目前已建立正式資料契約，並匯入真實但仍屬 `RESEARCH_ONLY` 的市場資料；新多年日線原始列
封存於 private Cloudflare R2，Supabase 保存 queue、manifest 與摘要。專案沒有插入假股票、
假行情、假模型輸出或假回測績效。

匯入順序：

1. `data_sources`
2. `trading_calendar`
3. `securities` 與 `security_history`
4. `daily_bars` 與 `corporate_actions`
5. 籌碼、融資券及國際市場 observations
6. `feature_snapshots`
7. 模型、驗證、推論與回測結果

多年歷史日線採可續跑任務佇列漸進匯入，優先順序固定為上市普通股、上櫃普通股、ETF。
三個隔離的 FinMind credential worker 依各自剩餘額度節流並保留安全額度；只有 primary worker
建立共用任務清單，三個 worker 仍可並行下載，最後由單一 finalizer 更新首頁摘要。

截至 2026-07-19，全量 R2 稽核確認 1,971 個 immutable daily-bar objects、
2,183,917 列、295,007,049 bytes，日期範圍為 2021-07-19～2026-07-17。

- TWSE：1,080 檔、1,205,606 列。
- TPEX：891 檔、978,311 列。
- ETF：尚未開始。

GitHub Actions run `29677606085` 的完整性結果為 `PASS`，但 point-in-time 狀態仍為
`UNVERIFIED`，dataset readiness 為 `BLOCKED`。目前 PIT covered symbol 與 trading-session
intersection 均為 0，不得將原始封存完整度解讀為正式模型可用度。

新回補的完整原始列以 ZSTD 壓縮 Parquet 寫入 private Cloudflare R2；Supabase 只保存 queue、
object manifest、資料品質、版本與摘要。達到執行期限、額度或 R2 單次 object／byte 上限時停止，
由後續排程接續。原始資料在身分與時間稽核完成前一律維持
`UNVERIFIED / RAW_LANDING_ONLY / RESEARCH_ONLY`。

## 上市研究資料補充流程

目前已建立但 feature gate 關閉、且尚無 workflow run 的獨立流程：

- `HISTORICAL_BENCHMARK_BACKFILL_ENABLED`：以單一 FinMind request 封存
  `TaiwanStockTotalReturnIndex / TAIEX` 的歷史總報酬基準。
- `HISTORICAL_SUPPLEMENTAL_BACKFILL_ENABLED`：三組 credential 分工封存三大法人與
  融資融券資料。2026-07-19 三組免費 credential 實測均被 `TaiwanStockPriceAdj`
  以 HTTP 400 拒絕，因此預設以
  `HISTORICAL_SUPPLEMENTAL_ALLOWED_DATASETS=institutional_flows,margin_short`
  排除還原行情；相關任務保留並標示 provider access unavailable，日後升級權限才可明確重啟。
- `FINMIND_HISTORICAL_EVIDENCE_ENABLED`：匯入公司行動及停復牌研究證據；
  在 verified historical identity catalog 建立前不得啟用。
- `TWSE_RESEARCH_FEATURE_DATASET_ENABLED`：逐檔驗證 R2 manifest 與 Parquet 後，
  產生只有價量特徵的 ZSTD Parquet。輸出固定為 `RESEARCH_ONLY`，且不自行產生標籤。

Fugle `adjusted_bars` 使用獨立的 provider、queue RPC 與 workflow，不會認領既有 FinMind
延後任務。日期依 Fugle 契約切成含首尾最多 366 日，每輪受單一金鑰的請求預算、pacing、
執行時間與 R2 object 上限控制。`FUGLE_ADJUSTED_BACKFILL_ENABLED` 與
`FUGLE_ADJUSTED_MIGRATION_READY` 預設皆為關閉；migration 未部署或任一 gate 未開啟時不得
呼叫 Fugle、寫入 R2 或建立正式任務。即使回補成功，資料仍為
`RAW_LANDING_ONLY / RESEARCH_ONLY`，不能作為成交價。

既有 migrations 已在獨立 $0 Supabase Staging 完成先前的套用與 rollback 演練；本次 Fugle
migration 只完成 Local reset、lint、validation 及 rollback，尚未寫入 Staging 或 Production。
因此 benchmark、supplemental、evidence、Fugle 與 feature workflow 的 Production feature
gate 仍應保持關閉。

本次分支新增兩類研究契約：

- TWSE current listing identity adapter：只保存目前上市普通股的首次觀察證據，固定為
  `UNRESOLVED / FIRST_OBSERVED_AT_RETRIEVAL / IDENTITY_RESEARCH_ONLY`，不會冒充歷史 PIT 身分。
- TWSE feature artifact contract：manifest 必須由實際 Parquet read-back 產生，並驗證 byte
  size、row count、Parquet SHA-256、schema hash、dataset snapshot、source archive snapshot
  與 current identity snapshot。`twse-archive-price-volume-5d-v2` 另驗證每列有限正值的
  `decision_close_price` 成本稽核欄；該欄不屬於 17 個模型特徵，不改變 feature schema
  hash。未通過驗證的 artifact 不得進入資料組裝器。

## 上櫃普通股研究特徵流程

- R2 已有 891 檔 TPEX 普通股 `daily_bars` 原始封存；不需為建立價量特徵重抓相同資料。
- 2026-07-20 新增獨立 TPEX 17 個價量特徵 workflow、Parquet artifact 契約與 typed read-back；
  股票池固定為 TPEX 普通股，ETF 與 TWSE 資料會 fail closed。
- 官方櫃買指數 OHLC provider／normalizer 使用
  [櫃買中心指數歷史資料](https://www.tpex.org.tw/en-us/indices/stock-index/industrial/inxh.html)
  的獨立契約，不以 TAIEX 代替上櫃基準。
- Repository variable `TPEX_RESEARCH_FEATURE_DATASET_ENABLED` 是手動啟用 gate。
- [run `29716316791`](https://github.com/migao2006/tool/actions/runs/29716316791) 已成功讀取並驗證
  1,642 個 archive manifests、891 檔來源股票及 1,597,277 筆原始列，輸出 1,511,065 筆
  feature rows、879 檔股票，範圍為 2018-04-09～2026-07-17。
- 12 檔來源股票沒有產生完整 feature row；現行 audit 只有隔離列與不足歷史的彙總，沒有逐檔
  排除原因，不能把 891 檔誤稱為全部完成。
- Artifact typed read-back、Parquet SHA-256 與 schema SHA-256 已驗證通過。
- 新增獨立 `build-tpex-daily-feature-delta.yml`：成功的每日市場匯入後，以 exact date 讀取
  Supabase TPEX canonical `daily_bars` 最新完整 revision，並串接已驗證 R2 歷史視窗。輸出只保存
  為 `RESEARCH_ONLY` GitHub artifact，不寫回 Production，也不放寬完整歷史 feature artifact 契約。
- Daily delta 的 dataset snapshot 同時綁定歷史 archive snapshot、current identity snapshot、
  canonical daily-bar series snapshot、feature schema 與 `as_of_date`；任何日期缺失、revision 不完整、
  SHA／schema／row read-back 不一致都會 fail closed。
- 目前尚無完整官方 daily payload archive，因此 canonical daily-row snapshot 不等於官方 raw payload
  驗證；這項限制會以固定 reason code 保留，不能回填或冒充 point-in-time 證據。
- 已新增 TPEX 官方月 OHLC 的獨立 queue／RPC、Parquet、immutable R2 read-back、CLI 與 GitHub
  Actions workflow；Local migration、validation、rollback 與 schema lint 已通過。截至
  2026-07-20，Production 同契約已有 2018-04～2026-06 共 99 個 manifests／objects、2,006 列。
- 這份 OHLC 是櫃買價格指數，不是總報酬指數。
- 本次新增 `build-tpex-prepared-research-dataset.yml` 與 bounded CLI，只接受 `horizon=5`，並以
  `TPEX_PREPARED_RESEARCH_DATASET_ENABLED` 控制。它會驗證 feature artifact、daily-bar／benchmark
  manifest snapshot、R2 bytes、SHA-256、Parquet schema 與每列 lineage，再以相同
  `t+1 open → 第 5 個交易日 close` 路徑輸出 read-back verified GitHub artifact。
- TPEX session snapshot 暫由已驗證 benchmark rows 決定，明確保留
  `TRADING_CALENDAR_DERIVED_FROM_BENCHMARK_RESEARCH_ONLY`；因此尚不能升級為正式 PIT 資料集，
  也尚未建立模型或 UI 輸出。

以上資料與程式均維持 `RESEARCH_ONLY`；完成 feature 或 prepared artifact 不等於完成
point-in-time、正式交易日曆、公司行動、可交易性或模型驗收。

上述程式、測試與 GitHub feature artifact 仍不等於正式訓練資料。真實標籤組裝仍必須同時提供原始可執行 OHLC、公司行動／停牌區間與
交易成本設定；缺任一項時 fail closed，不發布模型績效。

不受 FinMind token 額度控制的官方 current OpenAPI 匯入使用有界平行下載：全域最多 4 個、
同一 provider 最多 2 個同時請求。日行情、證券快照、公司行動與基準資料會先完成全部下載
及驗證，再進入原有資料庫寫入階段；不得用無上限 concurrency 換取速度或造成部分批次寫入。

每筆 fact 必須帶 `source_id`、`source_version`、`available_at` 與 `ingested_at`。修訂資料新增版本，不得直接覆寫歷史後假裝當時已知。

資料匯入使用伺服器端資料庫連線，憑證只放環境變數；不得把 Supabase `service_role`、secret key 或資料庫密碼寫入前端與 Git。
