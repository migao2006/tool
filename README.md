# Alpha Lens

台股 5 個交易日短波段選股 MVP。系統以橫截面排名為核心，不預測精確未來股價；目前狀態為 `RESEARCH_ONLY`，尚無正式候選股、模型績效或回測結果。

## 目前狀態

- 最新已核對現況：[`docs/current-status.md`](docs/current-status.md)
- Release／部署證據邊界：[`docs/release-state.md`](docs/release-state.md)
- 模型卡：[`model_card.md`](model_card.md)／[`model_card.json`](model_card.json)
- 正式產品 horizon：`5`
- 2／3／10 日：未發布，不能用 5 日模型代替
- 原始歷史行情：private Cloudflare R2 的 ZSTD Parquet
- 任務、manifest、稽核 metadata 與 UI 摘要：Supabase
- 排程與發布入口：GitHub Actions；不直接以 Vercel CLI 發布 Production
- Owner 一鍵每日完整更新：[`docs/manual-full-update.md`](docs/manual-full-update.md)

代理工作規範以根 [`AGENTS.md`](AGENTS.md) 為入口；目前 Work Package 位於
[`tasks/active/TASK.md`](tasks/active/TASK.md)，跨 session 精簡狀態位於
[`.codex/CONTINUITY.md`](.codex/CONTINUITY.md)。詳細架構、產品、既定決策與審查規則
位於 [`.ai/`](.ai/)，驗證程序位於
[`.agents/skills/repository-verification/SKILL.md`](.agents/skills/repository-verification/SKILL.md)。

## 文件索引

核心規範：

- [`AGENTS.md`](AGENTS.md)：穩定代理權限、安全邊界與 Work Package 完成條件
- [`tasks/README.md`](tasks/README.md)：Active、Completed 與 task template 的責任邊界
- [`.codex/CONTINUITY.md`](.codex/CONTINUITY.md)：精簡跨 session 狀態（不授權）
- [`docs/product-ui.md`](docs/product-ui.md)：四頁 UI、顯示語意與狀態
- [`docs/architecture.md`](docs/architecture.md)：目錄、依賴與資料流
- [`docs/data-model.md`](docs/data-model.md)：point-in-time、模型、驗證與回測
- [`docs/security.md`](docs/security.md)：Supabase Auth、RLS 與機密
- [`docs/tooling-release.md`](docs/tooling-release.md)：工具、Git、migration 與發布閘門
- [`docs/local-development-tools.md`](docs/local-development-tools.md)：Windows 本機工具、`just`、`act` 與 `zizmor`
- [`docs/p1-repair-report-2026-07-20.md`](docs/p1-repair-report-2026-07-20.md)：P1 修復、驗證結果與部署限制

資料來源與匯入：

- [`docs/api_sources.md`](docs/api_sources.md)
- [`docs/data_import.md`](docs/data_import.md)
- [`docs/manual-full-update.md`](docs/manual-full-update.md)
- [`docs/historical_daily_bar_landing.md`](docs/historical_daily_bar_landing.md)
- [`docs/r2-historical-archive.md`](docs/r2-historical-archive.md)
- [`docs/historical_calendar_import.md`](docs/historical_calendar_import.md)
- [`docs/security_snapshot_import.md`](docs/security_snapshot_import.md)
- [`docs/corporate_action_import.md`](docs/corporate_action_import.md)
- [`docs/delisting_registry_import.md`](docs/delisting_registry_import.md)
- [`docs/benchmark_import.md`](docs/benchmark_import.md)

契約：

- [`docs/prediction_api_contract.md`](docs/prediction_api_contract.md)
- [`supabase/schema/README.md`](supabase/schema/README.md)

## 本機驗證

```powershell
uv sync --frozen --extra test
uv run pytest
pnpm install --frozen-lockfile
pnpm exec playwright install chromium
pnpm run test:e2e
python scripts/sync_release_manifest.py --check
```

`release-manifest.json` 是最新模型快照、平台強化狀態與 migration 證據邊界的單一來源；更新後執行
`python scripts/sync_release_manifest.py` 重新產生 `model_card.json`、模型卡、現況受管區段、
`docs/release-state.md` 與 manifest digest。CI／本機驗證使用 `--check` 防止文件漂移。未知的遠端 migration 狀態或發布 commit 必須保留為未確認，不得沿用舊值。

品質工具、Windows 憑證處理及完整發布規則請以 [`docs/tooling-release.md`](docs/tooling-release.md) 為準。任何測試成功都只代表程式驗證，不代表模型具備樣本外獲利能力。
