# 既定工程決策

本文件記錄不應在一般任務中反覆改變的跨模組決策。若需要推翻，先提出影響、遷移方式、回復方案與對應測試。

## 模型與資料

1. 排名模型是唯一個股排序來源；方向與分位數只做交易 gate，市場模型只控制總曝險，波動模型只控制風險與部位。
2. `final_score_model.py` 不得復活成另一套加權公式；相容層只能呼叫 `decision_policy`。
3. 正式交易路徑為盤後決策、下一交易日可成交開盤進場、持有 h 個交易日後收盤退出。
4. 財報、營收、事件與海外市場一律按實際 `available_at` 對齊，不按資料所屬期間回填。
5. 上市、上櫃與 ETF 分市場評估；ETF 使用獨立模型及成本設定。
6. 訓練、校準、測試與 locked holdout 依時間分離；所有 preprocessing 在 fold 內 fit。

## 儲存與發布

1. 多年原始行情以壓縮 Parquet 存 private Cloudflare R2，原始 object 預設 immutable。
2. Supabase 保存任務、manifest、稽核 metadata、Auth 與前端摘要，不重複保存同一份歷史原始列。
3. 未完成 PIT 身分、交易日曆、公司行動及交易狀態驗證的資料維持 `RAW_LANDING_ONLY / RESEARCH_ONLY`。
4. GitHub 是唯一人工發布入口；Vercel Production 只能由核准的 GitHub 流程觸發。
5. Production migration 必須版本化，先在隔離環境驗證並確認 rollback；高風險變更採 expand-and-contract。

## 安全與權限

1. 使用完成任務所需的最小專案級權限，不要求組織 owner、帳務或跨專案權限。
2. 可以確認 secret 名稱、作用環境與是否設定，但不得讀回、列舉或輸出明文。
3. 前端只使用 publishable key；個人資料表啟用 RLS 並以 `auth.uid()` 限制擁有者。
4. 不以停用 TLS、RLS、Auth、憑證驗證或錯誤監控解決問題。

## 工具與平台

- Python 使用 uv、Ruff、basedpyright、pytest；前端使用 pnpm、Biome、Playwright。
- GitHub CLI、Supabase CLI、Vercel CLI、Wrangler 與 Docker 依任務使用，但 CLI 可用不等於允許繞過發布閘門。
- Windows 憑證問題使用系統 CA；禁止 `strict-ssl=false` 或停用 TLS 驗證。
- 搜尋程式碼優先使用 `rg`；JSON/YAML 可使用 jq/yq。

## 變更紀錄原則

即時完成度只寫在 `docs/current-status.md` 與 model card。歷史決策、已完成任務報告與 provenance 不得因看似過時而刪除；若資訊相衝突，新增明確的 superseded 標記與指向，而不是改寫歷史。
