# 目前實作與阻塞狀態


<!-- release-manifest:status-header:start -->
> 更新日期：2026-07-24（Asia/Taipei）
>
> 文件基準：最新發布 commit 未記錄於目前可用證據，不得沿用舊快照 commit；OOS 驗證 workflow 使用 `29690820942`，最新特徵與具完整 artifact／provenance 證據的研究推論 workflow 使用 `29693937930`、`29701335309`
>
> 系統狀態：`RESEARCH_ONLY`
>
> Repository 目前包含 38 個 migration 檔案；本修補新增且待 Staging／Production 部署驗證：`20260720170000_prediction_snapshot_rate_limit.sql`、`20260720190000_prediction_snapshot_read_rpc.sql`、`20260721090000_prediction_snapshot_calendar_freshness.sql`、`20260724044115_decision_policy_status_semantics.sql`。
>
> Staging／Production 的既有文件最後完整紀錄均為 31／31 筆；其後 Repository 共有 7 檔：`20260720051630_tpex_price_index_ohlc_queue.sql`、`20260720061143_scope_prediction_runs_by_market.sql`、`20260720064801_exclude_legacy_prediction_publisher_from_lint.sql`、`20260720170000_prediction_snapshot_rate_limit.sql`、`20260720190000_prediction_snapshot_read_rpc.sql`、`20260721090000_prediction_snapshot_calendar_freshness.sql`、`20260724044115_decision_policy_status_semantics.sql`。本修補未連線重新驗證這些 migration 的遠端套用狀態，不得由檔案存在與否推測已部署或未部署。
>
> Prediction Snapshot 主要讀取路徑已改為單一 RPC `market_data.get_prediction_snapshot_rows_v2(integer,text,timestamptz)`，正常路徑預期每次快照只產生 1 次 PostgREST 請求。預設模式為 `rpc`；RPC 未部署時 fail closed，只有明確設定 `legacy` 才走緊急舊路徑。
> Freshness 優先使用 `TRADING_CALENDAR`，要求 45 日連續可信日曆覆蓋（上限 62 日；RPC 取回 63 個曆日以涵蓋就緒時間前的邊界）；缺日或不可用時明確改採 `WALL_CLOCK_FALLBACK`，不得猜測休市日。
> P2 已抽出 TWSE／TPEX 共用月度 benchmark 與 feature CLI 協調器，並將三個核心入口函式控制在 56、34、40 行。
> 帳號復原使用 `pkce` 與 `PASSWORD_RECOVERY`；Supabase Redirect URL allowlist 與正式 SMTP 尚未由本修補連線重新驗證。
>
> CI 品質工作：`quality-security`；彙總 gate：`test-gate`；外部 GitHub Actions 全部固定完整 commit SHA。遠端 branch protection 尚未由本修補重新驗證。
>
> Vercel 使用 `vercel.json` 強制 CSP 與安全標頭；本修補尚未直接讀取正式站 response headers，因此遠端生效狀態不得推測。
>
> 本區塊與下方具完整 artifact／provenance 證據的快照由 `release-manifest.json` 產生；請勿直接修改。
<!-- release-manifest:status-header:end -->

## 一、環境與 Migration

### Supabase Staging

- 已建立每月費用為 `$0` 的獨立 Staging 專案 `alpha-lens-staging`。
- Project ref：`kretvnnfavndkmckyidl`。
- 專案狀態：`ACTIVE_HEALTHY`。
- 既有文件紀錄顯示 Staging migration history 曾與 Production 對齊，共 31 筆 migrations；
  當時最新 migration 為 `20260719152201_publish_research_snapshot_atomically.sql`。
- 新約束已實測允許來源日期後才取得的快照，仍拒絕未來快照日期，且驗證資料無殘留。
- `supabase db lint --linked --level error`：0 個 schema error。
- Supplemental task transaction RPC 與研究快照原子發布 RPC contract：`PASS`。
- 原子發布 RPC 已完成 transaction rollback 演練；`anon` 與 `authenticated` 不可執行，只有 `service_role` 可執行。
- Staging 只用於隔離驗證；它不是 Supabase Pro Branching，也不是 Production。

### Supabase Production

- 既有文件紀錄顯示 Production migration history 曾與 Staging 對齊，共 31 筆 migrations；
  當時最新 migration 為 `20260719152201_publish_research_snapshot_atomically.sql`。
- Production `db lint` 沒有 schema error；原子發布 RPC 權限已驗證為 service-role only。

### 本機隔離環境

- Docker Engine `29.6.1`、Docker Compose `5.3.0` 與 Docker Desktop 已驗證可用。
- 既有文件紀錄顯示 Supabase Local 曾用 Docker 完整重建前 32 個 migrations，最後包含
  `20260720051630_tpex_price_index_ohlc_queue.sql`；相關 TPEX benchmark validation、rollback 與
  schema lint 曾通過。
- 本修補未啟動共用 Supabase Local，也未寫入 Staging／Production；遠端 migration
  history 未重新驗證，Repository 第 32～38 個 migration 的套用狀態不得由檔案存在推測。
- `20260724044115_decision_policy_status_semantics.sql` 已在一次性 PostgreSQL 17
  container 完成全 migration chain、legacy backfill、publisher/RPC、約束、權限與
  rollback 驗證；container 與測試資料已移除。這不等於 Staging 或 Production 已部署。

## 二、已封存及已產生的真實資料

### 歷史普通股日線行情

GitHub Actions run `29677606085` 的 R2 完整稽核結果：

| 項目 | 已驗證數量 |
| --- | ---: |
| Parquet objects | 1,971 |
| 總列數 | 2,183,917 |
| 總位元組 | 295,007,049 |
| TWSE symbols | 1,080 |
| TPEX symbols | 891 |

- Object 與 manifest 的完整性稽核為 `PASS`。
- 這批資料仍是 `RAW_LANDING_ONLY`、`POINT_IN_TIME_UNVERIFIED`、`RESEARCH_ONLY`。
- 完整性 `PASS` 只代表 object、hash 與 manifest 可讀且一致，不代表可直接用於正式模型。

2026-07-20 的 Production manifest 即時統計已增至 4,054 個 `daily_bars` objects、
3,882,062 列。這是資料庫 manifest 統計，不等同於重新完成 4,054 個 objects 的全量
R2 integrity audit；正式完整性證據仍以上述 run `29677606085` 為準。

### 台股交易日曆觀測

- Supabase 已保存 2,077 筆 calendar observations。
- 觀測範圍為 2018-01-02 至 2026-07-17。
- 目前仍屬研究排程提示；尚未完成可驗證開收盤時間、臨時休市及 decision cutoff 的正式 point-in-time 契約。

### TAIEX 歷史基準

GitHub Actions run `29678818649`：

- 執行成功。
- 已產生 1 個 benchmark Parquet object。
- 共 1,214 列。
- 範圍為 2021-07-19 至 2026-07-17。
- 現況仍是 `RESEARCH_ONLY`、`POINT_IN_TIME_UNVERIFIED`、`NOT_EXECUTION_PATH_ALIGNED`。
- 基準目前是 close-based 歷史序列，尚未與股票的 `t+1 可成交開盤進場／第 5 個交易日收盤退出` 路徑完全對齊。

### 上市股票研究特徵

[GitHub Actions run `29693937930`](https://github.com/migao2006/tool/actions/runs/29693937930) 已在 commit
`be9ca59c4bbae18de88cd95b080ceecb4c60fda3` 產生 v2 特徵 artifact：

| 項目 | 已驗證結果 |
| --- | ---: |
| 執行狀態 | success |
| Dataset version | `twse-archive-price-volume-5d-v2` |
| Feature rows | 1,908,104 |
| Symbols | 1,080 |
| Source archives | 2,009 |
| 最新橫截面 | 2026-07-17 |
| Parquet bytes | 274,902,797 |
| Hash／read-back | PASS |

v2 新增並驗證 `decision_close_price`，供每日推論依真實收盤價重新計算交易成本；原有 17 個
模型特徵與 feature schema hash 保持不變。Provenance：

- Parquet SHA-256：`24c90589d51de6b0c06f084ca977c4bfb99993f91164d65b3bad33bce3c73aac`。
- Dataset snapshot：`c349a800d40dd73319c27fa39ca42107252230f1c14606919d7b6d90f52a919f`。
- Parquet schema SHA-256：`a53d4976fb779f89054786e2f960d355f4f4426a90eb4a46eadce251c1c22dad`。
- Model feature schema hash：`8e256243dbe0018a7a96a637b989e2338dcf06a8f2e9a9d42faf888c7f54cd53`。
- Source archive snapshot：`5438e7435de331b27ad2723eeee2544641e0e2520a56ebd949bbaac08b259407`。
- GitHub artifact：`8444804465`，digest `70143a1cb7f8ecb4905c67787830c991fded7ab89f913d5b1ce46dca3c92b19b`。

這份 artifact 已完成 schema、hash 與 read-back 驗證，但只能用於研究。主要 reason codes：

- `CURRENT_SECURITIES_SURVIVORSHIP_MAPPING`
- `HISTORICAL_IDENTITY_NOT_POINT_IN_TIME`
- `TRADING_SESSIONS_DERIVED_PER_SYMBOL`
- `RESEARCH_SCHEDULING_HINT`
- `LABELS_NOT_ASSEMBLED`
- `BENCHMARK_ARCHIVE_NOT_CONNECTED`

因此其狀態必須維持：

- `usage_scope=FEATURE_RESEARCH_ONLY`
- `point_in_time_status=UNVERIFIED`
- `label_status=LABELS_NOT_ASSEMBLED`
- `system_status=RESEARCH_ONLY`

### 上櫃普通股研究特徵（2026-07-20 新增）

- R2 已有 891 檔上櫃普通股 `daily_bars` 原始封存；其狀態仍是
  `RAW_LANDING_ONLY / POINT_IN_TIME_UNVERIFIED / RESEARCH_ONLY`。
- 2026-07-20 新增獨立的 TPEX 17 個價量特徵建置 workflow、Parquet artifact 契約與 typed
  read-back 驗證，不會混用上市或 ETF 股票池。
- 同日新增櫃買中心官方指數 OHLC provider 與 normalizer，資料來源契約對應
  [櫃買中心指數歷史資料](https://www.tpex.org.tw/en-us/indices/stock-index/industrial/inxh.html)。
- Repository variable 名稱為 `TPEX_RESEARCH_FEATURE_DATASET_ENABLED`；必須明確開啟後，
  workflow 才可執行。
- [GitHub Actions run `29716316791`](https://github.com/migao2006/tool/actions/runs/29716316791)
  已成功完成第一次真實建置及 typed read-back：

  | 項目 | 已驗證結果 |
  | --- | ---: |
  | Archive manifests／來源股票 | 1,642／891 |
  | Source／parsed rows | 1,597,277／1,564,233 |
  | Feature rows／實際股票 | 1,511,065／879 |
  | 排除列 | 86,212 |
  | 日期範圍 | 2018-04-09～2026-07-17 |
  | Parquet bytes | 219,459,812 |

- 12 檔來源股票沒有產生 feature row；現行 audit 只保存彙總原因，包括 33,044 筆隔離列與
  各視窗的不足歷史，沒有逐檔排除清單，因此不得捏造這 12 檔的個別原因。
- Parquet SHA-256 為 `7e12dac2707e7dea17559ffe6b69f74f08ae4790c712c52bd33de1564eb3da8b`，
  schema SHA-256 為 `a53d4976fb779f89054786e2f960d355f4f4426a90eb4a46eadce251c1c22dad`；
  feature schema 為 `b9fbc304b7cd22310b62b291953440d231a44d554c93021aaae62d154f9acf96`。
- 已建立櫃買價格指數月 OHLC 的獨立 Parquet／R2 immutable archive、Supabase queue／RPC、CLI
  與 GitHub Actions workflow。Local 已通過完整 migration、validation、rollback 再套用及
  schema lint；截至 2026-07-20，Production 同契約已有 2018-04～2026-06 共 99 個 manifests／
  objects、2,006 列 benchmark OHLC。
- 這份基準固定標示為 `PRICE_INDEX_NOT_TOTAL_RETURN`。本次新增獨立、手動且 feature-gated 的
  `horizon=5` prepared research dataset 管線：它會從 typed feature artifact、精確 TPEX daily-bar
  manifests 與官方櫃買指數 manifests 讀取 R2，逐一驗證 object／hash／row lineage 後，才按相同
  `t+1 open → 第 5 個交易日 close` 路徑建立研究標籤。
- 管線輸出仍固定為 `RESEARCH_ONLY / MODEL_RESEARCH_ONLY`；交易日 session snapshot 是由已驗證
  benchmark bytes 派生，不是獨立官方 calendar，且 PIT 身分、公司行動與完整交易狀態尚未驗證。
  尚未執行正式 prepared artifact、模型或 UI 發布。

上述完成的是可執行且 fail-closed 的研究管線，不是正式上櫃模型；系統狀態維持
`RESEARCH_ONLY`。

### 上市 5 日歷史 OOS 研究結果

[GitHub Actions run `29690820942`](https://github.com/migao2006/tool/actions/runs/29690820942) 已於 2026-07-19 成功完成完整訓練與發布：

| 項目 | 已驗證結果 |
| --- | ---: |
| Prepared records | 1,196,162 |
| Purged walk-forward folds | 5 |
| OOS 評估日期／fold | 63 |
| Locked holdout rows（保留未執行） | 170,032 |
| 最新 OOS research predictions | 672 |
| Supabase `prediction_run_id` | 1 |
| `as_of_date` | 2025-05-02 |
| `decision_at` | 2025-05-02 17:00:00 +08:00 |
| Model version | `twse-price-research-h5-v1` |
| Training end date | 2024-06-18 |

排名平均結果：

| 指標 | Rank model | 20 日動能基準 |
| --- | ---: | ---: |
| NDCG@10 | 0.311856 | 0.330156 |
| NDCG@20 | 0.305487 | 0.317444 |
| NDCG@50 | 0.287796 | 0.293994 |
| Rank IC | -0.054552 | -0.023127 |
| ICIR | -0.358336 | -0.181064 |

Rank model 在上述 NDCG 與 Rank IC 指標均未優於 20 日動能基準，未通過正式排名驗收。方向模型的 fold 平均 log loss 為 1.037198、macro-F1 為 0.333102、ECE 為 0.030459；分位數模型的 P10 breach 為 12.1255%、P90 exceedance 為 9.9223%、P10～P90 coverage 為 77.9522%，校準前後 crossing rate 均為 0。

Production Supabase 已保存 672 筆歷史研究預測；legacy publisher 曾把它們記為
`NO_TRADE`。新契約依 `RESEARCH_ONLY` 與缺少 formal policy evidence 將它們 fail
closed 重分類為 `MISSING_REQUIRED_DATA`、`decision=null`，不是有效的政策不進場
結果。這些列可供 UI 顯示歷史 OOS 研究結果，但不得解讀為當日正式推薦。

Artifact／provenance：

- GitHub artifact：`8443586850`，digest `57eb16f26d50e2408020c51a4e1bef2f179e998819baf2f550bfc088c92e6b69`。
- Prepared Parquet SHA-256：`9ca63d003f082948013545f2755bb0d4dea145d94aaebbcd358cd93f40b480be`。
- Dataset snapshot：`22f6747e395b2a893ea297496558b05bd59e10751ec6a27d7d8ad3560aa88c22`。
- Feature schema：`8e256243dbe0018a7a96a637b989e2338dcf06a8f2e9a9d42faf888c7f54cd53`。
- Source hash：`18c6aac3780bea72be2ebdae2803fbe86b8a42436f60101d6412199fc11a6701`。
- Prediction snapshot：`f4fa5a50ebaa3f4820caadaf02c70525a7b6e93fd89d1fa89fbaac21cc7840d9`。
- Label：`twse-research-unadjusted-open-close-5d-v1`。
- Benchmark：`TWSE_TAIEX_PRICE_INDEX`，版本 `rwd.en.TAIEX.MI_5MINS_HIST.v1@snapshot:4c58a09fd1bbccc21416948eff8d31f77c31ba8568e2392493d0050f674c52c9`。
- Cost profile：`tw_stock_swing_v1:base_cost`。

### 最新具完整 artifact／provenance 證據的上市橫截面研究推論


<!-- release-manifest:status-snapshot:start -->
[GitHub Actions run `29701335309`](https://github.com/migao2006/tool/actions/runs/29701335309) 已使用該次已驗證特徵橫截面、最後一個 walk-forward fold 的凍結模型 bundle，完成研究推論並發布至 Production Supabase；快照 RPC 與後續 gate attachment 的既有紀錄顯示已完成不可變讀回驗證。發布 commit 未記錄於目前可用證據，因此文件不再沿用舊快照 commit。

| 項目 | 已驗證結果 |
| --- | ---: |
| Evaluation scope | `RETROSPECTIVE_RESEARCH_INFERENCE` |
| `as_of_date` | `2026-07-17` |
| `decision_at` | `2026-07-17T17:00:00+08:00` |
| 預測列數 | 1,068 |
| Supabase `prediction_run_id` | 4 |
| Model version | `twse-price-research-h5-v1` |
| Training end date | `2024-06-18` |
| 政策動作 | `CANDIDATE=0`、`WATCH=0`、`NO_TRADE=0` |
| 政策評估狀態 | `MISSING_REQUIRED_DATA=1,068`、`VALIDATION_FAILED=0`、`HARD_FAIL=0` |
| 系統狀態 | `RESEARCH_ONLY` |
| 公開 API 資料品質 | 1,068 筆 `WARN`，0 筆 hard fail |
| Industry coverage | 0／1,068 |
| Decision gate rows | 8,544；每檔固定 8 層 |

完整性核對紀錄：股票與 global rank 均無重複、排名為 1～1,068 連續整數、三分類機率總和為 1、毛／淨 P10≤P50≤P90，且 `latest_available_at <= decision_at`。Provenance：

- Feature artifact SHA-256：`24c90589d51de6b0c06f084ca977c4bfb99993f91164d65b3bad33bce3c73aac`。
- Model bundle SHA-256：`c41b76df09decf6be62da3cc59012597c7fd889d4980e43c14eb7cca70de5ca7`。
- Prediction snapshot SHA-256：`4581af6f96eb56791a498343784e484a3c604ef7c32f549ffdbbfc7dce60f505`。
- Snapshot artifact SHA-256：`605c19a53b4321e307848e4affa081c4a760601a3a0186a26192036c61395eee`。
- GitHub artifact：`8446597593`，digest `b06a8280e9780f19378f682ed4ad55ff9017fb684cbe1dd9abc953d7d9948199`。

這是回溯研究推論，不是新的 OOS 驗證。既有契約驗證紀錄顯示每檔恰好 8 層 gate；gate order、actual、threshold、reason code 與 attachment snapshot hash 均通過。具備真實輸入的資料品質、流動性容量、校準方向機率、淨分位數及排名資格會顯示實際值與門檻；缺少 point-in-time 可交易性、市場模型及部位配置輸入時一律 fail closed。舊資料庫欄位曾記錄 `NO_TRADE=1,068`；權威重分類為 `MISSING_REQUIRED_DATA=1,068` 且政策動作為空值。不得描述為正式候選股、即時交易訊號或獲利保證。
<!-- release-manifest:status-snapshot:end -->

### 2026-07-24 Production 唯讀狀態稽核

目前 Production 最新上市 `horizon=5` 為 `prediction_run_id=12`、
`as_of_date=2026-07-20`，共有 1,068 筆排名列。資料庫與公開 API 的 legacy 欄位均為
`CANDIDATE=0`、`WATCH=0`、`NO_TRADE=1,068`、hard fail 0，但沒有相同 run 的
`market_predictions` 列。

代表列 rank 1、symbol `6515` 的 Rank Score、三分類校準機率與淨 P50 均存在；八層
gate 中，formal tradability、market exposure 與 position limits 全部缺少，資料品質
只有 research `WARN`，不是完整政策評估。1,068 列全都缺少上述三類 mandatory
evidence；因此新契約的權威計數為 `NO_TRADE=0`、
`MISSING_REQUIRED_DATA=1,068`。資料庫 migration 與新版 Edge Function 尚未部署前，
正式 UI 仍可能顯示 legacy 值，不得把它描述為實際政策已決定不進場。

新契約另外要求 `EVALUATED` 必須具有 `PASS` 資料品質與完整、具來源日期的八層
gate。`CANDIDATE` 代表全部 gate 通過且入選，`WATCH` 代表全部 gate 通過但因
`OUTSIDE_TOP_K` 未入選，`NO_TRADE` 代表至少一項適用政策 gate 未通過；included
與 excluded 鍵不得重疊，excluded 只承載 `HARD_FAIL`。正式 `PASS` universe 不得
為空，但非空 universe 經完整有效評估後可如實得到 0 個正式候選。

## 三、Supplemental 回補現況

2026-07-20 Production manifest 與 task 統計：

| Dataset | Objects／rows | 任務狀態 |
| --- | ---: | --- |
| `institutional_flows` | 1,080／1,178,617 | 1,080 `SUCCEEDED` |
| `margin_short` | 1,008／1,173,917 | 1,008 `SUCCEEDED`、66 `PENDING`、6 `RETRY` |
| `adjusted_bars` | 0／0 | 1,080 `RETRY`；現有 FinMind free tier 不可用 |

法人資料已完成目前上市 campaign 的原始封存，但尚未接入本次 17 個價量特徵。融資券仍有
72 個任務未完成；`adjusted_bars` 仍沒有 Production object。不得把原始封存數量解讀為
point-in-time 或正式模型可用度。

## 四、Point-in-time 身分流程

- Production 已有 1,971 筆 `security_history` 與 1,080 筆 `security_listing_periods`。
- Current listing identity 證據仍固定為 `UNRESOLVED / RESEARCH_ONLY`，不是歷史 point-in-time 身分。
- 仍需歷史上市／下市期間、代號重用、ISIN／公司識別、產業 vintage 與來源實際發布時間證據。

## 五、目前仍屬硬性阻塞的項目

以下任何一項未解決時，都不得把模型狀態升級為 `PASS`：

1. 歷史 point-in-time security identity 尚未完成，現有特徵仍使用 current securities mapping，存在生存者偏誤與代號重用風險。
2. 交易日曆只有 2,077 筆研究觀測，尚未具備正式 session open／close、臨時休市及 decision cutoff 的可稽核歷史證據。
3. 公司行動、停復牌、處置／變更交易方法及可成交性歷史尚未完整驗證。
4. 仍有 843 筆下市觀測未解析，不能安全建立完整歷史股票池。
5. `adjusted_bars` 尚未取得；除權息、減資、分割與總報酬處理仍不足以支援正式 executable return。
6. 法人原始 archive 已完成目前上市 campaign，但尚未接入特徵；融資券尚有 72 個任務，`adjusted_bars` 仍為 0。
7. 研究資料已將股票與 TAIEX 價格指數統一為 `t+1 open → 第 5 個交易日 close`，但 TAIEX 仍是 price index、不是 total return，且整條路徑仍未完成正式 PIT／公司行動驗證。
8. Prepared artifact 與研究標籤雖已完成 hash／read-back 並實際執行 5-fold purged walk-forward，但仍是 `POINT_IN_TIME_UNVERIFIED`，且使用研究版未還原 open-close label，不是正式 LabelFactory 的 executable total-return label。
9. 研究資料已能支援這次 expanding train、calibration、test、purge 與保留 170,032 列 locked holdout；但歷史身分、公司行動與可交易性證據仍不足，不能將資料期間足夠解讀為正式 PIT coverage 足夠。
10. Purged walk-forward、溫度機率校準與分位區間校準已完成第一次真實執行；排名未優於 20 日動能基準，locked holdout 與完整 execution backtest 尚未執行。
11. 最新 1,068 筆推論沒有產業資料、point-in-time 可交易性、market model、正式 Top-K／部位配置、locked holdout 或完整 execution backtest；八層 gate 只能作 fail-closed 研究稽核，不能產生正式候選。

## 六、目前可以與不可以做的事

目前可以：

- 持續以 append-only 方式累積及稽核 R2 原始歷史資料。
- 產生具有 provenance、schema、hash 與 read-back 的研究 artifact。
- 在 UI 顯示目前 API 提供的最新上市橫截面研究排序、方向機率及條件報酬分位數；
  2026-07-24 唯讀觀測為 `as_of_date=2026-07-20`、1,068 筆。
- 保留 2025-05-02 的 672 筆歷史 OOS 驗證快照，與最新回溯研究推論分開追溯。
- 在 Staging 驗證 migration、RPC contract 與 rollback。
- 在 `RESEARCH_ONLY` 狀態下檢查資料缺漏及準備正式標籤輸入。

目前不可以：

- 顯示正式候選股或宣稱模型已可交易。
- 將 Rank Score、方向機率或分位數包裝成保證報酬。
- 將已完成的研究 OOS 結果描述為正式樣本外績效、正式候選股或即時預測。
- 以 workflow success 代替資料列數、archive 數量及 point-in-time 驗證。

## 七、下一個安全執行順序

1. 將已發布的 1,068 筆研究快照與 8,544 筆 gate 納入每日推論回歸監控；若附件缺列或 hash 不符，API 必須回傳 409 且 workflow 失敗，修復後以相同不可變 run 重試，不得顯示部分完成的 gate。
2. 補齊歷史 listing periods、代號重用、ISIN、產業 vintage 與下市解析，不得把 current snapshot 當歷史真相。
3. 完成剩餘融資券任務，建立可驗證的 adjusted price／公司行動／交易狀態來源，再把 supplemental 資料納入 fold 內特徵工程。
4. 補齊可驗證交易日曆、可成交性及 TAIEX total-return benchmark 契約，讓 tradability 與 market exposure gate 能使用正式輸入。
5. 執行並稽核已建立的上櫃獨立價量 feature workflow；之後才建立櫃買基準 R2 archive、
   5 日標籤與獨立模型。ETF 另用獨立追蹤基準、成本及模型，不與普通股混訓。
6. 建立正式 horizon=5 executable total-return labels，重新執行 purged walk-forward 並改善未通過的排名模型。
7. 研究設計、特徵與門檻凍結且排名通過基準後，才執行一次 locked holdout 與完整成本回測；未達門檻時繼續維持 `RESEARCH_ONLY` 或標示 `FAIL`。
