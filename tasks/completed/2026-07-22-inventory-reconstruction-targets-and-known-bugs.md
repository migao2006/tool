# Inventory Reconstruction Targets and Known Bugs

## Status

COMPLETE

## Goal

以有界、可重現的 repository 證據，建立下一批重組目標、已確認與疑似 Bug、
優先級與依賴、受控微任務數量，以及唯一下一個微任務的分析清單；本任務不修改
產品行為，也不修復任何 Bug。

## Repository and Commit State

- Repository root：
  `C:/Users/a0912/Documents/Codex/2026-07-22/agents-md-tasks-active-task-md`。
- Branch：`main`。
- HEAD：`ce9bbd0edf3a08411f9571946e76bac0ba93a9a9`。
- Latest commit：`ce9bbd0 refactor(data): extract daily-bar publication contracts`。
- Initial branch state：`main...origin/main [ahead 1]`，即 ahead 1、behind 0。
- Initial working tree 與 staging：乾淨；`git diff --name-status`、`git diff --stat`
  均無輸出。
- Final tracked diff：無；`tasks/active/TASK.md` 已還原為 HEAD 的標準 `NONE`。
- Final untracked state：只新增本完成紀錄；沒有第三個修改路徑。
- 未建立 clone、worktree、cloud sandbox、repository copy 或 branch。

## Authoritative Product Constraints

本分析將下列契約視為不可降低的門檻：正式只支援 `horizon=5`，其他 horizon
回傳 `UNSUPPORTED_HORIZON`；ETF／普通股票與 TWSE／TPEx 分離；排名只來自
rank model，前端不得建立第二個 final score；`available_at <= decision_at`；不得
look-ahead 或 survivorship bias；`HARD_FAIL` 不得產生正式候選；fake、placeholder、
synthetic fallback 不得冒充真實結果；完成正式驗證前維持 `RESEARCH_ONLY`；不得
宣稱保證獲利或精確未來價格。

## Evidence Sources Inspected

- 指示與產品文件：`AGENTS.md`、`.ai/product.md`、`.ai/architecture.md`、
  `.ai/decisions.md`、`.ai/code-review.md`、`.ai/known-issues.md`。
- Task workflow：`tasks/README.md`、`tasks/TASK_TEMPLATE.md`、原始
  `tasks/active/TASK.md`，以及使用者指定的三份 2026-07-22 completed records。
- Repository inventory：tracked `src/`、`scripts/`、`tests/`、`.github/` 路徑、
  implementation/test 檔案大小與結構；只有 root `AGENTS.md`，沒有 nested
  `AGENTS.md` 或 `AGENTS.override.md`。
- 一次性 indicators：TODO/FIXME/HACK/XXX/BUG、skip/skipif/xfail、
  `type: ignore`/`noqa`、file-level pyright suppressions、HARD_FAIL、horizon、
  RESEARCH_ONLY、point-in-time、ranking/final score、placeholder/fallback、
  dynamic loading、partial task records、CI exclusions。
- Targeted implementation：daily-bar publication、archive feature builder/current
  identity、daily inference/decision adapter、frontend prediction API/contract/validator、
  historical backfill coordinator、release manifest sync、daily research workflow。
- Targeted tests/callers：daily publication、TWSE/TPEX feature/inference、decision
  adapter、frontend five-day/market-scope、backfill coordinator、release manifest、
  daily workflow tests與相關 CLI entry points。
- 既有 full verification 證據依使用者提供：Python 985 passed、Playwright 65 passed、
  `verify-fast.ps1` exit 0、`verify-full.ps1` exit 0；本任務沒有重跑 full suite。

廣域文字搜尋第一次被 `src/vendor/` 的 minified bundle 放大並截斷；後續只針對尚未
完成的 indicator，排除 vendor 並限縮到 first-party source/tests/workflows。沒有重跑
已完成的搜尋，也沒有把截斷內容當成 finding。

## Confirmed Bugs

### FB-01 — Frontend unsupported horizon throws before returning the required reason code

- Classification：`CONFIRMED_BUG`。
- Severity：P2；只影響未支援 horizon，正式 5 日路徑是可行 workaround，但行為違反
  明確 horizon 契約。
- Exact evidence：
  - `src/data/prediction-api.js:34-39` 對未支援 horizon 呼叫
    `createUnavailableSnapshot`，reason code 為 `MODEL_NOT_RELEASED`。
  - `src/data/prediction-contract.js:170-172` 要求 normalized horizon 同時等於
    expected horizon 與 `CURRENT_HORIZON`；2、3、10 必定丟出 `RangeError`。
  - `src/data/prediction-contract.js:228-242` 的 unavailable builder 又呼叫上述 formal
    normalizer，故無法完成 unsupported-horizon branch。
  - `docs/prediction_api_contract.md:156-158` 明確記錄未支援值必須回
    `UNSUPPORTED_HORIZON`，並指出現有 frontend code 尚未統一。
  - `supabase/functions/prediction-snapshot/handler.ts:65` 與
    `supabase/functions/prediction-snapshot/tests/handler_test.ts:165` 顯示 backend 已使用並
    測試 `UNSUPPORTED_HORIZON`。
- Reproduction：
  `node --input-type=module -e "import { loadPredictionSnapshot } from './src/data/prediction-api.js'; const snapshot = await loadPredictionSnapshot({ horizon: 2, market: 'TWSE', config: {} }); if (snapshot.reasonCodes?.[0] !== 'UNSUPPORTED_HORIZON') { throw new Error('expected UNSUPPORTED_HORIZON, received ' + snapshot.reasonCodes?.[0]); }"`
  exit 1，實際在 `prediction-contract.js:172` 丟出
  `RangeError: 預測 API 回傳的 horizon 與請求不一致。`。
- Affected paths：`src/data/prediction-api.js`、`src/data/prediction-contract.js`、
  `src/core/ui-state.js`；回歸保護缺口在 `tests/test_frontend_five_day_contract.py`。
- Product impact：使用者或 caller 傳入 2、3、10 時拿不到可判讀的
  `UNSUPPORTED_HORIZON` fail-closed 結果，而是未包裝例外；frontend/backend reason-code
  語意不一致。
- Likely minimum repair boundary：兩個 production files
  `prediction-api.js`/`prediction-contract.js` 加一個行為型 regression test；UI state 的
  reason-code mapping 是否同步可在同一微任務內確認，但不得放寬 formal snapshot 的
  `horizon=5` 驗證。
- Separate analysis first：否；root cause、reproduction 與最小 repair boundary 已足夠。

沒有其他 finding 達到 confirmed bug 的證據門檻。特別是
`.ai/known-issues.md` 明載尚無 confirmed issue；唯一 PARTIAL completed record 是已讀取的
daily-bar extraction record，其 basedpyright 缺口已由後續 COMPLETE record 修復。沒有
confirmed P0 或 P1 bug。

## Suspected Risks

### SR-01 — Current-only identity may encode survivorship if any research-only boundary is bypassed

- Classification：`SUSPECTED_RISK`，不是 current confirmed bug。
- Severity：P0-class risk，因為若進入 formal path 會造成 survivorship bias；目前證據顯示
  多層 fail-closed guard，尚未建立錯誤 formal result。
- Exact evidence：
  - `src/data/research/current_identity_repository.py:50-79` 明確只讀 current
    `securities`，並自述不主張 point-in-time identity；同時正確限定 market 與
    `COMMON_STOCK`。
  - `src/data/research/archive_feature_builder.py:71-83` 要求 current identity snapshot，
    `:125-181` 以該 snapshot 決定歷史 symbol/identity/listing-date inclusion。
  - `src/data/research/archive_feature_rows.py:159` 將 point-in-time status 固定為
    `UNVERIFIED`，`:292-293` 固定輸出 `FEATURE_RESEARCH_ONLY`/`RESEARCH_ONLY`。
  - `src/pipeline/twse_research_daily_inference.py:402-420` 固定 snapshot 為
    `RESEARCH_ONLY`，保存 `POINT_IN_TIME_UNVERIFIED`、locked-holdout 與 formal gate
    缺口。
  - `src/pipeline/twse_research_prediction_contracts.py:197-200` 在 research gates 存在時
    序列化 decision 為 `NO_TRADE`。
  - 正式 canonical path 另由
    `src/data/canonical/historical_security_resolver.py:52-109` 要求 date-covered、
    `available_at <= cutoff`、verified historical identity；
    `src/data/canonical/daily_bar_promotion.py:166-179` 對未驗證 PIT 與 retrieval-time
    availability 加入 reasons，只有無 reason 才可 `production_eligible`。
- Inspection method：沿 current identity repository → archive feature builder/rows →
  prepared/daily inference → research serialization，以及獨立 canonical promotion path 的
  exact symbol/caller search；現有 tests 也明確期待 `POINT_IN_TIME_UNVERIFIED` 與
  `RESEARCH_ONLY`。
- Product impact：若未來新 publisher、promotion 或 workflow 繞過任一 guard，歷史 universe
  可能排除已下市或已轉板標的，污染排名、回測與正式候選。
- Likely minimum repair boundary：尚不可指定 code repair；先做只讀 end-to-end boundary
  analysis，列出所有 `FEATURE_RESEARCH_ONLY` consumers、promotion/publisher entry points、
  dynamic workflow module selection 與缺少的 negative regression assertions。
- Separate analysis first：是；未證明 bypass，不得虛報 confirmed bug 或直接修改 code。

## Technical Debt

### TD-01 — Critical pipeline modules broadly suppress static typing diagnostics

- Classification：`TECHNICAL_DEBT`；maintenance priority P3，沒有 demonstrated wrong output。
- Evidence：`src/pipeline/twse_research_daily_inference.py:5-7` 關閉 Any、unknown
  variable/member/argument 等 diagnostics；`src/pipeline/research_dataset.py:8-13`、
  `src/pipeline/venue_latest_feature_repository.py:5-8` 也有多項 file-level suppressions；
  `src/models/stock/quantile_return_model.py:59` 仍有 production return-value ignore。
- Inspection：first-party critical directories 的 `# pyright:` 與 `type: ignore` search。
- Impact：DataFrame、dynamic model與repository payload contract drift 較難由 basedpyright
  提前發現。
- Minimum repair boundary：每次只處理一個 module boundary，引入 typed DTO/Protocol 並移除
  對應 suppression；不可一次 repository-wide 改型別。
- Separate analysis first：是，需逐 module 建立診斷 baseline。

### TD-02 — Frontend contract tests rely heavily on source-text assertions

- Classification：`TECHNICAL_DEBT`；maintenance priority P3，但已使 FB-01 缺少行為回歸保護。
- Evidence：`tests/test_frontend_five_day_contract.py:51-78` 只檢查 client 字串存在；
  `:231-241` 只檢查錯誤文字；沒有執行 `loadPredictionSnapshot({horizon: 2})`。
- Inspection：test definitions 與 horizon caller search；backend Deno test 則有真正的
  unsupported request assertion。
- Impact：語句仍存在但控制流不可達、丟錯 exception 或 reason code 不一致時，test 仍可通過。
- Minimum repair boundary：在 FB-01 修復微任務加入一個 runtime JS contract test；保留必要
  source-shape assertions，但不把它們當行為證明。
- Separate analysis first：否。

### TD-03 — Release manifest synchronization combines validation, rendering and filesystem mutation

- Classification：`TECHNICAL_DEBT`；maintenance priority P3。
- Evidence：`scripts/sync_release_manifest.py` 約 912 physical lines；`:67-386` 驗證大型
  nested manifest，`:398-821` render 多份 JSON/Markdown，`:823-889` 讀取／組合／寫入五個
  generated outputs，`:892-908` 提供 CLI。
- Impact：manifest schema、文件 copy 與 I/O mode 為不同變更原因，任一修改都會觸發整個
  生成器的相容風險。
- Minimum repair boundary：先鎖定 validation error matrix 與 deterministic output mapping，
  再抽純 validation 或 renderer；不得做 pass-through-only wrapper。
- Separate analysis first：否，已有清楚 contract surface，但需 characterization microtask。

### TD-04 — Daily workflow tests cover text contracts, not executable job composition

- Classification：`TECHNICAL_DEBT`；maintenance priority P3。
- Evidence：`.github/workflows/daily-research-model.yml` 約 548 lines，包含 resolution、R2
  publication、feature build、trusted artifact discovery、Staging publish/verify、Production
  publish/verify；`tests/test_daily_research_model_workflow.py` 只有 4 個 source-text tests。
- Impact：matrix module dispatch、artifact naming/digest、environment/secrets gates 與
  `needs` edges 高度耦合；純文字 assertion 不證明 workflow expression 或 shell path 可執行。
- Minimum repair boundary：先建立 workflow contract inventory/parse-based characterization，
  再考慮有實際 job responsibility 的 reusable workflow；不得建立永久 pass-through workflow。
- Separate analysis first：是，因涉及 staging/production 邊界但本任務無遠端授權。

### TD-05 — One model-bundle test can skip when LightGBM is unavailable

- Classification：`TECHNICAL_DEBT`；maintenance priority P3。
- Evidence：`tests/test_twse_research_model_bundle.py:62-64` 使用
  `pytest.importorskip("lightgbm")`；未發現其他 skip/skipif/xfail marker，也未發現 CI
  `continue-on-error`/`paths-ignore`/`--ignore` exclusion。
- Impact：缺少 LightGBM 的環境不會驗證 fitted bundle round trip；這不是目前 full-suite
  failure 或錯誤結果的證據。
- Minimum repair boundary：確認 pinned test extra 必定安裝 LightGBM，或將 dependency absence
  明確列為 test environment failure；需獨立、低優先微任務。
- Separate analysis first：是，先確認 CI dependency matrix，不可把 optional local environment
  直接當產品 bug。

## Prioritized Reconstruction Roadmap

估算假設：每個 microtask 只有一個可驗證 outcome，通常不超過 5 個 tracked paths；
characterization、pure extraction、caller migration、compatibility cleanup 與 verification
分開；不包含 formal data migration、production access、secret 或 deployment 工作。以下
恰好五個 target。

### 1. Archive feature construction and current-identity row adaptation

1. Rank：1。
2. Exact component：`src/data/research/archive_feature_builder.py`（約 312 lines）與緊密
   依賴 `src/data/research/archive_feature_rows.py`（約 298 lines）。
3. Mixed responsibilities：manifest completeness/scope gate、current identity inclusion、
   archive object read/parse、current publication merge、feature calculation、hard-fail exclusion、
   provenance binding、batch writer lifecycle、audit aggregation。
4. Public contracts：`ArchiveFeatureDatasetBuilder.build`、
   `ArchiveFeatureAudit`/`ArchiveFeatureBuildError`、canonical/publication/output row adapters。
5. Known direct callers：TWSE/TPEX wrapper builders、
   `scripts/build_twse_research_feature_dataset.py`、
   `scripts/build_tpex_research_feature_dataset.py`；主要 tests 為
   `tests/test_twse_archive_feature_dataset.py` 與 `tests/test_tpex_feature_pipeline.py`。
6. Dynamic-loading risk：沒有 importlib/entry-point module loading 證據；但 market wrapper、
   artifact schema/hash、publication snapshot 與 workflow-selected CLI 是 naming/contract
   dependencies。
7. Existing test protection：TWSE archive suite 約 404 lines，含 publication、PIT、abort 與
   scope cases；TPEX pipeline 另覆蓋 common-stock scope。尚缺完整「research-only artifact
   絕不進 formal consumer」caller graph regression。
8. Estimated risk：高；直接觸及 survivorship/PIT、TWSE/TPEX、ETF separation 與 feature
   provenance。
9. Estimated microtasks：5–7。
10. First microtask：只讀 characterize `FEATURE_RESEARCH_ONLY` 到所有 consumer/publisher 的
    fail-closed boundary；完成前不抽 code。
11. Bug repair before reconstruction：沒有 confirmed bug repair；但 SR-01 的 P0 analysis gate
    必須先完成。

### 2. Daily-bar publication source/repository/serialization/service

1. Rank：2。
2. Exact file：`src/data/ingestion/daily_bar_publication.py`，約 577 lines；前一 commit 只抽出
   source contracts，尚未拆其餘責任。
3. Mixed responsibilities：Supabase source query/dedup/coverage validation、Parquet schema與
   serialization、R2 write/head/checksum、manifest construction/persistence、Git/library
   provenance、publication orchestration。
4. Public contracts：`DailyBarPublicationSourceRepository.fetch`、
   `serialize_daily_bar_publication`、`DailyBarPublicationArtifact/Result`、
   `DailyBarPublicationManifestRepository.save_and_read`、`DailyBarPublicationService.publish`；
   舊 module re-export path 必須相容。
5. Known direct callers：`scripts/publish_daily_bar_publication_snapshots.py`；workflow path filter
   `.github/workflows/daily-research-model.yml:18`；`tests/test_daily_bar_publication.py`。
6. Dynamic-loading risk：沒有動態載入此 module 的證據；內部 lazy-import pyarrow 與查詢
   package versions，workflow 另以 module string 啟動 CLI。
7. Existing test protection：10 tests/約 263 lines，已鎖 source contract identity/mapping/error
   與 500-row immutable round trip；`SourceRepository.fetch` 的 query、dedup、coverage/error
   matrix 缺直接 characterization。
8. Estimated risk：中高；同時耦合 private Supabase、R2、Parquet 與 manifest schema。
9. Estimated microtasks：4–6。
10. First microtask：只增加 `DailyBarPublicationSourceRepository.fetch` 的 query/filter、最新列
    selection、TWSE/TPEX/COMMON_STOCK、coverage 與 reason-code characterization；尚不抽檔。
11. Bug repair before reconstruction：否；FB-01 不在此 boundary。

### 3. Venue daily research inference

1. Rank：3。
2. Exact file：`src/pipeline/twse_research_daily_inference.py`，約 452 lines；
   `TpexDailyResearchInference` 以 subclass 共用此實作。
3. Mixed responsibilities：bundle/cross-section contract validation、evaluation-scope 判定、
   rank/direction/quantile inference、transaction cost/capacity、rank cross-section、decision
   gate adaptation、prediction/snapshot/provenance assembly。
4. Public contracts：`TwseDailyResearchInference.run` 與
   `TwseResearchPredictionSnapshot`；market、horizon、rank ordering、`NO_TRADE` research
   serialization 和 reason codes 必須不變。
5. Known direct callers：TWSE daily publish CLI、TPEX subclass及其 CLI；
   `tests/test_twse_latest_research_inference.py`、
   `tests/test_tpex_latest_research_inference.py`、decision adapter tests。
6. Dynamic-loading risk：此 file 無動態 module load，但 bundle I/O 使用 `import_module` 還原
   model classes；TPEX 對 TWSE-named base class 是 compatibility dependency。
7. Existing test protection：TWSE 3 tests、TPEX 3 tests，涵蓋 in-memory inference、cost
   recompute、market mismatch 與 `latest_available_at <= decision_at`；需補 rank-only/no-label
   phase contract與 hard-fail source input characterization。
8. Estimated risk：高；同時碰模型 ranking、quantile/direction gates、cost與 formal fail-closed
   語意。
9. Estimated microtasks：4–6。
10. First microtask：用現有 in-memory bundles characterize `_validate_contract`、model outputs、
    cost、rank、policy、snapshot 六個 phase 的 observable contract，再選一個 pure boundary 抽取。
11. Bug repair before reconstruction：否；但 SR-01 analysis 完成前不得宣稱 formal readiness。

### 4. Frontend prediction API/normalization/formal validation component

1. Rank：4。
2. Exact component：`src/data/prediction-api.js`（約 74 lines）、
   `src/data/prediction-contract.js`（約 243 lines）、
   `src/data/prediction-validator.js`（約 230 lines）。
3. Mixed responsibilities：request policy/auth token fallback、unsupported/unconfigured states、
   payload aliases/coercion、market/ETF/HARD_FAIL partition、unavailable snapshot creation、
   formal PASS timestamp/model/gate validation。
4. Public contracts：`loadPredictionSnapshot`、`normalizePrediction`、
   `normalizePredictionSnapshot`、`createUnavailableSnapshot`、`PredictionApiError`；Rank Score、
   global rank 與 decision fields 不得合成 final score。
5. Known direct callers：application bootstrap/pages 透過 prediction client；fixture server 直接
   import normalizer；frontend five-day與market-scope tests讀取上述 files。
6. Dynamic-loading risk：無 importlib；browser cache-busting query suffix、ES module import path、
   global config/Supabase SDK loader 是 compatibility dependencies。
7. Existing test protection：frontend contract file 約 342 lines，但多為 source-text assertion；
   fixture server只 runtime-normalize正式 horizon=5 response，沒有 unsupported runtime test。
8. Estimated risk：中高；HARD_FAIL、ETF/market、formal PASS validation安全敏感，但 component
   可用純 JS inputs characterization。
9. Estimated microtasks：3–5 reconstruction microtasks，另加 1 個 confirmed bug-repair
   microtask（不計入 reconstruction total）。
10. First microtask：先獨立修復 FB-01 並加 runtime unsupported-horizon regression；之後才
    characterize unavailable-state DTO 與 formal normalizer 的分離 boundary。
11. Bug repair before reconstruction：是，FB-01 必須先修；不得在 refactor 中順便改行為。

### 5. Release manifest validation/rendering/synchronization

1. Rank：5。
2. Exact file：`scripts/sync_release_manifest.py`，約 912 lines。
3. Mixed responsibilities：nested release schema與invariant validation、quality-tool/workflow
   consistency、model card/status/release-state rendering、marker fallback replacement、five-output
   filesystem synchronization、digest與 CLI error handling。
4. Public contracts：`python scripts/sync_release_manifest.py [--check]`、
   `validate_manifest`、`expected_outputs`、marker names與五個 generated file contents。
5. Known direct callers：`scripts/run_quality_security_checks.sh:16`、README documented command、
   `tests/test_release_manifest_sync.py`。
6. Dynamic-loading risk：無 dynamic imports；高 filename/section-marker/path convention risk，
   `release-manifest.sha256` 綁 exact bytes。
7. Existing test protection：6 tests/約 125 lines，涵蓋 generated sync、model-card source、
   repository/remote evidence、unknown commit、digest與既有 hardening fields；validation
   negative error matrix仍不足。
8. Estimated risk：中高；不改 runtime prediction，但錯誤會誤述 release/provenance/status。
9. Estimated microtasks：5–7。
10. First microtask：characterize `validate_manifest` 的必填 schema/invariant error matrix 與
    `expected_outputs` deterministic mapping，之後只抽 pure validation module。
11. Bug repair before reconstruction：否；不得把文件 generator 重組誤當產品狀態升級。

## Task Count and Schedule Estimate

- Remaining reconstruction microtasks：21–31（五 targets ranges 相加）。
- Confirmed bug-repair microtasks：1（FB-01）。
- Additional analysis microtasks：1（SR-01 end-to-end fail-closed boundary）。
- Total controlled backlog：23–33 microtasks。
- Likely commit/PR batches：假設每個 microtask 一個可 review commit、每個 PR 合併 1–2 個相鄰
  且同 boundary 的 microtasks，約 13–20 個 PR batches；安全或 production-adjacent boundary
  不跨 target 混批。

三種情境均以 total controlled backlog 計算並向上取整：

| Scenario | Throughput | Estimate |
| --- | ---: | ---: |
| Conservative | 3 microtasks/week | 8–11 weeks |
| Normal | 5 microtasks/week | 5–7 weeks |
| Accelerated | 1 microtask/working day | 23–33 working days，約 5–7 work weeks |

估算不含未知 production、data migration、external service、secret、deployment blocker，也不含
遠端 CI queue/review latency；不是 completion-date 承諾。

## Single Recommended Next Microtask

- Exact goal：只讀追蹤並證明由 `CurrentIdentityRepository` 產生的 current-only identity、
  `FEATURE_RESEARCH_ONLY` feature artifact與 prepared/daily inference output，不存在繞過
  verified historical identity、PIT、formal gate與system-status guard而形成 `PASS` 或
  `CANDIDATE` 的路徑；列出所有 direct/dynamic callers及缺少的 negative regression tests。
- Proposed allowed files：
  1. `tasks/active/TASK.md`
  2. `tasks/completed/2026-07-22-characterize-current-identity-formal-promotion-boundary.md`
- Focused validation：
  1. `uv run --system-certs --extra test pytest -q tests/test_codex_workflow_contract.py::test_single_active_task_structure`
  2. `git diff --check`
  3. `git diff --name-status`
- Fast verification required：否，分析只改 task Markdown。
- Full verification required：否。
- Priority reason：沒有 confirmed P0/P1；SR-01 是需先分析的 P0-class survivorship risk，符合
  selection rule 第 3 項，優先於 confirmed P2 repair及 ordinary reconstruction。
- Implementation：本 inventory task 沒有執行此 microtask，也沒有修復 FB-01。

## Focused Validation

| Command | Exit code | Result |
| --- | ---: | --- |
| `uv run --system-certs --extra test pytest -q tests/test_codex_workflow_contract.py::test_single_active_task_structure` | 0 | 1 passed；標準 `NONE` 結構與 completed filename contract 通過 |
| `git diff --check` | 0 | 通過；final run 無輸出 |
| `git diff --name-status` | 0 | 無 tracked diff；新 completed record 為預期 untracked file |

依 scope 明確不執行 fast verification 或 full verification。

## Repair Rounds

- Repair rounds used：0／2。
- 尚無 focused command failure，未執行 task structure、Markdown formatting 或 required
  report-section repair。

## Limitations

- 本任務未使用 production、Supabase、R2、GitHub API、network issue tracker 或任何 secret，
  因此未驗證 remote workflow state、formal data contents 或 production migrations。
- Suite passing 只證明既有 assertions；FB-01 顯示 source-text tests 仍可能漏掉控制流 defect。
- SR-01 目前有明確 fail-closed 證據，但尚未完成所有 publisher/dynamic workflow consumer 的
  end-to-end no-bypass proof，因此不得升格為 confirmed bug，也不得宣稱 survivorship 已解決。
- Estimates 是 bounded microtask ranges，不含未知外部 blockers。

## Permission Confirmation

- 只暫時修改並還原 `tasks/active/TASK.md`，以及新增本 completed record；沒有第三個 path。
- 未修改 product code、tests、scripts、workflows、configuration、dependencies 或 runtime。
- 未 commit、push、建立/合併 PR、deploy、reset、restore、stash、clean、pull、rebase 或 merge。
- 未操作 production、formal data、secret、DNS、billing、branch protection 或 remote resource。
