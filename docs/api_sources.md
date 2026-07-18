# 5 日 MVP 資料 API

本專案只保存真實回應及來源追蹤資訊。API 缺漏、憑證未設定或回應格式錯誤時，必須回報
`RESEARCH_ONLY`／`FAIL`，不得產生假行情或假預測。

## 已加入的來源

| 來源 | 模組 | 主要資料 | 憑證 |
|---|---|---|---|
| TWSE | `src/data/providers/twse.py` | 上市行情、指數、交易日、融資融券、交易狀態 | 不需要 |
| TPEx | `src/data/providers/tpex.py` | 上櫃行情、櫃買指數、法人、融資融券、處置資訊 | 不需要 |
| MOPS | `src/data/providers/mops.py` | 公司資料、月營收、資產負債表、綜合損益表 | 不需要 |
| FinMind | `src/data/providers/finmind.py` | 多年行情、籌碼、財報、公司行動與下市資料 | `FINMIND_TOKEN` |
| TAIFEX | `src/data/providers/taifex.py` | 期貨、選擇權、Put/Call 與法人部位 | 不需要 |
| TDCC | `src/data/providers/tdcc.py` | 證券基本資料與集保股權分散 | 不需要 |
| Fugle | `src/data/providers/fugle.py` | 未還原／還原歷史日 K 與成交金額 | `FUGLE_API_KEY` |
| 中央銀行 | `src/data/providers/cbc.py` | 匯率、利率與貨幣統計資料集 | 不需要 |
| Alpha Vantage | `src/data/providers/alpha_vantage.py` | 美國殖利率、利率、通膨、就業與 GDP | `ALPHA_VANTAGE_API_KEY` |
| Twelve Data | `src/data/providers/twelve_data.py` | 美股、指數、商品及匯率日資料 | `TWELVE_DATA_API_KEY` |

MOPS 不直接解析網站 HTML，而是使用 TWSE／TPEx OpenAPI 正式發布的 MOPS 資料集。

## 安全設定

複製 `.env.example` 只能作為本機欄位清單；實際正式金鑰應放在 GitHub Repository Secrets：

```text
FINMIND_TOKEN
FUGLE_API_KEY
ALPHA_VANTAGE_API_KEY
TWELVE_DATA_API_KEY
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
```

`SUPABASE_SERVICE_ROLE_KEY` 只能由 GitHub Actions／後端寫入程序使用，不得出現在前端、日誌、
錯誤訊息或 Git 紀錄。公開前端繼續使用 Supabase publishable key。
此環境變數同時支援新版 `sb_secret_...` 與舊版 JWT `service_role`。新版 secret key 只放在
`apikey` header；只有舊版 JWT 才會放入 `Authorization: Bearer`。

Supabase Data API 設定必須將 `market_data` 加入 **Exposed schemas**，否則 PostgREST 無法選取該
schema。資料庫 migration 已撤銷 `anon`／`authenticated` 對內部研究表的權限，只授權
`service_role`；加入 Exposed schemas 不代表開放給瀏覽器。

## 健康檢查

只檢查設定，不發出請求：

```powershell
.venv\Scripts\python.exe -m scripts.check_data_apis
```

執行小型真實請求；缺少憑證的來源會顯示 `NOT_CONFIGURED`，不會使用假資料：

```powershell
.venv\Scripts\python.exe -m scripts.check_data_apis --live
```

GitHub Actions 在台灣交易日晚上執行相同檢查。未設定的私有來源維持 `RESEARCH_ONLY`；
已設定來源若連線或契約失敗則工作失敗。

單獨下載一份真實原始資料並保存來源追蹤資訊：

```powershell
.venv\Scripts\python.exe -m scripts.fetch_api_data TWSE `
  --dataset daily_bars `
  --output data/raw/twse_daily_bars.json
```

輸出路徑 `data/raw/` 已排除於 Git，不會把大量原始行情提交到程式庫。

## 時間對齊

- 每個原始回應都保存 HTTPS 來源、資料集版本、UTC 取得時間與 SHA-256。
- 取得時間不等同資料的 `available_at`；正規化匯入時仍須依官方發布時間決定。
- Alpha Vantage 不提供 ALFRED 式歷史 vintage；原始回應只能以 `retrieved_at` 作為
  `available_at` 下限，必須每日保存快照，禁止用最新修正值回填歷史特徵。
- Twelve Data 的美國市場收盤資料必須在台灣 `decision_at` 已經可取得後才可加入特徵。
- MOPS 財報及營收使用公告／建立時間，不使用季度結束日或營收所屬月份冒充發布時間。

## 可補強的官方免費來源

下列來源尚未加入 provider registry，不得在完成介面與測試前視為正式資料來源：

- 美國財政部 Daily Treasury Rates：補強每日名目與實質殖利率，不需 API key。
- BLS Public Data API：補強 CPI、失業率與非農就業；V2 使用免費註冊 key。
- BEA Data API：補強 GDP、PCE 與國民所得帳；使用免費註冊 key。
- New York Fed Markets Data API：補強 EFFR、SOFR 等每日參考利率。
- EIA Open Data API：補強原油、天然氣及能源庫存；使用免費註冊 key。
