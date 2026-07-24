# Decision Policy 必要證據發佈與回復

本程序只發佈 `decision-policy-required-evidence.v1` 的 transport 與 fail-closed
契約。它不會創造 tradability、市場曝險或部位上限值，也不會把現有研究快照升級為
`PASS`。所有環境在 Production 完成驗證後仍維持 `RESEARCH_ONLY`。

## 發佈前條件

- feature branch 的 Focused、Fast、Full、migration、Edge、frontend、security 與
  independent review 均通過，PR CI 為綠燈。
- 遠端 migration history 已逐筆唯讀比對；禁止盲目使用 `--include-all` 或 migration
  repair。
- `20260724085021_publish_research_market_evidence_atomically.sql` 是唯一待套用的
  本 Work Package migration，且本機 clean reset、validation snippet、權限與 rollback
  演練均通過。
- 即將使用的 evidence artifact 與 feature artifact 必須是同一市場、同一
  `as_of_date`、同一 `decision_at` 及同一不可變 workflow handoff。

## 相容部署順序

1. 部署可同時讀取 gate envelope v1/v2 的 Edge 與前端契約。
2. 在 Staging 套用三參數
   `market_data.publish_research_prediction_snapshot(jsonb,jsonb,jsonb)` migration。
3. 在 Staging 執行 `validate_research_market_evidence_publisher.sql`，確認只有
   `service_role` 可執行、候選與 market row 同交易保存、冪等與衝突拒絕均成立。
4. 以 exact-date feature universe 匯出 Production 唯讀證據，再在 Staging 執行推論；
   缺少 position producer 時，結果必須仍全部
   `MISSING_REQUIRED_DATA`、`decision=null`。
5. 驗證 Staging API 後，對 Production 重複 migration、snippet、Edge 部署及 smoke
   test。
6. Production 只重發 Staging 已驗證的不可變 snapshot；不得在 Production
   request-time 重算或改寫排名、機率、分位數、門檻或 evidence。

現有 GitHub Edge Production workflow 只允許 `main` ref。feature branch 可以完成
Staging；Production workflow 若下一步要求更新 `main`，必須停在受保護分支授權邊界，
不得繞過 ref gate 或改用未核准的直接部署。

## 回補政策

- 不進行歷史「值」回補。Production 目前沒有可證明在歷史 `decision_at` 前可用的三類
  完整證據，使用今日 identity、今日狀態、設定預設值或推測持倉都會造成偏誤。
- 可安全重發的只有已存在的 immutable ranking snapshot，加上逐列明確
  `MISSING` evidence 與原因碼；這不會使任何列變成 `EVALUATED`。
- 未來只有 exact-date、`available_at <= decision_at`、場別一致且驗證通過的
  `AVAILABLE` evidence 才能參與該次政策評估。

## Production 驗證

逐一記錄但不得輸出 secret：

- policy universe 列數，以及每個 `evaluation_status`、`action` 的計數。
- 所有非 `EVALUATED` 列 `action is null`；所有 `HARD_FAIL` 列皆非
  `CANDIDATE`。
- 至少一筆完整測試契約列與實際缺證據列的 reason、source、effective date、
  `available_at`、publication/run identity；若 Production 沒有可信完整列，明確記錄
  「無」，不得製造代表列。
- `TWSE`／`TPEX` 不混用；horizon 5 正常，其他 horizon 回
  `UNSUPPORTED_HORIZON`。
- `system_status=RESEARCH_ONLY`。
- 發佈前後依 security identity 比對 rank、Rank Score、三分類機率、P10/P50/P90、
  gate threshold、model/training identity，必須無漂移。

候選數可以是零；它不是發佈成功條件。

## 回復

1. Publisher 問題：停止新發佈；三參數函式是 additive，可讓既有兩參數 publisher
   繼續運作。必要時執行
   `supabase/snippets/rollback_research_market_evidence_publisher.sql`，只移除三參數
   overload，不刪除 prediction 或 market data。
2. Edge 問題：回復至上一個同時理解目前資料庫 status 契約的已驗證 Edge 版本。
   不得回復到會把 missing evidence 顯示成 `NO_TRADE` 的版本。
3. 資料問題：停止 publication；immutable conflict 會拒絕覆寫。保留錯誤稽核資料，
   以新的 publication/run 修正，不直接竄改既有 ranking row。
4. Security importer 問題：可停用單一場別 job；不可恢復成一個延遲場別阻擋另一個
   場別，也不可跨市場 fallback。
