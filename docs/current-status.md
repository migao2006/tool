# 專案現況

> 核對日期：2026-07-19（Asia/Taipei）
> 核對基準：`main` 的 `d32c3de47f7c119f1d9e231851cd5697fb3696ca`
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

| 市場 | 資產類型 | Object | 股票代號 | 資料列 | Byte |
| --- | --- | ---: | ---: | ---: | ---: |
| TWSE | COMMON_STOCK | 1,080 | 1,080 | 1,205,606 | 163,303,656 |
| TPEX | COMMON_STOCK | 607 | 607 | 735,782 | 98,253,575 |
| 合計 | COMMON_STOCK | 1,687 | 1,687 | 1,941,388 | 261,557,231 |

這些資料全部仍為 `UNVERIFIED / RAW_LANDING_ONLY / RESEARCH_ONLY`。完整性 `PASS` 只證明 Supabase manifest 與 R2 Parquet 一致，不證明歷史股票池、身分、公司行動、交易狀態或當時可取得時間正確。

- R2 日線日期範圍為 2021-07-19～2026-07-17。
- Production R2 manifest 目前只有 `daily_bars`，尚無 supplemental 或 historical benchmark dataset。
- 目前快照沒有 ETF R2 日線 object。
- 目前 security master 有 TWSE 1,080 檔、TPEX 891 檔；ISIN 與 `security_history` 均為 0。TWSE 目前排程的 1,080 檔已封存；TPEX 有 607 檔封存、284 檔仍待回補。
- TWSE 與 TPEX 數量是目前排程股票池，不得解讀為完整的 point-in-time 歷史股票池。
- `trading_calendar` 有 2,077 筆 TWSE 日期（2018-01-02～2026-07-17），但開盤、收盤與 decision cutoff 仍全部缺漏。
- 官方下市觀測共 843 筆（TWSE 264、TPEX 579），目前全部 `UNRESOLVED`。
- 模型、feature snapshot、prediction、validation 與 backtest 正式資料表目前均為 0 筆。
- Supabase 保存 queue、manifest、稽核 metadata 與前端摘要，不重複保存 R2 的全量原始列。

## 三、工作流程狀態

| 流程 | 現況 | 正式用途 |
| --- | --- | --- |
| 歷史日線回補 | 已排程；三組 credential、每組每輪最多 100 檔 | 只累積 raw archive |
| R2 全量稽核 | 已建立每日與手動流程 | 只驗證 object／manifest 完整性 |
| 歷史交易日曆 | 已排程保存 FinMind 實際交易日期 | `RESEARCH_ONLY`，缺開收盤與 cutoff |
| 官方下市名冊 | 已排程保存首次觀察版本 | `RESEARCH_ONLY`，身分未解析 |
| TAIEX 歷史基準 | 程式與 workflow 已合併，尚無 workflow run | 未啟用正式回補 |
| 還原行情／法人／融資券 | 程式與 workflow 已合併，尚無 workflow run | 未啟用正式回補 |
| 公司行動／停牌歷史證據 | 程式與 workflow 已合併，尚無 workflow run | 受 verified identity gate 阻擋 |
| 上市價量 feature artifact | 程式與 workflow 已合併，尚無 workflow run | 只允許 `FEATURE_RESEARCH_ONLY` |
| 研究資料組裝與模型 runner | 程式與單元測試已建立 | 尚無端到端排程、真實績效或模型 artifact |

四個新流程使用 GitHub Repository Variables 作 feature gate。未完成非正式環境 migration 驗證與資料契約前，不得開啟後宣稱正式可用。

目前歷史 campaign 的結束日固定為 2026-07-17。完成既有 queue 後，R2 不會因此自動新增之後的交易日；平日 current import 只保存 Supabase 近期資料。長期累積仍需建立冪等、可稽核的 R2 daily delta workflow。

## 四、Supabase 狀態

- 遠端 Production migration history 已核對至 `20260718191828_optimize_historical_backfill_snapshot`，共 13 筆。
- 本機另有 11 筆較新的 forward migration，從 `20260719044435_expand_historical_supplemental_archives` 到 `20260719062000_historical_benchmark_archive`，尚未套用 Production。
- `20260717180000_initial_market_data_baseline` 供空資料庫重建；遠端 history 沒有此版本。未完成 schema 等價稽核前不得直接 `db push`、`--include-all` 或盲目 migration repair。
- Supabase CLI `2.109.1` 已完成本機 migration chain 重建；本機 `db lint` 為 0 個 schema error。
- 尚未建立並驗證 Supabase Staging branch，也尚未為上述 11 筆 migration 完成代表性資料與 rollback 演練。

因此，本文件更新不會套用任何 Production migration，也不會開啟資料工作流程 feature gate。

## 五、程式與驗證證據

- PR #20 已合併：`feat: add TWSE five-day research data pipeline`。
- 合併提交：`d32c3de47f7c119f1d9e231851cd5697fb3696ca`。
- Python：592 tests passed。
- Ruff：通過。
- basedpyright（受影響 production files）：0 errors、0 warnings。
- Playwright iPhone viewport：9 tests passed。
- actionlint：通過。
- SQLFluff（PostgreSQL）：通過。
- Gitleaks：未發現本次提交機密。
- 合併後 GitHub Actions：Project tests、API readiness、Import market data、GitHub Pages 均成功。

上述是程式與契約測試，不是模型樣本外績效。

## 六、正式訓練前仍缺少的條件

1. 可稽核的歷史掛牌身分、ISIN、代號重用與 listing period。
2. 具有版本與來源 hash 的交易日曆證據，以及可驗證的開盤、收盤與決策 cutoff。
3. 公司行動完整 coverage 與歷史停牌、處置、變更交易方法、全額交割、分盤狀態。
4. 個股 `t+1 open → 第 5 個持有交易日 close` 與 close-only 指數基準之間一致、經驗證的 alpha 路徑。
5. Feature／benchmark artifact metadata、manifest 與資料組裝器之間的強制 hash／provenance 綁定；目前部分來源聲明仍由 caller 傳入。
6. Raw → feature → label → runner 的單一可續跑、自動化研究流程。
7. Supabase queue 的成功游標與 `EXHAUSTED`／完成狀態語意修正。
8. 真實 purged walk-forward、獨立 calibration、locked holdout 與完整成本回測。

在這些條件完成前：

- 不發布 `CANDIDATE` 正式推薦。
- 不顯示虛構 Rank Score、機率、分位數或報酬。
- 不把單元測試、原始資料完整性或研究 runner 輸出稱為正式績效。

## 七、下一步順序

1. 在隔離環境驗證 11 筆 Supabase migration、代表性資料與 rollback。
2. 完成 TWSE point-in-time 身分、交易日曆與公司行動／交易狀態證據 adapter。
3. 將 R2 feature 與 benchmark artifact 改為由 metadata／manifest 自動衍生 provenance，拒絕 caller 任意聲明。
4. 建立 feature-gated 的端到端研究 workflow。
5. 對齊正式標籤與市場基準路徑，再執行第一輪真實 purged walk-forward。
6. 只有通過驗收才讓 UI 顯示正式候選；否則維持 `RESEARCH_ONLY` 或 `FAIL`。
