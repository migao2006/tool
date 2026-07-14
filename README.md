# 台股智選 v16 Ultimate

以台灣公開市場資料建立的 1～8 週機會股研究系統。核心不是把所有指標直接相加，而是依序執行：

1. 風險排除
2. 成長確認
3. 籌碼確認
4. 價量進場判斷
5. 估值與市場環境檢查
6. 點時快照回測

候選分數只是研究排序，不是買進訊號，也不保證未來報酬。

## v16 的關鍵改變

- 上市、上櫃、ETF 完全分榜，不互相比較。
- 公司股採 100 分制：成長 30、籌碼 25、技術價量 25、估值 10、市場／產業 10，風險最多扣 30 分。
- 缺少資料時移除該項權重並重正規化，不把缺漏當成 0 分；同時獨立顯示資料信心。
- 資料信心低於 70%、最終分數低於 60，或命中硬性風險規則時，不進正式排行榜。
- 月營收深度驗證使用 48 個月請求範圍，正式需求至少 24 個月；計算年增、月增、累計年增、3 月平均年增、加速度、連續加速、近 12 月新高、歷年同期新高、季節性與公布後價格反應。
- 價量深度驗證保留最多 280 筆日線，計算 MA 5／10／20／60／120／240、斜率、突破、量能結構、ATR、RSI、MACD、KD、相對市場強弱與過熱距離。
- 籌碼計算外資／投信／自營商 5／10／20 日累計、連買天數、買超占量、融資使用率及融資融券變化；TDCC 每週資料只用於持股結構，不當成每日訊號。
- 財務品質使用最多 12 季損益、資產負債及現金流，檢查 EPS、利潤率、ROE、現金轉換、FCF、存貨、應收、負債、流動比率與利息保障。
- 會識別營運加速型、籌碼轉強型、落後補漲型；不符合時標為綜合觀察型。
- 回測只使用當日已寫入的快照，至少累積 25 個交易日才公布；檢查 5／10／20 日報酬、超額報酬、勝率、最大有利走勢及最大回撤。

完整公式與欄位請見 [docs/METHODOLOGY.md](docs/METHODOLOGY.md)，資料稽核請見 [docs/API-AUDIT.md](docs/API-AUDIT.md)。

## 資料來源與用途

| 來源 | 用途 | 更新方式 |
| --- | --- | --- |
| TWSE 盤後介面／OpenAPI | 上市行情、估值、法人、融資融券、注意、處置、變更、停牌、市場指數、基金基本資料 | 當日快照 |
| TPEx OpenAPI | 上櫃行情、估值、法人、融資融券、注意、處置、變更、停牌、櫃買指數 | 當日快照 |
| MOPS 開放資料 | 最新月營收與六類財報快照 | 每月／每季 |
| FinMind 公開歷史資料 | 250 日價量、36 月營收、12 季財務／現金流、20 日法人與融資融券、TAIEX／TPEx 長期市場基準 | 逐檔、限速、每日排程 |
| TDCC 開放資料 | 每週集保戶股權分散 | 每週 |
| 原有 Supabase Edge | 歷史價格備援與既有使用者紀錄 | 備援 |

FinMind 請求使用單一佇列，預設每次啟動至少間隔 1.35 秒；4xx 不重送，429、逾時與 5xx 才有限次數退避重試。TWSE、TPEx、MOPS、TDCC 也各自排隊，不會無限制平行請求。月營收與財報期別未改變時會重用前一份分析，每日只刷新價量與籌碼；新期別或新候選才補抓歷史。

## 一次部署到 GitHub 與 Vercel

1. 將本專案的所有檔案上傳至 GitHub Repository，包含 `.github/`、`api/`、`public/`、`src/`、`scripts/`、`data/`。
2. 在 Vercel 選擇 **Add New → Project**，匯入 Repository。
3. Framework Preset 選 **Other**。
4. Root Directory 保持 `./`。
5. Build Command 使用 `npm run build`，Output Directory 使用 `public`。
6. 部署完成後，在 GitHub 的 **Actions** 頁面執行一次 **Update Taiwan market snapshot → Run workflow**。

每日排程在台北時間 22:30 執行。它會先更新有限候選池，再逐檔深度驗證，寫入 `public/data/latest.json` 與 `data/snapshots/YYYY-MM-DD.json`，最後提交變更；Vercel 會因 GitHub commit 自動重新部署。

### 選用的環境變數

`FINMIND_TOKEN` 不是程式啟動的必要條件；若有自己的 FinMind token，建議在 GitHub Repository 的 **Settings → Secrets and variables → Actions** 新增同名 Secret。不要把 token 寫進原始碼或提交到 GitHub。

## 本機操作

需要 Node.js 20 或更新版本。

啟動本機完整頁面與 API：

```sh
npm run dev
```

```sh
npm test
```

建立一次真實市場深度快照：

```sh
npm run update-data
```

本機快速試跑可縮小候選池：

```sh
SNAPSHOT_COMPANY_LIMIT=2 SNAPSHOT_ETF_LIMIT=3 npm run update-data
```

依已累積的每日快照重建無前視偏誤回測：

```sh
npm run backtest:snapshots
```

稽核目前各公開介面的日期與欄位：

```sh
npm run audit
```

## API

- `GET /api/market-data?type=stocks`
- `GET /api/market-data?type=revenue`
- `GET /api/market-data?type=financials`
- `GET /api/market-data?type=risks`
- `GET /api/market-data?type=benchmarks`
- `GET /api/market-data?type=etf-profiles`
- `GET /api/market-data?type=deep&symbol=2330&instrumentType=股票&market=上市`
- `GET /api/market-data?type=history&symbol=2330&months=12`
- `GET /api/market-data?type=sources`
- `GET /api/health`

加入 `refresh=1` 可略過伺服器短期快取；日常使用不應頻繁加入此參數。

## 目前不能假裝已取得的資料

部分 ETF 欄位沒有穩定且一致的免金鑰公開介面，包括即時淨值折溢價、追蹤誤差、完整內扣費用與成分集中度。v16 會顯示缺漏並降低 ETF 信心，不會拿公司基本面代替。

TDCC 公開下載檔提供目前一週的全市場持股級距；歷史趨勢必須靠每日快照逐週累積。產業 20 日相對強弱也必須靠持續快照建立，初期只使用市場指數與當日產業廣度。

## 免責聲明

本專案僅供資料研究與軟體示範，不構成投資建議、買賣邀約、報酬保證或任何受託管理。公開資料可能延遲、更正、缺漏或調整格式；使用者應在重要決策前回到原始公告核對。
