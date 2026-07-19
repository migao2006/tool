# Alpha Lens

台股 5 個交易日短波段選股 MVP。系統以橫截面排名為核心，不預測精確未來股價；目前狀態為 `RESEARCH_ONLY`，尚無正式候選股、模型績效或回測結果。

## 目前狀態

- 最新已核對現況：[`docs/current-status.md`](docs/current-status.md)
- 模型卡：[`model_card.md`](model_card.md)／[`model_card.json`](model_card.json)
- 正式產品 horizon：`5`
- 2／3／10 日：未發布，不能用 5 日模型代替
- 原始歷史行情：private Cloudflare R2 的 ZSTD Parquet
- 任務、manifest、稽核 metadata 與 UI 摘要：Supabase
- 排程與發布入口：GitHub Actions；不直接以 Vercel CLI 發布 Production

## 文件索引

核心規範：

- [`AGENTS.md`](AGENTS.md)：代理權限、產品邊界與完成條件
- [`docs/product-ui.md`](docs/product-ui.md)：四頁 UI、顯示語意與狀態
- [`docs/architecture.md`](docs/architecture.md)：目錄、依賴與資料流
- [`docs/data-model.md`](docs/data-model.md)：point-in-time、模型、驗證與回測
- [`docs/security.md`](docs/security.md)：Supabase Auth、RLS 與機密
- [`docs/tooling-release.md`](docs/tooling-release.md)：工具、Git、migration 與發布閘門

資料來源與匯入：

- [`docs/api_sources.md`](docs/api_sources.md)
- [`docs/data_import.md`](docs/data_import.md)
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
```

品質工具、Windows 憑證處理及完整發布規則請以 [`docs/tooling-release.md`](docs/tooling-release.md) 為準。任何測試成功都只代表程式驗證，不代表模型具備樣本外獲利能力。
