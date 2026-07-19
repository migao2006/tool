# 專案現況

> 核對日期：2026-07-19（Asia/Taipei）
> 核對基準：`main` 的 `155c2df` 與本次工作分支的實際驗證結果
> 系統狀態：`RESEARCH_ONLY`

本文件只記錄已由程式、GitHub Actions、R2 稽核或 Supabase 遠端狀態證實的事實。數量是有日期的快照，不代表之後排程不會繼續增加；缺少真實資料時不得用推估值補齊。

## 一、目前能做什麼

- 前端已維持「總覽、5 日候選、個股詳情、自選股」四頁結構，底部只有三個主要入口。
- Supabase Email＋密碼 Auth、session 恢復與自選股 UI 已存在；prediction／watchlist backend 與自選股持久化尚未上線。
- 每小時歷史日線回補可由三組隔離的 FinMind credential worker 並行執行，原始資料存入 private Cloudflare R2。
- R2 日線 manifest、完整性讀取器、全量稽核及首頁資料累積摘要已建立。
- TAIEX 歷史總報酬基準、補充資料、歷史事件證據、上市價量特徵及研究模型 runner 的程式與測試已合併。
- 第一版研究 runner 已包含 LambdaRank、方向三分類、分位數模型及基準比較介面，但尚未以符合正式 point-in-time 契約的真實資料執行。

以上完成項目不等於已產生正式模型、候選股或回測績效。

## 二、真實資料快照

2026-07-19 的 R2 全量完整性稽核結果：

| 市場 | 資產類型 | Object | 股票代號 | 資料列 |
| --- | --- | ---: | ---: | ---: |
| TWSE | COMMON_STOCK | 1,080 | 1,080 | 1,205,606 |
| TPEX | COMMON_STOCK | 891 | 891 | 978,311 |
| 合計 | COMMON_STOCK | 1,971 | 1,971 | 2,183,917 |

總封存大小為 295,007,049 bytes。GitHub Actions run `29677606085` 已逐一驗證全部 manifest 與 Parquet object，結果為 `integrity_status=PASS`。

這個 `PASS` 只證明 Supabase manifest 與 R2 Parquet 一致，不證明歷史股票池、身分、公司行動、交易狀態或當時可取得時間正確。資料仍為：

- `point_in_time_status=UNVERIFIED`
- `usage_scope=RAW_LANDING_ONLY`
- `system_status=RESEARCH_ONLY`
- `canonicalization_status=BLOCKED`
- `dataset_build_ready=false`

- R2 日線日期範圍為 2021-07-19～2026-07-17。
- Production R2 manifest 目前只有 `daily_bars`，尚無 supplemental 或 historical benchmark dataset。
- 目前快照沒有 ETF R2 日線 object。
- 目前 security master 有 TWSE 1,080 檔、TPEX 891 檔；ISIN 與 `security_history` 均為 0。兩個市場目前排程中的普通股日線均已完成既定 campaign。
- TWSE 與 TPEX 數量是目前排程股票池，不得解讀為完整的 point-in-time 歷史股票池。
- `trading_calendar` 有 2,077 筆 TWSE 日期（2018-01-02～2026-07-17），但開盤、收盤與 decision cutoff 仍全部缺漏。
- 官方下市觀測共 843 筆（TWSE 264、TPEX 579），目前全部 `UNRESOLVED`。
- 模型、feature snapshot、prediction、validation 與 backtest 正式資料表目前均為 0 筆。
- Supabase 保存 queue、manifest、稽核 metadata 與前端摘要，不重複保存 R2 的全量原始列。

## 三、工作流程狀態

| 流程 | 現況 | 正式用途 |
| --- | --- | --- |
| 歷史日線回補 | 既定 campaign 的 1,971 個任務均已成功；無 pending、running、retry 或 exhausted | 只累積 raw archive |
| R2 全量稽核 | run `29677606085` 成功，全部 1,971 objects 通過 object／manifest 完整性驗證 | 不代表 PIT 或模型驗收 |
| 歷史交易日曆 | 本次分支新增 append-only observation；日期提示固定為 `UNRESOLVED / CALENDAR_RESEARCH_ONLY` | 缺正式開盤、收盤與 cutoff |
| TWSE current listing identity | 真實 dry-run 取得 1,090 列，正規化為 1,080 檔普通股 | 只有當前掛牌證據，不是歷史 PIT 身分 |
| 官方下市名冊 | 已排程保存首次觀察版本 | `RESEARCH_ONLY`，身分未解析 |
| TAIEX 歷史基準 | 程式與 workflow 已合併，尚無 workflow run | 未啟用正式回補 |
| 還原行情／法人／融資券 | 程式與 workflow 已合併，尚無 workflow run | 未啟用正式回補 |
| 公司行動／停牌歷史證據 | 程式與 workflow 已合併，尚無 workflow run | 受 verified identity gate 阻擋 |
| 上市價量 feature artifact | 本次分支加入 typed manifest、read-back、schema／snapshot／SHA-256 驗證 | 尚無 Production artifact，只允許 `FEATURE_RESEARCH_ONLY` |
| 研究資料組裝與模型 runner | 程式與單元測試已建立 | 尚無正式 artifact；execution backtest 尚未完成 |

四個新流程使用 GitHub Repository Variables 作 feature gate。未完成非正式環境 migration 驗證與資料契約前，不得開啟後宣稱正式可用。

目前歷史 campaign 的結束日固定為 2026-07-17。完成既有 queue 後，R2 不會因此自動新增之後的交易日；平日 current import 只保存 Supabase 近期資料。長期累積仍需建立冪等、可稽核的 R2 daily delta workflow。

## 四、Supabase 狀態

- 已建立獨立的 Supabase Free Staging 專案 `alpha-lens-staging`，project ref 為 `kretvnnfavndkmckyidl`。這是每月 $0 的獨立專案，不是需要 Pro 的 Supabase Branch。
- Staging migration history 與本機完全一致，共 26／26 筆 migration。
- 已先把 Staging 回復至 Production 現行 head，再匯入具代表性的 Production TWSE／TPEX、任務及 archive manifest 資料，最後套用 12 筆待發布 migration；資料保留與 constraint 驗證均成功。
- 已完成最後一筆 migration 的 down／up rollback 演練；舊 constraint 正確拒絕 date-only hint，重新套用後只允許 `UNRESOLVED／CONFLICT` 的研究日期提示。
- Staging `db lint --linked --level error` 為 0 個 schema error；advisor 沒有 WARNING 或 ERROR。
- Production 完全未變更。Production migration history 仍為 13 筆，head 為 `20260718191828_optimize_historical_backfill_snapshot`。
- Production 尚有 12 筆 forward migration 待發布，從 `20260719044435_expand_historical_supplemental_archives` 到 `20260719065502_allow_research_calendar_date_hints`。
- `20260717180000_initial_market_data_baseline` 已存在本機與 Staging，但 Production migration history 沒有此版本。正式發布前仍須先完成 migration history 對齊，不得直接使用 `--include-all`。
- Production 代表性資料對新 constraint 的唯讀 preflight 為 0 個 task violations、0 個 archive violations。
- 目前本機 Supabase CLI linked project 是 Staging，不是 Production。

因此，Production 尚未套用 migration，資料工作流程 feature gate 仍保持關閉。

## 五、程式與驗證證據

- PR #20 已合併：`feat: add TWSE five-day research data pipeline`。
- 合併提交：`d32c3de47f7c119f1d9e231851cd5697fb3696ca`。
- Python：634 tests passed。
- Ruff（本次變更範圍）：通過。
- basedpyright（受影響 production files）：0 errors、0 warnings。
- Playwright iPhone viewport：9 tests passed。
- actionlint：通過。
- SQLFluff（PostgreSQL）：通過。
- Gitleaks：未發現本次提交機密。
- 合併後 GitHub Actions：Project tests、API readiness、Import market data、GitHub Pages 均成功。

上述是程式與契約測試，不是模型樣本外績效。

## 六、正式訓練前仍缺少的條件

1. 目前新增的是 current listing 身分證據，仍缺歷史 ISIN、代號重用、完整 listing period 與 verified identity catalog。
2. 交易日曆目前只有日期提示；verified 開盤、收盤與 decision cutoff coverage 仍為 0。
3. Verified security state 與 company action coverage 仍不可用。
4. 未解析下市觀測仍有 843 筆。
5. 個股路徑為 `t+1 open → 第 5 個持有交易日 close`，目前 TAIEX archive 設計為 close-only，兩者尚未形成一致、可執行的 alpha 路徑。
6. Production R2 仍只有 `daily_bars`；adjusted bars、法人、融資券及 benchmark 尚無正式 object。
7. Feature artifact 的 typed manifest 與 hash 驗證已在程式完成，但尚未產生及驗證真實 Production artifact。
8. 目前約五年資料不足以直接滿足既定 expanding train、calibration、test 與 locked holdout 組合；現行正式規格約需 6.8 年。
9. 尚未完成正式 LabelFactory 接線、execution simulator、purged walk-forward、獨立 calibration、locked holdout 與完整成本回測。

在這些條件完成前：

- 不發布 `CANDIDATE` 正式推薦。
- 不顯示虛構 Rank Score、機率、分位數或報酬。
- 不把單元測試、原始資料完整性或研究 runner 輸出稱為正式績效。

## 七、下一步順序

1. 將本次變更提交 GitHub，等待 CI 與 required checks 全部通過。
2. 對齊 Production baseline migration history，再以 dry run 確認 12 筆 forward migration 的發布範圍。
3. 發布 Production migration 後，逐一開啟 benchmark 與 supplemental feature gate，監控 R2 object、queue 與 quota。
4. 產生並 read-back 驗證第一個真實 TWSE feature artifact；結果仍維持 `RESEARCH_ONLY`。
5. 補齊 verified PIT 身分、交易日曆、公司行動與交易狀態，並對齊個股與 TAIEX 的可執行路徑。
6. 完成正式 5 日標籤、purged walk-forward 與成本回測；未達門檻時維持 `RESEARCH_ONLY` 或 `FAIL`。
