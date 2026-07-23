# Characterize Current-Identity Formal Promotion Boundary

## Status

COMPLETE

## Primary Boundary Conclusion

FAIL_CLOSED_BY_CURRENT_CODE

在本次限定的第一方 repository caller、workflow、CLI、artifact contract、decision adapter 與 publisher 路徑內，沒有找到可把以 current-only security identity 建出的 `FEATURE_RESEARCH_ONLY` 或 `POINT_IN_TIME_UNVERIFIED` artifact，提升成正式 `PASS`、`CANDIDATE`、`production_eligible` 或正式發布結果的可達路徑。

這個結論只涵蓋已檢查的 repository 內第一方路徑；它不是對未檢查的 production 資料、遠端部署狀態、外部自訂 runner、未來程式變更或 repository 外呼叫者的安全證明。

## Repository 狀態

- Root：`C:/Users/a0912/Documents/Codex/2026-07-22/agents-md-tasks-active-task-md`
- Branch：`main`
- HEAD：`ce9bbd0edf3a08411f9571946e76bac0ba93a9a9`
- Latest commit：`ce9bbd0 refactor(data): extract daily-bar publication contracts`
- `origin/main` relationship：behind 0、ahead 1；`git rev-list --left-right --count origin/main...HEAD` 為 `0 1`。
- 初始 staging 與 tracked working tree 乾淨。
- 初始唯一 untracked path：`tasks/completed/2026-07-22-inventory-reconstruction-targets-and-known-bugs.md`。
- 既有 inventory 報告初始 SHA-256：`52DFB8B2B932AC1D7D9DCF33DD528B33EE8A4B2781A74E7CE9C2E52167B6DA8B`。
- Preflight 後才建立本 ACTIVE task；開始時 `tasks/active/TASK.md` 精確為 approved NONE，未發現另一個 ACTIVE task。
- 最終 staging 與 tracked working tree 乾淨；`tasks/active/TASK.md` 已與 HEAD 的 approved NONE 內容一致。
- 最終 `git status --short --branch` 只有本報告與先前 inventory 報告兩個 untracked paths；branch仍為ahead 1。
- 既有 inventory 報告最終 SHA-256仍為 `52DFB8B2B932AC1D7D9DCF33DD528B33EE8A4B2781A74E7CE9C2E52167B6DA8B`，與初始值相同。

## 單一分析目標

由 current identity 衍生、狀態為 `FEATURE_RESEARCH_ONLY` 或 `POINT_IN_TIME_UNVERIFIED` 的 artifact，是否能繞過 historical-identity、point-in-time、system-status 與 formal-promotion controls，成為正式 candidate 或正式 publication result？

範圍只涵蓋上述 boundary；horizon、market、rank、`HARD_FAIL`、`NO_TRADE` 與 product safety 只在同一 promotion path 中直接相關時納入。

## 已檢查證據

- Instructions：`AGENTS.md`、`.ai/architecture.md`、`.ai/product.md`、`.ai/decisions.md`、`.ai/code-review.md`、`.ai/known-issues.md`、`tasks/README.md`、`tasks/TASK_TEMPLATE.md`、初始 active task 與既有 inventory 報告。
- 起始 producers：`src/data/research/current_identity_repository.py`、`src/data/research/archive_feature_builder.py`、`src/data/research/archive_feature_rows.py`。
- 下列 graph 所列 direct callers、consumers、contracts、CLI、workflows、publishers、SQL RPC 與 API status boundary。
- Bounded searches：`CurrentIdentity`、`current_identity`、`POINT_IN_TIME_UNVERIFIED`、`FEATURE_RESEARCH_ONLY`、`RESEARCH_ONLY`、`NO_TRADE`、`PASS`、`CANDIDATE`、`HARD_FAIL`、`production_eligible`、`available_at`、`decision_at`、`historical_identity`、`survivorship`。
- Dynamic loading search：`importlib|__import__|pkgutil|entry_points|globals\(|getattr\(`，限定 `src scripts .github`。
- Tests 只作既有 contract 行為旁證；未把測試人工輸入視為 production caller。

## Producer-to-formal-output 路徑

1. **Current identity acquisition**：`CurrentIdentityRepository.fetch` 從目前 `securities` 依 market 與 `COMMON_STOCK` 產生 snapshot；class 明示它不是 historical listing master（`src/data/research/current_identity_repository.py:50-51,68-120`）。Venue wrappers 在 `twse_current_identity_repository.py:6-8` 與 `tpex_current_identity_repository.py:11-13`。Direct caller 是 `scripts/_build_venue_research_feature_dataset.py:68-129`，由 TWSE/TPEX CLI factories（各自 `scripts/build_*_research_feature_dataset.py:44-65`）注入。

2. **Historical feature-universe filtering**：`ArchiveFeatureDatasetBuilder.build` 以 current identity listing period 過濾 archive rows；缺 identity 或 listing date 不涵蓋交易日即排除（`src/data/research/archive_feature_builder.py:125-180`）。這一步沒有把 current identity 變成 historical verification；survivorship limitation 仍在。

3. **Archive feature construction**：`canonical_feature_record` 與 current-publication peer 固定 `point_in_time_status=UNVERIFIED`（`src/data/research/archive_feature_rows.py:125-205`）。Output row 只容許非 hard fail，固定 `FEATURE_RESEARCH_ONLY`、`RESEARCH_ONLY`、labels 未組裝（`:208-300`）。Builder 排除 `HARD_FAIL`、要求 provenance、空集合失敗，成功才 finish，錯誤 abort（`archive_feature_builder.py:223-305`）。

4. **Feature artifact assignment/read-back**：`FeatureArtifactManifest` 只接受 h=5、`FEATURE_RESEARCH_ONLY`、`RESEARCH_ONLY`、`POINT_IN_TIME_UNVERIFIED`，mapping 沒有 status 的隱式 default（`src/data/research/feature_artifact_contracts.py:49-152`）；`VerifiedFeatureArtifact.point_in_time_verified` 永遠 false（`:155-203`）。Reader 重驗 metadata/schema/rows 並重建 unverified manifest（`feature_artifact_reader.py:93-159`）；Parquet metadata也固定 research（`archive_feature_parquet.py:81-104`）。

5. **Prepared dataset**：feature adapter要求 opaque verified artifact，但 feature PIT flag硬編碼 false（`twse_feature_artifact_input.py:30-98`）。TWSE/TPEX builders只接受 h=5，audit固定 `COMPLETED_RESEARCH_ONLY`、`MODEL_RESEARCH_ONLY`、`RESEARCH_ONLY`，historical identity、corporate action、feature availability verification flags全為 false（`twse_research_dataset_build.py:96-204`；`tpex_research_dataset_build.py:50-101`）。Row assembler把 PIT/security/action 缺口寫成理由，任何理由排除該列（`twse_research_row_assembler.py:92-149,248-250,324-385`）。Dataset contract要求 `available_at <= decision_at`、非 hard fail、PASS/WARN quality與 exact research scope/status（`research_dataset.py:126-227`）。Prepared manifest/repository再次要求 exact research audit與 read-back（`twse_prepared_research_contracts.py:136-234`；`twse_prepared_research_repository.py:54-214`）。

6. **Model training/artifact**：default config為 `RESEARCH_ONLY`（`config/five_day_mvp.toml:3`）。Orchestrator先 audit/provenance，再用 status cap禁止結果高於設定；只有仍為 PASS才執行 formal promotion audit（`src/modeling/pipeline/orchestrator.py:35-211`；`status_policy.py:10-29`）。現行 `VenuePriceResearchRunner._result` 永遠回 `PipelineStatus.RESEARCH_ONLY`（`venue_price_research_runner.py:281-312`）。Bundle contract固定 research、`locked_holdout_passed=False`並拒絕 promotion（`twse_research_model_bundle_contracts.py:98-194`）。Formal promotion contract本身要求 data、locked holdout、rank/cost/provenance與 exact PASS（`promotion.py:14-35,108-209`），current research chain到不了它。

7. **Prediction/inference**：`VenueLatestFeatureRepository` 要求 verified artifact、h=5、market/ordinary stock、非 hard fail，並檢查 availability（`venue_latest_feature_repository.py:101-209`）。Daily inference只使用 model `rank`排序（`twse_research_daily_inference.py:247-261`），保留 PIT failure reasons（`:317-373`）；snapshot固定 `system_status=RESEARCH_ONLY`、locked holdout false、formal policy false並要求相關理由（`:375-424`）。

8. **Decision/candidate**：`TwseResearchDecisionPolicyAdapter` 雖可內部呼叫 formal policy取得暫態結果，對外永遠建構 `Decision.NO_TRADE` 並加入 `RESEARCH_ONLY_DECISION_POLICY_NO_CANDIDATE`；正式輸入缺失也 fail closed（`twse_research_decision_policy_adapter.py:101-230`）。Research result contract明確拒絕 `CANDIDATE`（`twse_research_decision_contracts.py:58-85`）。Prediction contract在有 gate reason時序列化為 `NO_TRADE`（`twse_research_prediction_contracts.py:46-200`）。

9. **Publication/release**：writer只寫 contract-valid snapshot並 read-back驗 hash（`twse_research_snapshot_writer.py:22-54`）。Supabase payload只接受 exact research status、h=5、正確 market/hash/timestamps，run counts固定 candidate/watch/hard-fail為0、全部 no-trade，stock decision固定 `NO_TRADE`（`twse_research_prediction_supabase_payload.py:139-339`）。Publisher要求 environment/production gates，但只呼叫 research RPC（`twse_research_prediction_supabase.py:97-194`）；gate payload拒絕非 `NO_TRADE`（`twse_research_decision_gate_payload.py:15-64`）。DB RPC再要求 exact research、availability、零 candidates與全 NO_TRADE（`supabase/migrations/20260720061143_scope_prediction_runs_by_market.sql:169-415`）。Edge formal status另需 linked PASS validation、locked holdout、無 hard fail、market與完整 dated gates；research來源保持research（`supabase/functions/prediction-snapshot/snapshot.ts:138-163,185-370`）。

10. **Workflow/CLI entry points**：feature workflows呼叫上述venue CLIs（`.github/workflows/build-twse-research-feature-dataset.yml:60-80`及TPEX peer同範圍）。Daily workflow以market case硬編碼TWSE/TPEX research modules（`.github/workflows/daily-research-model.yml:203-227`）；staging建置/驗證後，production job下載同一snapshot，只呼叫 `scripts.publish_stored_research_snapshot`（`:238-548`）。Stored publisher重驗hash、market/date、h=5與exact research，輸出status仍research（`scripts/publish_stored_research_snapshot.py:50-133`）。手動latest/OOS workflows也回到相同research scripts；沒有找到第二個第一方formal publisher。

11. **獨立 canonical formal path**：`HistoricalSecurityResolver.resolve` 要求日期涵蓋的 `ListingPeriodIdentity`、identity availability、唯一verified identity、market、PIT/usage/PASS（`src/data/canonical/historical_security_resolver.py:48-110`）。`CanonicalDailyBarPromotionService` 只有 resolver、raw/row PIT、retrieval、calendar、company action與bar date全部無理由才production eligible（`daily_bar_promotion.py:83-215`）；contract再次要求verified/model/pass/no reasons/availability與完整證據（`canonical/contracts.py:168-191`）。搜尋只找到tests與exports，沒有current research graph的第一方runtime caller；它使用不同historical identity type。

## Stage Analysis Table

| Stage / exact symbol | Input status/type | Output status/type | Required guards；failure/reason；mode | Direct caller -> next consumer | Current identity；formal promotion | Evidence |
|---|---|---|---|---|---|---|
| `CurrentIdentityRepository.fetch` | current securities | `CurrentIdentitySnapshot` | market/common stock；query failure；fail-closed exception | venue feature CLI -> archive builder | current-only=yes；formal=no | `current_identity_repository.py:50-51,68-120` |
| `ArchiveFeatureDatasetBuilder.build` | archive+current identity | filtered feature records | nonempty inputs/current listing filter/provenance；missing identity excluded、empty error；fail-closed | venue CLI -> row converter/writer | yes；no | `archive_feature_builder.py:52-83,125-180,223-305` |
| `canonical_feature_record` / `archive_feature_output_row` | filtered history | unverified research row | non-hard-fail；PIT unverified/research reasons；fail-closed toward formal | builder -> Parquet | yes；no | `archive_feature_rows.py:125-164,208-300` |
| `FeatureArtifactManifest` + reader | Parquet/metadata | integrity-verified artifact, PIT false | h5/exact scope/status/PIT/schema/hash；validation error；fail-closed | feature CLI -> prepared builder | yes；no | contracts `:49-203`; reader `:93-159` |
| TWSE/TPEX research dataset builders | verified research feature | prepared research audit/dataset | h5/market/nonempty；research audit reasons；fail-closed | prepared CLI -> prepared repository | provenance yes；no | TWSE `:96-204`; TPEX `:50-101` |
| row assembler + research dataset contracts | source rows | excluded row or WARN research row | PIT/scheduling/availability/non-hard-fail；reasons exclude；fail-closed | dataset builder -> prepared artifact | yes；no | assembler `:92-149,248-250,324-385`; dataset `:126-227` |
| `VenuePriceResearchRunner.train/_result` | prepared research | research bundle/result | verified prepared/provenance；locked holdout/model-not-promoted reasons；fail-closed | model CLI -> bundle reader/inference | provenance yes；no | runner `:46-217,281-312`; bundle publisher `:99-134` |
| `run_pipeline` / `cap_result_status` | runner result+config | capped status | config cap/audit/promotion checks；failure->FAIL；fail-closed | generic CLI -> promotion or research result | current runner stays research；no | orchestrator `:35-211`; policy `:10-29` |
| latest feature repository + inference | feature+bundle | research prediction/snapshot | h5/market/common/non-hard-fail/availability；gate reasons；fail-closed | daily scripts -> decision adapter | yes；no | repository `:101-209`; inference `:247-424` |
| `TwseResearchDecisionPolicyAdapter.evaluate` | research prediction/formal transient result | `NO_TRADE` result | missing formal inputs/research boundary；no-candidate reason；fail-closed | inference -> decision contract/publisher | yes；no | adapter `:101-230`; result `:58-85` |
| Supabase payload/publisher | verified research snapshot | research RPC payload | exact research/h5/hash/date/market/all no-trade；reject/no RPC；fail-closed | stored/daily scripts -> research RPC | provenance yes；no | payload `:139-339`; publisher `:97-194` |
| SQL RPC + edge snapshot | research payload/rows | research API snapshot | research counts/status/availability；formal view needs linked PASS/full gates；fail-closed | publisher/API -> frontend | provenance yes；no | SQL `:169-415`; edge `:138-163,185-370` |
| canonical resolver/promotion | historical identity+canonical evidence | PASS eligible or non-PASS | historical/PIT/market/calendar/action/availability；reasons block；fail-closed | no first-party runtime caller found -> canonical contract | current identity not accepted；only fully verified formal possible | resolver `:48-110`; service `:83-215`; contract `:168-191` |

每一列都記錄了 input/output、guards、failure或reason、fail mode、caller、consumer、current identity與formal reachability；上方graph補足精確CLI/workflow caller名稱及status transitions。

## Gate 稽核

- **Historical identity verification** — `CurrentIdentityRepository.fetch`/archive builder只產research限制；formal resolver要求 `ListingPeriodIdentity`。Current identity能留在research provenance，但不能進formal resolver。Fail-closed；無reachable bypass。
- **Point-in-time verification** — `FeatureArtifactManifest`、opaque artifact property與reader固定PIT false/unverified，caller不可覆寫。Validation failure。Fail-closed；無reachable bypass。
- **`available_at <= decision_at`** — dataset、latest repo、prediction、payload、SQL及frontend formal validator皆檢查。Late data被排除、拒絕或降級。Fail-closed；無reachable bypass。
- **System status** — feature/prepared/model/snapshot/payload/SQL要求exact research；frontend missing status降為research，unknown降為FAIL。Fail-closed；無reachable bypass。
- **`HARD_FAIL`** — archive builder、dataset、latest repository、edge排除或拒絕；formal snapshot也不得有hard fail。Fail-closed；無reachable bypass。
- **Production eligibility** — model promotion要求exact PASS與完整audit/locked holdout/provenance；canonical promotion要求完整historical/PIT/calendar/action evidence。Current research graph與canonical formal graph沒有第一方接線。Fail-closed；無reachable bypass。
- **Research-only state** — feature manifest、prepared audit/manifest、runner、bundle/snapshot/payload均固定constant；mismatch exception。Fail-closed；無reachable bypass。
- **`NO_TRADE`** — research decision adapter/result、gate payload、Supabase payload與SQL RPC逐層要求。Candidate/watch count必為0。Fail-closed；無reachable bypass。
- **Candidate creation** — underlying formal policy內部可能產生暫態candidate，但research adapter丟棄並輸出NO_TRADE，result contract拒絕candidate。對外boundary fail-closed；無formal output。
- **Formal publication** — production workflow只調用research publisher/RPC；edge formal status另需linked PASS及完整gates。Fail-closed；無reachable bypass。

## Bypass 調查

| 疑似 bypass | Reachability / caller | Formal output | Blocker / classification |
|---|---|---|---|
| 丟棄/替換 `POINT_IN_TIME_UNVERIFIED` | readers/builders可達但contract固定且read-back | 否 | **BLOCKED** by feature/prepared contracts |
| `FEATURE_RESEARCH_ONLY`轉正式 | 未找到第一方converter；consumer要求exact research | 否 | **BLOCKED** |
| missing/unknown status預設PASS | backend缺欄位拒絕；frontend missing->research、unknown->FAIL | 否 | **BLOCKED** |
| `HARD_FAIL`後繼續 | 各層排除/拒絕 | 否 | **BLOCKED** |
| system validation前產candidate | formal policy可能暫態candidate | 否 | adapter轉NO_TRADE，result/payload再拒絕；**BLOCKED** |
| research artifact走formal publisher | production job可達，但實際module/RPC是research publisher | 否 | exact research/no-trade；**BLOCKED** |
| filename/default重建formal status | filename只核sidecar/hash/market；status仍驗內容 | 否 | **BLOCKED** |
| workflow/CLI漏historical verification | current identity research workflow確實可達 | 否 | 狀態固定unverified/research；**REACHABLE AS RESEARCH ONLY, BLOCKED FROM FORMAL** |
| direct repository/service bypass | 第一方caller仍受typed contracts；canonical需要不同type | 否 | **BLOCKED** for inspected first-party callers |
| 第二production entry point | manual latest/OOS仍使用同research scripts | 否 | **NOT FOUND**；不延伸成全域安全宣稱 |
| generic CLI dynamic runner | repository內無第一方PASS runner；default config cap research | repository內否 | **UNRESOLVED EXTERNAL/FUTURE RISK** for external runner/custom config |
| frontend `candidates`集合名稱 | UI grouping可出現，但item仍NO_TRADE/system research | 否 | 不是formal `Decision.CANDIDATE`；**BLOCKED** |
| verifier輸出 `status: PASS` | operational check success，可達 | 否 | 同結果明列 `system_status: RESEARCH_ONLY`；**NOT PRODUCT PASS** |

## Primary Conclusion Rationale

**FAIL_CLOSED_BY_CURRENT_CODE**。Current-identity producer-to-publisher第一方路徑在每個語意邊界保留或重新施加research-only/PIT-unverified。最接近candidate的是underlying policy內部暫態結果，但adapter在公開result前固定NO_TRADE，result contract、payload與SQL各自再拒絕。最接近production publication的是production workflow job，但它只發布research snapshot到research RPC，不產生formal PASS/candidate。

這不是只靠absence of evidence：結論由可達callers上的固定status、read-back contracts、decision adapter、publisher payload與DB RPC多層明示拒絕支持。沒有repository證據支持 `CONFIRMED_P0_BUG`。

## 已確認事實

- Current identity repository明示不是historical listing master，且它確實參與archive universe filtering，所以survivorship/PIT limitation存在。
- Feature artifact固定PIT unverified與research-only；integrity verification不等於PIT verification。
- Prepared dataset audit/manifest與現行venue runner均固定research-only；runner不回PASS。
- `available_at <= decision_at`、market分離、h=5、non-hard-fail在相關直接路徑多層檢查。
- Daily inference只用rank model排序，未找到frontend第二final score參與formal path。
- Research decision固定NO_TRADE，research result contract拒絕CANDIDATE。
- Research publisher/SQL要求research-only、零candidate/watch/hard-fail且每列NO_TRADE。
- Edge formal PASS另需linked PASS、locked holdout與完整dated gates。
- Canonical formal path要求historical identity及完整PIT/calendar/company-action evidence，沒有current research graph的第一方runtime caller。

## 推論與限制

### Evidence-supported inference

- 在此HEAD的已檢查repository entry points中，current-derived artifact即使走完build、train、inference與production-environment publish job，仍只能成為research-only/no-trade output。
- Dynamic CLI在現行第一方runner/config下不能提供current-derived formal PASS；這是repository caller範圍的推論，不是宣稱所有外部Python API使用都不可濫用。

### Unresolved external risk

- 未查production database內容、部署版本、遠端workflow state、secrets或外部服務；本task無此權限。
- Repository外custom runner/config、偽造local manifest、deployment drift或未來新增entry point可能改變boundary。
- 未證明歷史資料本身正確；只證明current-derived未驗證狀態在已檢查路徑不正式提升。
- 本結論只證明inspected repository paths，不把未找到bypass本身當安全證明。

## 下一個唯一微任務

### Exact goal

修復既有inventory已確認的frontend unsupported-horizon P2：使 `loadPredictionSnapshot({ horizon: 2 | 3 | 10 })` 穩定fail closed為 `UNSUPPORTED_HORIZON`，而不是 `RangeError` 或 `MODEL_NOT_RELEASED`；horizon 5 strict path不變。

### Proposed allowed files

1. `src/data/prediction-api.js`
2. `src/data/prediction-contract.js`
3. `tests/test_frontend_five_day_contract.py`

### Focused validation

- 既有Node reproduction逐一驗證2、3、10為 `UNSUPPORTED_HORIZON`，5仍走正常strict path。
- `uv run --system-certs --extra test pytest -q tests/test_frontend_five_day_contract.py`
- `git diff --check`

### Fast/full verification requirements

- Focused通過後需跑 `pwsh -NoProfile -File scripts/verify-fast.ps1`。
- 此窄幅分類修復預設不需full verification；若focused/fast顯示跨層contract影響或修改超出三檔，才升級full。

### Priority

本次未確認P0 bypass；unsupported-horizon是先前inventory已重現的P2，範圍小且可用精確regression test封閉。

## 修改檔案

本task只觸及兩個允許路徑：

1. `tasks/active/TASK.md`（執行期間ACTIVE，完成後精確恢復NONE）
2. `tasks/completed/2026-07-22-characterize-current-identity-formal-promotion-boundary.md`

沒有修改product、test、script、workflow、configuration、一般documentation或既有completed records。既有inventory報告未寫入、stage、移除、改名或替換。

## Focused Validation

以下命令在ACTIVE task恢復NONE且本報告已建立後依序執行：

- `uv run --system-certs --extra test pytest -q tests/test_codex_workflow_contract.py::test_single_active_task_structure` — exit code **0**；1 test passed。
- `git diff --check` — exit code **0**；無diff error；只有Git提示 `tasks/active/TASK.md` 日後接觸時LF可能轉CRLF。
- `git diff --name-status` — exit code **0**；無輸出，確認沒有tracked或staged diff。
- `git status --short --branch` — exit code **0**；輸出branch ahead 1及兩個untracked completed reports：本報告與先前inventory報告。

四個focused commands均通過，沒有失敗命令需要文件修復。

未執行fast或full verification，符合本analysis-only task限制。

## 修復輪數

- Focused-command-triggered task-document repair rounds：0。
- ACTIVE建立、正常封存、驗證結果回填、NONE恢復不是repair round。
- 一次封存patch因ACTIVE file上下文不匹配而原子性地未套用；沒有檔案改動、不是focused command failure，因此不計repair round。

## Task 狀態

- Archived path：`tasks/completed/2026-07-22-characterize-current-identity-formal-promotion-boundary.md`
- Final `tasks/active/TASK.md`：`# No active task` / `## Status` / `NONE`。

## 權限確認

- 無product code/test change。
- 無commit、push、PR、deployment。
- 無pull、merge、rebase、reset、restore、stash、clean。
- 無production mutation、formal-data、secret、remote-service或remote-resource operation。
- 無clone、worktree、cloud sandbox、repository copy、branch或額外folder。

## 剩餘風險

- 結論只證明此HEAD的inspected first-party repository paths；未來新增caller、publisher或status converter需持續受contract保護。
- External/custom dynamic runner與deployment drift仍需獨立治理；它們不是本次confirmed bug。
- Current identity仍造成research資料的historical/PIT與survivorship limitation；現行安全性來自禁止formal promotion，不是資料已被historically verified。
