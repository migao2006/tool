# Alpha Lens P1 修復交付報告

- 日期：2026-07-20（Asia/Taipei）
- 基礎版本：`tool-main-p0-fixed-2026-07-20.zip`
- 修復範圍：P1 Repository 修補、測試與部署契約
- 遠端狀態：**尚未部署至 GitHub、Supabase、Vercel 或任何正式環境**
- 模型狀態：仍為 **`RESEARCH_ONLY`**

## 一、核心結論

P1 Repository 修復已完成。主要交付包括：

1. Prediction Snapshot 正式讀取路徑由多次 PostgREST 查詢改成 **單一 RPC 請求**。
2. RPC 缺失或回應不合法時 **fail closed**，不會自動退回高成本 legacy 路徑。
3. GitHub Actions 外部 Action 全部固定至完整 commit SHA，並加入自動契約檢查。
4. 新增必要的品質與安全 CI：Ruff、basedpyright、Biome、Deno、actionlint、Gitleaks、pip-audit、SQLFluff、pre-commit。
5. 新增 Vercel 強制 CSP 與 8 項其他安全標頭，共 9 項全域安全標頭。
6. Release／migration／平台強化狀態改由 `release-manifest.json` 產生，避免文件分叉。
7. 完整 Python 測試 **923／923 通過**；Edge Function 行為測試 **39／39 通過**。

本次只完成 Repository 層級修補。Supabase migration、Edge Function、Vercel response headers、GitHub branch protection 均未遠端驗證或啟用。

## 二、P1 修復內容

### 2.1 Snapshot 讀取改為單一 RPC

新增：

- `supabase/migrations/20260720190000_prediction_snapshot_read_rpc.sql`
- `supabase/snippets/validate_prediction_snapshot_read_rpc.sql`
- `supabase/snippets/rollback_prediction_snapshot_read_rpc.sql`

RPC：

```text
market_data.get_prediction_snapshot_rows(integer, text, timestamptz)
```

RPC 在資料庫內一次組合：

- 最新 prediction run
- stock predictions
- securities
- 當下有效的 security history／industry classification
- data-quality audits
- decision gates
- market predictions
- validation run
- validation metrics
- backtests

Edge Function 正式路徑對 PostgREST 僅送出一個 `POST /rest/v1/rpc/get_prediction_snapshot_rows`。這降低的是 Edge 與 PostgREST 之間的網路往返；資料庫內部仍需執行聚合查詢，必須在 Staging 量測 CPU、延遲、payload 大小與 statement execution plan。

### 2.2 Point-in-time 與權限契約

RPC 只會選擇在 `p_observed_at` 以前已存在且可用的快照：

```text
decision_at <= p_observed_at
latest_available_at <= p_observed_at
created_at <= p_observed_at
```

Security history 採半開有效區間：

```text
effective_from <= 台北日期 < effective_to
```

`effective_to IS NULL` 才表示持續有效，且 `available_at` 不得晚於觀測時間。

RPC 使用：

- `SECURITY INVOKER`
- 固定 `search_path = pg_catalog, market_data`
- 撤銷 `public`、`anon`、`authenticated` 權限
- 僅授權 `service_role`

另新增 `validation_runs_snapshot_lookup_idx`，支援模型版本、horizon 與 completed time 的 validation lookup。

### 2.3 Fail-closed 部署順序

`SnapshotRepository` 預設：

```text
PREDICTION_SNAPSHOT_READ_MODE=rpc
```

行為：

- RPC 存在且資料合法：回傳完整 snapshot。
- RPC 不存在：回傳 `503 PREDICTION_SNAPSHOT_RPC_NOT_DEPLOYED`。
- RPC 回應格式錯誤：回傳 database response error。
- RPC timeout：回傳 504。
- 不會自動退回 legacy 多查詢路徑。

`legacy` 只保留為明確的緊急回復模式：

```text
PREDICTION_SNAPSHOT_READ_MODE=legacy
```

即使使用 legacy，最新 run 與 security history 仍受相同 point-in-time cutoff 約束。

因此部署順序必須是：

1. 驗證並套用 RPC migration。
2. 執行 validation SQL。
3. 再部署預設為 `rpc` 的 Edge Function。

順序顛倒時 API 會故意回傳 503，不會掩蓋部署錯誤。

### 2.4 GitHub Actions 供應鏈固定

新增：

- `config/github-actions-pins.json`
- `scripts/check_github_action_pins.py`
- `.github/dependabot.yml`

結果：

- 33 個 workflow 已檢查。
- 137 次外部 Action 引用全部固定為完整 40 字元 commit SHA。
- 只允許 10 個經審查的 Action／SHA 組合。
- 每次引用必須附版本註記。
- 本機 reusable workflow 不會誤判為外部 Action。
- Dependabot 每週檢查 GitHub Actions、pip 與 npm 更新。

固定的 Action 包括：

- `actions/checkout`
- `actions/setup-python`
- `actions/setup-node`
- `actions/upload-artifact`
- `actions/download-artifact`
- `actions/github-script`
- `astral-sh/setup-uv`
- `denoland/setup-deno`
- `pnpm/action-setup`
- `actions/setup-go`

### 2.5 Required quality／security CI

新增或調整：

- `.github/workflows/project-tests.yml`
- `config/quality-tools.env`
- `scripts/run_quality_security_checks.sh`
- `scripts/check_migration_contracts.py`
- `scripts/check_python_lock_contract.py`
- `scripts/check_vercel_headers.py`
- `.pre-commit-config.yaml`
- `.sqlfluff`
- `biome.json`
- `pyrightconfig.json`
- `requirements.lock`

`quality-security` job 會執行：

- GitHub Action SHA 契約
- Migration 權限與 PIT 契約
- Python 完整 exact-pin lock 契約
- Release manifest 同步
- Vercel CSP／header 契約
- `uv lock --check`
- Ruff
- basedpyright
- pre-commit
- Biome
- Deno check／fmt／lint／test
- actionlint
- Gitleaks
- pip-audit
- SQLFluff

`test-gate` 彙總：

- scope selection
- Python tests
- frontend／browser tests
- quality-security

任何已選擇的必要範圍失敗或取消，`test-gate` 即失敗。Repository 已建立此 gate，但 GitHub 遠端 branch protection 是否已把 `test-gate` 設為 required check，尚未驗證。

### 2.6 Python lock 與測試平行化

`requirements.lock` 改為完整的 transitive exact-pin export，共 32 個套件／版本條目，與 `uv.lock` 及 project／test dependencies 互相檢查。

pytest 設定修正為：

```text
-n auto --maxprocesses=4 --dist=loadfile
```

原設定有 `--maxprocesses`，但未啟用 `-n`，實際仍可能串行。現在最多使用 4 個 worker。

LightGBM bundle 測試固定 `n_jobs=1`，避免測試 worker 與 OpenMP 再度過度平行，造成 CI 非決定性卡住。

### 2.7 Vercel CSP 與安全標頭

新增 `vercel.json`，全域設定：

1. `Content-Security-Policy`
2. `Strict-Transport-Security`
3. `X-Content-Type-Options`
4. `Referrer-Policy`
5. `Permissions-Policy`
6. `X-Frame-Options`
7. `Cross-Origin-Opener-Policy`
8. `Cross-Origin-Resource-Policy`
9. `X-Permitted-Cross-Domain-Policies`

CSP 不允許：

- `'unsafe-inline'`
- `'unsafe-eval'`
- inline script attributes
- inline style attributes
- object／frame embedding

為維持嚴格 CSP，`src/core/router.js` 原本直接修改 `element.style` 的做法改為切換 CSS class：

```text
is-scroll-restoring
```

允許的 `connect-src` 僅包含本站、目前 Supabase HTTPS／WSS 與 Sentry ingest endpoint。

### 2.8 Release manifest 單一來源

`release-manifest.json` 現在同時記錄：

- 模型／research snapshot 證據
- Repository migration 數量
- 已記錄的 Staging／Production migration 邊界
- P0／P1 新增 migration
- Snapshot RPC 模式與遠端狀態
- CI gate 與工具固定版本
- Vercel CSP 狀態
- 尚未確認的 branch protection／正式站 header 狀態

同步器會產生或更新：

- `model_card.json`
- `model_card.md`
- `docs/current-status.md`
- `docs/release-state.md`
- `release-manifest.sha256`

CI 與 pre-commit 使用：

```bash
python scripts/sync_release_manifest.py --check
```

任何生成文件漂移都會失敗。

## 三、驗證結果

| 驗證 | 結果 |
| --- | ---: |
| 完整 Python tests | **923／923 通過** |
| Edge Function 行為 tests | **39／39 通過** |
| Ruff 0.15.22 | 通過 |
| basedpyright 1.39.9 | **0 errors、0 warnings** |
| pre-commit 4.6.0 | 5／5 hooks 通過 |
| SQLFluff 4.2.2 parse | P0／P1 migration 與 snippets 全部通過 |
| SQLFluff LT12 | 通過 |
| GitHub Action pin 契約 | **137／137 引用通過** |
| Migration 契約 | **36 個 migration 通過** |
| Python lock 契約 | **32 個 exact pins 通過** |
| Vercel header／CSP 契約 | 通過 |
| JavaScript syntax | **62 個檔案通過** |
| GitHub YAML parse | **34 個檔案通過** |
| Playwright test discovery | **61 個測試成功列出** |
| Release manifest sync | 通過 |
| `git diff --check` | 通過 |
| Internal／container URL 掃描 | 0 項命中 |

Edge 測試是在 Node 22 的 TypeScript transform 相容 harness 執行；它驗證行為，但不取代正式 Deno runtime 的 `deno check`、`deno fmt`、`deno lint` 與 `deno test`。

## 四、未完成或不能宣稱通過的項目

### 4.1 Supabase migration 未實際執行

目前執行環境沒有可用 Docker daemon／PostgreSQL，因此尚未執行：

- `supabase db reset --local --no-seed`
- `supabase db lint --local`
- RPC migration 實際套用
- RLS／function privileges 實際查驗
- `EXPLAIN (ANALYZE, BUFFERS)`
- validation SQL
- rollback SQL

因此不能宣稱 RPC 已在真實 PostgreSQL／PostgREST 上通過。

### 4.2 完整瀏覽器測試未執行

Playwright 成功發現 61 個測試，但容器缺少 Chromium／WebKit browser binaries，不能宣稱 E2E 測試通過。線上 CI 已設定先安裝 browser runtime 再執行。

### 4.3 部分安全工具未完成本機實掃

- `pip-audit` 可啟動，但容器 DNS 無法連線至 PyPI vulnerability service，因此未完成漏洞查詢。
- Biome、actionlint、Gitleaks 的固定版本 binary 不在本機，外部下載亦受 DNS 限制。
- 它們已加入 required online CI，但本地結果不可標示為通過。

### 4.4 遠端控制未驗證

尚未確認：

- GitHub branch protection 是否要求 `test-gate`。
- Staging／Production 真實 migration history。
- RPC 與 rate-limit migration 是否已套用。
- Edge Function 是否已更新。
- Vercel Preview／Production 是否實際回傳新安全標頭。
- CSP 是否對正式 Auth、Sentry、所有 iPhone 流程無回歸。

## 五、建議部署流程

### 5.1 GitHub PR

1. 將修正版建立為單一 P1 PR。
2. 確認 `Project tests / Test gate` 通過。
3. 確認 quality-security 內所有線上工具實際通過，包括 pip-audit、Biome、Deno、actionlint 與 Gitleaks。
4. 將 `test-gate` 設為 main branch required check。

### 5.2 Supabase Local

1. 啟動 Docker。
2. 執行完整 local reset 與 schema lint。
3. 執行 RPC validation SQL。
4. 使用代表性的 1,068 筆 prediction／8,544 筆 gate 資料量測：
   - RPC latency
   - response bytes
   - PostgreSQL CPU／buffers
   - Edge wall-clock
   - timeout margin
5. 執行 rollback，再重新套用，確認可逆。

### 5.3 核對遠端 migration history

Manifest 只記錄 Staging／Production 最後確認到第 31 個 migration。Repository 有 36 個，存在 5 個尚未由本修補重新確認的檔案。

不得直接使用：

```text
supabase db push --include-all
```

也不得盲目 repair。必須逐一比對遠端 schema／history，只部署確定尚未套用的 migration。

### 5.4 Staging

1. 先套用並驗證 `20260720190000_prediction_snapshot_read_rpc.sql`。
2. 若啟用 P0 rate limit，再套用並驗證 `20260720170000_prediction_snapshot_rate_limit.sql`。
3. 設定 `PREDICTION_SNAPSHOT_READ_MODE=rpc`。
4. 初始可維持 `PREDICTION_RATE_LIMIT_ENABLED=false`，完成可信 client-address header 驗證後再啟用。
5. 透過 GitHub workflow 部署 Edge Function，輸入 `rpc_migration_verified=true`。
6. 比較 RPC 與 legacy payload，確認 schema、筆數、排序與 hash 語意一致。
7. 壓測 200／429／503／504、request ID 與 structured logs。
8. 在 Vercel Preview 驗證 CSP、Auth、Supabase WebSocket、Sentry、行動版與 200% 大字流程。

### 5.5 Production

只有在 Staging、線上 CI、browser tests、migration rollback、live headers 與 branch protection 全部通過後，才合併並發布 Production。

## 六、回復策略

### Snapshot RPC

若 RPC 在 Staging／Production 有效能或相容問題：

1. 將 Edge Function 環境變數改為：
   ```text
   PREDICTION_SNAPSHOT_READ_MODE=legacy
   ```
2. 重新部署 Edge Function。
3. 確認 public snapshot 恢復後，再評估是否執行 rollback SQL 移除 RPC 與 lookup index。

Legacy 是緊急回復路徑，會恢復較多 PostgREST 往返，不應長期使用。

### Vercel CSP

若 Preview 發現必要資源遭 CSP 阻擋，應先精確新增必要來源，不得直接加入 `'unsafe-inline'` 或 `*`。若 Production 已受影響，可回復到上一個已驗證 Vercel deployment，再修正 `vercel.json`。

### CI

若新工具造成非程式碼本身的 registry outage，應保留 required gate 並修正重試／快取策略，不應移除掃描器或把失敗改為 `continue-on-error`。

## 七、剩餘風險

1. 單一 RPC 降低網路往返，但尚未取得真實 execution plan 與 Staging 延遲資料。
2. 4 秒 database timeout 是否足夠，需依 Staging P95／P99 決定。
3. CSP 尚未直接驗證正式 response headers 與完整瀏覽器流程。
4. Remote branch protection 尚未設為已確認。
5. 研究模型仍未優於 20 日動能基準，locked holdout 尚未執行，不能升級為正式投資推薦。
6. P0 rate limiting 仍預設關閉，必須先確認 Edge 平台提供不可由用戶偽造的 client-address header。

## 八、交付判定

- P1 原始碼修復：**完成**
- Repository 靜態／單元回歸：**通過**
- 真實 Supabase migration：**未執行**
- 完整 Playwright browser run：**未執行**
- 線上 security scanner：**待 GitHub CI**
- Staging：**未部署**
- Production：**未部署**
- 模型狀態：**`RESEARCH_ONLY`，未變更**
