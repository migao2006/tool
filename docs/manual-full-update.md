# 手動完整每日更新

Repository owner 可在 GitHub Actions 的 **Manual full update** workflow 用一次
`Run workflow` 執行完整的每日市場與研究更新。這是 Production-capable 入口；只能從
`main` 啟動，不能用本機 `act`、分支 workflow 或自行串接兩個舊入口取代。

## 預設行為

三個輸入如下：

| 輸入 | 預設 | 說明 |
| --- | --- | --- |
| `dry_run` | `false` | `true` 時只執行來源驗證與 Production 現況解析，不寫入市場、Staging 或 Production。 |
| `publish_production` | `true` | `false` 時仍完成市場匯入、特徵、Staging 發布與驗證，但不發布 Production。 |
| `as_of_date` | 空白 | 空白時由既有 resolver 選擇最新已對齊且可用的市場日期；指定時必須是有效 `YYYY-MM-DD`，並通過既有 aligned-date、coverage、age 與 point-in-time 規則。 |

空白日期不是「今天」。Import 可以在執行當日向官方來源查詢，但 TWSE 與 TPEx 的來源日期
必須一致，研究日期只來自已驗證的 `home_data_status` 與 resolver。workflow 不會把日曆日期
代入 snapshot，也不會為了看起來新鮮而略過驗證。

非空 `as_of_date` 只約束既有 research resolver 的 target；Import 仍依原有契約抓取並驗證
目前官方來源，不會假裝 provider 支援歷史日期查詢。指定日必須不晚於已發布的 aligned
daily-bar date，後續 exact-date feature、point-in-time 與 publication gates 仍須全部通過。

## 完整資料流

預設執行順序固定為：

```text
Manual full update
  → Import market data（既有 retry、來源日期與 Supabase contract）
  → Daily research resolver（aligned date、missing markets）
  → exact-date current bars
  → TWSE／TPEx 隔離 feature build
  → Staging publish + verification
  → identical immutable Production publish + verification
  → fail-closed job summary
```

新入口只以 `workflow_call` 重用既有 Import 與 Daily workflows。它不實作第二套 resolver、
ranking、retry、Staging、Production 或 validation 邏輯。`horizon=5`、
`available_at <= decision_at`、TWSE／TPEx、ETF／普通股隔離、`RESEARCH_ONLY` 與
`HARD_FAIL` 契約均不變。

## No-op 與摘要

resolver 若證明兩市場最新有效 snapshot 均不早於 target，整次執行以
`NO_CHANGE_REQUIRED / ALREADY_CURRENT` 成功結束。這是有效 no-op；不會重跑模型，也不會
假稱 Production 有變更。

`Final verification and summary` 永遠執行，並從同一次 run、同一次 attempt 的下列精確
artifacts 組合證據：

- sanitized Import result：TWSE／TPEx source date；
- Daily resolution：target、aligned date、required markets 與更新前有效 snapshot；
- required market 的 Production verifier result：run、prediction count、decision-gate count。

摘要顯示 trigger SHA／branch、兩市場來源日期、resolved target／aligned date、需要更新的
市場、Production 是否改變、最終 Production 日期、prediction／八層 gate 完整度，以及
失敗或 no-op reason。缺檔、多檔、日期／市場／environment 不符、prediction coverage 不足，
或 gate count 不等於 prediction count × 8 時，summary job 失敗，不會把部分成功寫成完成。

## 並行、失敗與 recovery

- Manual wrapper 使用 `manual-full-update` concurrency group。
- 被呼叫的 Import 與 Daily 仍分別使用原有 `import-market-data` 與
  `daily-research-model` group；caller 不與 callee 共用 group，避免 reusable workflow
  自我取消。
- 因此相同匯入不會並行，Daily publication 也不會並行；跨階段仍由 exact-date、
  immutable、resolver 與 verifier 契約保持冪等。
- Recovery workflow 明確監聽 Manual wrapper。它只信任目前 `main` 的同 repository run；
  來源日期暫時不一致或由既有 artifact 證明的
  `SUPABASE_CONNECTION_ERROR` 才會請求完整 rerun。
- Manual wrapper 最多兩次 total attempts。永久、混合、缺證據、未知 stage、非 `main`
  或被新 commit 取代的失敗只建立／更新 sanitized Issue，不會無限重跑。

## 操作

1. 開啟 GitHub repository 的 **Actions**。
2. 選擇 **Manual full update**。
3. 按 **Run workflow**，branch 必須選 `main`。
4. 一般完整更新保留三個預設值後執行。
5. 等待 `Final verification and summary` 與 recovery run 都完成；以 job summary 和
   `manual-full-update-summary-<run_id>-<run_attempt>` artifact 為準。

不要因為今天日期較新就指定 `as_of_date`。只有需要重播一個已存在、且通過 resolver
驗證的精確 aligned date 時才填寫。

## Rollback

程式 rollback 是 revert 新的 manual workflow、兩個 `workflow_call` seam、summary contract
與 Manual recovery 白名單，再經 PR／CI 合併。已通過驗證的市場資料與 immutable research
snapshot 不需刪除；Publication 是 exact-date 且冪等，rollback 不應改寫歷史資料、降低
validation 或移除 `RESEARCH_ONLY`。
