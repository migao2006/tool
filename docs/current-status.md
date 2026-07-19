# 目前實作與阻塞狀態

> 更新日期：2026-07-19（Asia/Taipei）
>
> 正式 `main` 基準：`0bd4959`
>
> 系統狀態：`RESEARCH_ONLY`

本文件只記錄已由實際 workflow、資料庫、artifact 或稽核結果證實的現況。資料管線雖已能持續累積原始行情並產生研究特徵，但尚未滿足正式 5 日模型所需的 point-in-time、標籤、walk-forward 與成本回測條件，因此不得產生正式 `CANDIDATE` 或把研究產物描述為正式推薦。

## 一、環境與 Migration

### Supabase Staging

- 已建立每月費用為 `$0` 的獨立 Staging 專案 `alpha-lens-staging`。
- Project ref：`kretvnnfavndkmckyidl`。
- 專案狀態：`ACTIVE_HEALTHY`。
- Staging 已完成 database reset，並套用 28 個 migrations。
- 最新 migration 為
  `20260719090300_allow_late_retrieval_for_current_security_snapshot.sql`。
- 新約束已實測允許來源日期後才取得的快照，仍拒絕未來快照日期，且驗證資料無殘留。
- `supabase db lint --linked --level error`：0 個 schema error。
- Supplemental task transaction RPC contract：`PASS`。
- Staging 只用於隔離驗證；它不是 Supabase Pro Branching，也不是 Production。

### Supabase Production

- Production 目前有 27 個 migrations，既有 migration history 已對齊至
  `20260719081157_defer_unavailable_supplemental_datasets.sql`。
- `20260719090300_allow_late_retrieval_for_current_security_snapshot.sql`
  尚未套用至 Production，需先通過 GitHub 發布閘門。

### 本機隔離環境

- Docker Engine `29.6.1`、Docker Compose `5.3.0` 與 Docker Desktop 已驗證可用。
- Supabase Local 已用 Docker 完整重建 28 個 migrations。
- 新 security snapshot 約束、rollback 及 `supabase db lint` 已實際通過。

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

GitHub Actions run `29679038238`：

| 項目 | 已驗證結果 |
| --- | ---: |
| 執行狀態 | success |
| Feature rows | 1,138,336 |
| Symbols | 1,071 |
| 日期範圍 | 2021-10-14 至 2026-07-17 |
| Artifact bytes | 172,563,841 |
| Hash／read-back | PASS |

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

## 三、Supplemental 回補現況

GitHub Actions run `29678861850`：

- Workflow 技術狀態為 success。
- 本輪 archived objects／rows 為 0；不得把 workflow success 解讀為資料回補成功。
- `adjusted_bars` 因 FinMind free tier 回傳 HTTP 400，未取得可封存資料。Fugle capability
  probe 已確認 `adjusted=true` 可取得不同於 raw 的序列；正式 backfill 仍須先部署獨立
  migration 並明確開啟兩道 feature gate，目前 Production manifest 仍為 0。
- 對 unavailable dataset 的 defer／分類程式修正已在分支完成，但尚未正式發布。
- 法人資料與融資券資料尚待修正發布後重新執行及驗證。

目前不得宣稱 adjusted bars、法人或融資券歷史資料已補齊。

## 四、Point-in-time 身分流程

- Current listing identity workflow 在週日執行時失敗。
- 失敗流程已在分支修正，但尚未合併發布，也尚未完成正式重跑。
- 即使重跑成功，current listing snapshot 仍不等於歷史 point-in-time 身分；仍需歷史上市／下市期間、代號重用、ISIN／公司識別與來源時間證據。

## 五、目前仍屬硬性阻塞的項目

以下任何一項未解決時，都不得把模型狀態升級為 `PASS`：

1. 歷史 point-in-time security identity 尚未完成，現有特徵仍使用 current securities mapping，存在生存者偏誤與代號重用風險。
2. 交易日曆只有 2,077 筆研究觀測，尚未具備正式 session open／close、臨時休市及 decision cutoff 的可稽核歷史證據。
3. 公司行動、停復牌、處置／變更交易方法及可成交性歷史尚未完整驗證。
4. 仍有 843 筆下市觀測未解析，不能安全建立完整歷史股票池。
5. `adjusted_bars` 尚未取得；除權息、減資、分割與總報酬處理仍不足以支援正式 executable return。
6. 法人及融資券 supplemental archives 尚未成功回補與驗證。
7. TAIEX benchmark 與股票尚未統一為相同進出場路徑，不能產生正式可比較的 5 日 alpha label。
8. Feature artifact 雖通過 hash／read-back，但仍是 `POINT_IN_TIME_UNVERIFIED`，且 labels 尚未組裝。
9. 目前特徵範圍從 2021-10-14 起，不足以同時穩健容納至少 5 年 expanding train、calibration／validation、test、purge 與最後 12 個月 locked holdout。
10. 尚未完成正式 LabelFactory 組裝、purged walk-forward、機率／區間校準、locked holdout 與含完整成本的 execution backtest。
11. Production 尚未套用 migration `20260719081157`，Supplemental 修正與 identity workflow 修正也尚未正式發布及重跑。

## 六、目前可以與不可以做的事

目前可以：

- 持續以 append-only 方式累積及稽核 R2 原始歷史資料。
- 產生具有 provenance、schema、hash 與 read-back 的研究 artifact。
- 在 Staging 驗證 migration、RPC contract 與 rollback。
- 在 `RESEARCH_ONLY` 狀態下檢查資料缺漏及準備正式標籤輸入。

目前不可以：

- 顯示正式候選股或宣稱模型已可交易。
- 將 Rank Score、方向機率或分位數包裝成保證報酬。
- 使用目前 feature artifact 直接訓練並宣稱得到正式樣本外績效。
- 以 workflow success 代替資料列數、archive 數量及 point-in-time 驗證。

## 七、下一個安全執行順序

1. 合併並由 GitHub 發布 supplemental defer migration 與 workflow 修正，確認 Production migration history 後再套用。
2. 正式重跑 current identity workflow，保留失敗與來源時間稽核；同時繼續補歷史 listing periods，而非把 current snapshot 當歷史真相。
3. 重跑法人與融資券 supplemental backfill；對 free tier 不可用的 `adjusted_bars` 保持明確 unavailable，不得無限重試或造資料。
4. 補齊公司行動、交易狀態、下市解析及可驗證交易日曆。
5. 將股票與 TAIEX 對齊相同交易路徑後，才建立正式 horizon=5 labels。
6. 完成 purged walk-forward、calibration、locked holdout 與完整成本回測；未達門檻時繼續維持 `RESEARCH_ONLY` 或標示 `FAIL`。
