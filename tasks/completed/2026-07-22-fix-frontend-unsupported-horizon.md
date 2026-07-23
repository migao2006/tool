# Fix Frontend Unsupported-Horizon Handling

## Status

COMPLETE

## 結論

已修復確認的 frontend unsupported-horizon bug。`loadPredictionSnapshot` 對 repository定義的未發布horizon 2、3、10現在直接回傳不可用、`RESEARCH_ONLY`、空prediction/candidate集合且reason為 `UNSUPPORTED_HORIZON` 的fail-closed snapshot；不再拋出 `RangeError`，也不再回 `MODEL_NOT_RELEASED`。

正式支援範圍仍恰好是horizon 5。`normalizePredictionSnapshot` 的strict formal parser沒有被放寬；runtime regression證明h=5 request收到h=2 payload時仍轉為 `PREDICTION_API_CONTRACT_ERROR`，cause為 `RangeError`。

## Repository 狀態

- Root：`C:/Users/a0912/Documents/Codex/2026-07-22/agents-md-tasks-active-task-md`
- Branch：`main`
- HEAD：`ce9bbd0edf3a08411f9571946e76bac0ba93a9a9`
- Latest commit：`ce9bbd0 refactor(data): extract daily-bar publication contracts`
- Initial ahead/behind：ahead 1、behind 0；`git rev-list --left-right --count origin/main...HEAD`為`0 1`。
- Initial tracked tree與staging：乾淨；`git diff --name-status`與`git diff --stat`無輸出。
- Initial untracked paths恰好兩個：
  - `tasks/completed/2026-07-22-inventory-reconstruction-targets-and-known-bugs.md`
  - `tasks/completed/2026-07-22-characterize-current-identity-formal-promotion-boundary.md`
- 只有root `AGENTS.md`，無nested `AGENTS.md`或`AGENTS.override.md`。
- Initial active task精確為`# No active task` / `## Status` / `NONE`。

## 既有報告基準雜湊

- Inventory report SHA-256：`52DFB8B2B932AC1D7D9DCF33DD528B33EE8A4B2781A74E7CE9C2E52167B6DA8B`
- Promotion-boundary report SHA-256：`510578D8427CBEE4566509684852BA7A14B132BF5A29B1B0A38027941B02B27B`

兩份報告在product edit前、focused validation時與task完成時均維持相同雜湊，未被修改、stage、移除、改名或替換。

## Bug 重現（修改前）

三個case均使用actual public runtime module；各command只有horizon值不同：

```text
node --input-type=module -e "import { loadPredictionSnapshot } from './src/data/prediction-api.js'; const result = await loadPredictionSnapshot({ horizon: 2, market: 'TWSE', config: {} }); console.log(JSON.stringify(result));"
node --input-type=module -e "import { loadPredictionSnapshot } from './src/data/prediction-api.js'; const result = await loadPredictionSnapshot({ horizon: 3, market: 'TWSE', config: {} }); console.log(JSON.stringify(result));"
node --input-type=module -e "import { loadPredictionSnapshot } from './src/data/prediction-api.js'; const result = await loadPredictionSnapshot({ horizon: 10, market: 'TWSE', config: {} }); console.log(JSON.stringify(result));"
```

| Horizon | Exit code | Returned object | Exception | Returned reason | Formal normalization invoked |
|---:|---:|---|---|---|---|
| 2 | 1 | 無 | `RangeError: 預測 API 回傳的 horizon 與請求不一致。` | 無；caller原本傳入`MODEL_NOT_RELEASED`但未能return | 是；stack為`loadPredictionSnapshot -> createUnavailableSnapshot -> normalizePredictionSnapshot` |
| 3 | 1 | 無 | 同上 | 無 | 是 |
| 10 | 1 | 無 | 同上 | 無 | 是 |

Node另輸出既有`MODULE_TYPELESS_PACKAGE_JSON`warning；它不是本bug原因，也不影響exit classification。修改前另以h=5、`config: {}`執行public API，exit 0並回 `PREDICTION_API_NOT_CONFIGURED`，用作unrelated reason baseline。

實際行為與既有bug report一致，因此task沒有BLOCKED或擴大scope。

## Contract Boundary Inspection

- Request horizon normalization：`src/data/prediction-api.js:31`的`normalizeHorizon(horizon)`。
- Released-horizon gate：`prediction-api.js:33`的`isReleasedHorizon`。
- 原錯誤reason assignment：修改前`prediction-api.js:38`為`MODEL_NOT_RELEASED`。
- Unavailable construction：`src/data/prediction-contract.js:228`的`createUnavailableSnapshot`。
- Strict formal h=5 enforcement：`normalizePredictionSnapshot`在`prediction-contract.js:162-174`要求payload horizon同時等於requested horizon與`CURRENT_HORIZON`。
- Caller exposure：`loadPredictionSnapshot`直接return unavailable result；configured h=5 payload仍呼叫`normalizePredictionSnapshot`，contract error包裝成`PredictionApiError`。
- 原誤轉換：unsupported request進入unavailable builder後，builder仍呼叫formal h=5 normalizer，因此在能return reason之前throw。
- Existing target tests在本task前只有source-text assertions，沒有執行`loadPredictionSnapshot`的Node runtime regression。

## 根因

`loadPredictionSnapshot`先正確辨識horizon不是released h=5，但做了兩個不安全轉換：

1. 把reason設為`MODEL_NOT_RELEASED`，與repository/API的`UNSUPPORTED_HORIZON`契約不一致。
2. 將這個unsupported unavailable payload傳入只接受formal h=5的`normalizePredictionSnapshot`。該parser先檢查`horizon !== CURRENT_HORIZON`並throw，所以unavailable result根本無法建立。

第一個unsafe transition在`prediction-api.js`的reason assignment；造成uncaught exception的transition在`createUnavailableSnapshot -> normalizePredictionSnapshot`。

## 實際修改

### `src/data/prediction-api.js`

- Purpose：統一frontend/backend與產品文件的unsupported reason。
- Before：non-released 2/3/10傳`MODEL_NOT_RELEASED`。
- After：傳`UNSUPPORTED_HORIZON`。
- h=5 unchanged：released gate後的API config、auth、fetch與strict normalization path完全未改。

### `src/data/prediction-contract.js`

- Purpose：讓unsupported unavailable response在formal parser之前fail closed。
- Before：所有unavailable payload都無條件進`normalizePredictionSnapshot`，2/3/10因此throw。
- After：先用既有`normalizeHorizon`/`normalizeMarketScope`；若不是`CURRENT_HORIZON`，直接建立frozen unavailable DTO：`RESEARCH_ONLY`（或合法指定status）、`UNSUPPORTED_HORIZON`、日期/版本為null、predictions/candidates/excluded/watchlist為frozen空陣列、validation為空normalized metadata。
- h=5 unchanged：h=5仍呼叫原本的`normalizePredictionSnapshot`；formal parser本身未修改。
- Safety：unsupported branch不fetch、不建立prediction、不產candidate、不填placeholder日期/模型版本。

### `tests/test_frontend_five_day_contract.py`

- Purpose：補actual JavaScript runtime regression，而非source-text assertion。
- 新增`run_node_module`使用`node --input-type=module -e`執行repository modules。
- Runtime case逐一驗證2/3/10：不throw、回原request horizon、`RESEARCH_ONLY`、唯一reason `UNSUPPORTED_HORIZON`、四個record集合皆空。
- 設置fetch counter，證明三個unsupported requests在network/formal response path之前return。
- 保留unrelated h=5 `PREDICTION_API_NOT_CONFIGURED` reason。
- 以mock response讓h=5 request收到h=2 payload，確認仍被包裝為`PREDICTION_API_CONTRACT_ERROR`且cause為`RangeError`，證明strict parser未放寬。

## 契約保留

- Supported formal horizon仍恰好是5。
- Repository定義的未發布horizon 2、3、10均回`UNSUPPORTED_HORIZON`。
- Unsupported result保持unavailable/fail-closed：research-only、無日期/模型placeholder、無prediction/candidate/watchlist/excluded records。
- `normalizePredictionSnapshot`與`normalizePrediction`的h=5 checks未修改。
- h=5 API-not-configured reason仍是`PREDICTION_API_NOT_CONFIGURED`；其他unrelated reason-code logic未改。
- 無scoring、ranking、decision、candidate或publisher變更；沒有第二final score。
- ETF/ordinary equity、TWSE/TPEX、HARD_FAIL、RESEARCH_ONLY handling未改。
- 沒有把fake、synthetic或placeholder result呈現成real prediction。

## Runtime Regression Coverage

新增test為`test_prediction_client_returns_fail_closed_unsupported_horizons`（`tests/test_frontend_five_day_contract.py:93`）。它執行actual JS public API，而不是只檢查source string；同時涵蓋unsupported success contract、no-fetch、h=5 unrelated unavailable reason與h=5 strict response rejection。

## 驗證結果

### Preflight（全部exit 0）

- `git rev-parse --show-toplevel`
- `git branch --show-current`
- `git status --short --branch`
- `git rev-parse HEAD`
- `git log -1 --oneline`
- `git diff --name-status`
- `git diff --stat`
- `git rev-list --left-right --count origin/main...HEAD`
- `(Get-FileHash -Algorithm SHA256 -LiteralPath 'tasks/completed/2026-07-22-inventory-reconstruction-targets-and-known-bugs.md').Hash`
- `(Get-FileHash -Algorithm SHA256 -LiteralPath 'tasks/completed/2026-07-22-characterize-current-identity-formal-promotion-boundary.md').Hash`

### Focused validation

- 修改後direct Node command（單一command loop 2/3/10）：exit **0**；三者均`threw=false`、`RESEARCH_ONLY`、`UNSUPPORTED_HORIZON`、predictions/candidates為0。
- `uv run --system-certs --extra test pytest -q tests/test_frontend_five_day_contract.py`：exit **0**；20 passed。
- `pnpm dlx "@biomejs/biome@2.4.16" lint src/data/prediction-api.js src/data/prediction-contract.js`：exit **0**；checked 2 files，no fixes。這是repository quality script使用的pinned Biome與最小target集合，未修改package/lockfile。
- `git diff --check`：exit **0**；只有Windows LF-to-CRLF informational warnings。
- `git diff --name-status`：exit **0**；當時只有ACTIVE與三個允許product/test paths。
- `git status --short --branch`：exit **0**；當時只有上述四個tracked changes與兩份既有untracked reports。
- 兩個`Get-FileHash` commands：各exit **0**；值與preflight相同。

修改後direct Node exact command：

```text
node --input-type=module -e "import { loadPredictionSnapshot } from './src/data/prediction-api.js'; const results = []; for (const horizon of [2, 3, 10]) { try { const snapshot = await loadPredictionSnapshot({ horizon, market: 'TWSE', config: {} }); results.push({ horizon, threw: false, resultHorizon: snapshot.horizon, systemStatus: snapshot.systemStatus, reasonCodes: snapshot.reasonCodes, predictions: snapshot.predictions.length, candidates: snapshot.candidates.length }); } catch (error) { results.push({ horizon, threw: true, name: error.name, message: error.message }); } } console.log(JSON.stringify(results)); if (results.some((item) => item.threw || item.reasonCodes?.[0] !== 'UNSUPPORTED_HORIZON' || item.systemStatus !== 'RESEARCH_ONLY' || item.predictions !== 0 || item.candidates !== 0)) process.exitCode = 1;"
```

### Fast verification

- `pwsh -File scripts/verify-fast.ps1`：exit **0**；instruction limits、17 focused repository instruction tests與diff check通過。

### Full verification

- 第一次`pwsh -File scripts/verify-full.ps1`：exit **1**。Fast portion通過；pytest為985 passed、1 failed。唯一failure是`test_single_active_task_structure`，原因是本task文件的`## Status`與`ACTIVE`間多一空行。Command在Python suite後停止，沒有執行其後pnpm/Playwright。
- Task-document correction後，`uv run --system-certs --extra test pytest -q tests/test_codex_workflow_contract.py::test_single_active_task_structure`：exit **0**；1 passed。
- 第二次`pwsh -File scripts/verify-full.ps1`：exit **0**；fast通過、986 pytest passed、`pnpm install --frozen-lockfile`顯示Already up to date、Playwright discovery 65 tests、Playwright 65 passed。

### Final archival checks

- `uv run --system-certs --extra test pytest -q tests/test_codex_workflow_contract.py::test_single_active_task_structure`：exit **0**；1 passed，final active NONE結構通過。
- `git diff --check`：exit **0**；只有Windows LF-to-CRLF informational warnings。
- `git diff --name-status`：exit **0**；只列`src/data/prediction-api.js`、`src/data/prediction-contract.js`、`tests/test_frontend_five_day_contract.py`三個tracked product/test changes；active task已回到HEAD內容。
- `git status --short --branch`：exit **0**；branch ahead 1，三個上述tracked changes，以及兩份既有reports與本report共三個untracked completed reports。
- `(Get-FileHash -Algorithm SHA256 -LiteralPath 'tasks/completed/2026-07-22-inventory-reconstruction-targets-and-known-bugs.md').Hash`：exit **0**；`52DFB8B2B932AC1D7D9DCF33DD528B33EE8A4B2781A74E7CE9C2E52167B6DA8B`。
- `(Get-FileHash -Algorithm SHA256 -LiteralPath 'tasks/completed/2026-07-22-characterize-current-identity-formal-promotion-boundary.md').Hash`：exit **0**；`510578D8427CBEE4566509684852BA7A14B132BF5A29B1B0A38027941B02B27B`。

Final working tree沒有第六個task-modified path：三個tracked product/test files、正常lifecycle後與HEAD相同的active task，以及本task新completed report；兩份pre-existing untracked reports不是本task變更。

## 修復輪數

- Product/test repair rounds：0／2。所有product-focused checks首次即通過，之後沒有再改product/test。
- Task-document corrections：1。首次full發現`## Status`與`ACTIVE`間空行；只修改`tasks/active/TASK.md`移除空行，原失敗single test隨後exit 0。
- 第一次full failure屬本task引入的task-document structure issue，不是產品bug、pre-existing repository issue、environment、dependency或external-service failure。

## 修改檔案

### Pre-existing untracked analysis reports（保留、非本task修改）

1. `tasks/completed/2026-07-22-inventory-reconstruction-targets-and-known-bugs.md`
2. `tasks/completed/2026-07-22-characterize-current-identity-formal-promotion-boundary.md`

### 本task修改

1. `tasks/active/TASK.md`（ACTIVE lifecycle；完成後恢復NONE）
2. `src/data/prediction-api.js`
3. `src/data/prediction-contract.js`
4. `tests/test_frontend_five_day_contract.py`
5. `tasks/completed/2026-07-22-fix-frontend-unsupported-horizon.md`

沒有第六個path；沒有修改`ui-state.js`、其他tests、docs、config、workflow、dependency、lockfile或generated output。

## Task 狀態

- Archived path：`tasks/completed/2026-07-22-fix-frontend-unsupported-horizon.md`
- Final active task預期精確為：`# No active task` / `## Status` / `NONE`。

## 權限確認

- 無commit、push、PR、branch/tag或merge。
- 無deployment、production或formal-data mutation。
- 無secret access/exposure。
- 無dependency/lockfile、workflow、repository setting或remote-resource change。
- 無reset、restore、stash、clean、pull、merge或rebase。
- 無clone、worktree、cloud sandbox、repository copy、branch或額外folder。

## 剩餘風險

- Node在此repository package metadata下會輸出`MODULE_TYPELESS_PACKAGE_JSON`warning；它不影響行為，本窄task不允許修改`package.json`。
- Unsupported response是特意與formal snapshot parser分離的fail-closed DTO；未來新增欄位時應維持runtime regression，避免兩種DTO shape drift。
- 本task沒有做frontend architecture reconstruction，也沒有更改UI reason-copy mapping；caller依既有generic fail-closed state顯示不可用。

## 下一步

下一個動作應在新的Codex Session執行commit-boundary audit，核對本task diff、歷史untracked reports與預期commit scope；本session沒有開始任何額外bug fix或reconstruction task。
