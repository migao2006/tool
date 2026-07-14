# 台灣股票公開資料稽核

核對日期：2026-07-14（Asia/Taipei）

系統以官方 Swagger、實際 JSON／CSV 欄位與來源自己的資料日期交叉檢查。HTTP 200 只代表請求成功，不代表資料是今天；每一類資料都保留 `date`、`period` 或 `availableAt`。

API 限制另以供應商目前文件核對：[FinMind Quick Start](https://finmind.github.io/quickstart/) 為無 Token 300 requests/hour、有 Token 600 requests/hour；[Supabase Edge Functions Limits](https://supabase.com/docs/guides/functions/limits) 的 Free plan wall-clock 上限為 150 秒；Vercel API Functions 的 `maxDuration: 300` 符合目前 [Vercel Functions Limits](https://vercel.com/docs/functions/limitations)。限制可能變動，調整批次前應重新查證，不應只依舊版註解。

## 當日全市場快照

| 資料 | 主要端點 | 程式用途 |
| --- | --- | --- |
| 上市行情 | TWSE `rwd/zh/afterTrading/MI_INDEX` | 指定最近交易日取得開高低收、量、金額與交易筆數 |
| 上市行情備援 | TWSE OpenAPI `/exchangeReport/STOCK_DAY_ALL` | 主行情失效時補足上市標的；不得用較舊日期覆蓋較新資料 |
| 上市估值 | TWSE `rwd/zh/afterTrading/BWIBBU_d` | 本益比、殖利率、股價淨值比 |
| 上市三大法人 | TWSE `rwd/zh/fund/T86` | 外資、投信、自營商與三大法人買賣超 |
| 上市融資融券 | TWSE `rwd/zh/marginTrading/MI_MARGN` | 融資、融券餘額及增減 |
| 上櫃行情 | TPEx `/tpex_mainboard_daily_close_quotes` | 上櫃開高低收、量、金額與交易筆數 |
| 上櫃估值 | TPEx `/tpex_mainboard_peratio_analysis` | 本益比、殖利率、股價淨值比 |
| 上櫃三大法人 | TPEx `/tpex_3insti_daily_trading` | 外資、投信、自營商與合計買賣超 |
| 上櫃融資融券 | TPEx `/tpex_mainboard_margin_balance` | 融資、融券餘額及增減 |
| 最新月營收 | TWSE `/opendata/t187ap05_L`、TPEx `/mopsfin_t187ap05_O` | 全市場初篩與最新期別核對 |
| 最新財報 | TWSE／TPEx `t187ap06`、`t187ap07` 六種格式 | 全市場初篩與最新季別核對 |

TPEx 法人欄位使用官方完整名稱，不以模糊位置猜測：

- `Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference`
- `SecuritiesInvestmentTrustCompanies-Difference`
- `Dealers-Difference`
- `TotalDifference`

## 歷史深度資料

有限候選池才透過 FinMind 公開資料逐檔取得：

| Dataset | 範圍 | 衍生用途 |
| --- | ---: | --- |
| `TaiwanStockPrice` | 18 個月，最多保留 280 個交易日 | 使用目前帳號可取得的上市／上櫃原始日線，再合併同日官方盤後報價；計算均線、斜率、突破、量能、ATR、RSI、MACD、KD與相對強弱。近 40 日超過 35% 的疑似公司行動跳空會停用技術評分，避免未還原價格誤判。`TaiwanStockPriceAdj` 因帳號權限會回 HTTP 400，已不再列為正式相依。 |
| `TaiwanStockTotalReturnIndex` | 8 個月，TAIEX／TPEx 各一次 | 官方指數 OpenAPI 少於 65 筆時，補足 20／60 日市場基準 |
| `TaiwanStockMonthRevenue` | 48 個月請求範圍 | 24～36 月完整度、YoY、MoM、YTD、3 月平均、加速度、同期／12 月新高、季節性、公布後反應 |
| `TaiwanStockFinancialStatements` | 52 個月 | 來源已為單季值；直接計算 8～12 季 EPS、營收、利潤率與業外品質，不再二次差分 |
| `TaiwanStockBalanceSheet` | 52 個月 | ROE、負債、流動比率、存貨與應收變化 |
| `TaiwanStockCashFlowsStatement` | 52 個月 | 年內累計值先轉單季，再合計近四季營業／自由現金流與 TTM 現金轉換 |
| `TaiwanStockInstitutionalInvestorsBuySell` | 3 個月 | 5／10／20 日法人累計、連買天數、買超占量 |
| `TaiwanStockMarginPurchaseShortSale` | 3 個月 | 融資使用率及 5／20 日融資融券變化 |
| `TaiwanStockSecuritiesLending` | 3 個月 | 借券資料的日期與近期量能摘要 |

排程中的 FinMind 請求不在同一批即時重送；失敗股票由後續批次依資料庫退避時間重試，避免極限流量下超出每小時限制。

## 交易風險與市場環境

| 市場 | 端點 | 用途 |
| --- | --- | --- |
| 上市 | `/announcement/punish` | 處置股票與有效期間 |
| 上市 | `/announcement/notice` | 注意股票 |
| 上市 | `/exchangeReport/TWT85U` | 變更交易方法等交易限制 |
| 上市 | `/exchangeReport/TWTAWU` | 停止／恢復交易資訊 |
| 上櫃 | `/tpex_disposal_information` | 處置股票 |
| 上櫃 | `/tpex_trading_warning_information` | 警示／注意資訊 |
| 上櫃 | `/tpex_cmode` | 交易方式變更 |
| 上櫃 | `/tpex_spendi_today` | 暫停／恢復交易資訊 |
| 上市指數 | `/indicesReport/MI_5MINS_HIST` | 大盤歷史趨勢與相對強弱 |
| 櫃買指數 | `/tpex_index` | 櫃買市場歷史趨勢與相對強弱 |

官方風險端點若缺漏，`coverageComplete` 會降低資料信心；不把「請求失敗」解讀成「沒有風險」。

## ETF 與集保

- TWSE `/opendata/t187ap47_L` 用於 ETF 類型、追蹤指數、成立／上市日、境外曝險及槓桿／反向辨識；方向只依基金名稱、備註與追蹤指數判斷，不把共用的「槓桿／反向」基金大類誤當實際方向。MIS `all_etf.txt` 補估計淨值與折溢價。
- TDCC `getOD.ashx?id=1-5` 是每週最後營業日的持股分級資料；只用於 400 張以上與 10 張以下結構，不當成每日買賣訊號。
- 追蹤誤差、完整內扣費用與成分股集中度若沒有已串接的穩定欄位，保留缺漏並降低信心，不拿公司月營收或 ROE 代替。

## 節流、重用與請求預算

| 來源 | 同時執行 | 最短間隔 |
| --- | ---: | ---: |
| FinMind | 2 | 0.5 秒啟動間隔；另有滑動 60 分鐘配額帳本 |
| TWSE OpenAPI | 2 | 1.25 秒 |
| TWSE 盤後介面 | 1 | 1.5 秒 |
| TPEx OpenAPI | 2 | 1.2～1.25 秒 |
| MOPS | 1 | 1.8 秒 |
| TDCC | 1 | 2 秒 |

GitHub 靜態快照直接匯出持久後端，不再建立第二套 FinMind 請求。市場基準與 TDCC 全市場資料由每日 universe 工作持久化。冷資料無 Token 每批最多 6／6／19、有 Token 最多 11／11／23；歷史可重用時公司批次可提高到 10／10 或 22／22。所有 FinMind 正式請求先在資料庫原子保留最近 60 分鐘額度，分別不超過 300 或 600，最後一批依剩餘額度裁切。新期別才重抓長歷史，錯誤由下一輪退避重試。

## 缺漏分類

- 季營業額原本已在資料表但摘要漏欄，屬程式錯誤，v16.3 已修正。
- TWSE 的當期月營收全市場表可能少於可交易公司母體；這是上游橫斷面覆蓋差異，不代表營收為 0。公司深度批次保留一半名額給 `revenue is null` 標的，改以逐檔 FinMind 月營收補回，且仍受同一個 300／600 滑動配額帳本限制。
- 若橫斷面缺漏、逐檔來源亦回空陣列，狀態為 `empty-no-history`／`source-not-returned`；HTTP 400、429、5xx 則另列 `upstream-error`，不會混成同一種缺漏。
- 金控／證券業的 `Income／收益` 與銀行的淨利息、淨非利息收益已改用正確欄位；少數保險業只有不可直接等同營業額的結果欄，明標「不具可比單一營業額」，不列為 API 失敗。
- `7714` 的 FinMind 月營收只有 20 個月，屬來源歷史覆蓋限制；保留實際月數並降低歷史信心。
- 融資額度為 0／註記 `OX` 屬不可融資，不列為 API 缺漏。
- 去年同期營收為 0 時，年增率數學上不適用；營業額仍正常顯示。
- 最新營收公布後未滿五個交易日屬等待期，不列為缺漏。
- 新 ETF 未滿 120 根日線屬客觀歷史不足，不進正式排行。

## 後端儲存稽核

| 表 | 保存內容 | 公開權限 |
| --- | --- | --- |
| `stock_master`、`stock_snapshots` | 全市場主檔、交易日初篩欄位與來源日期 | RLS + 只讀 |
| `stock_price_history` | 每檔最多 280 日 OHLCV | 只讀 |
| `stock_monthly_revenues` | 每檔最多 40 月營收 | 只讀 |
| `stock_quarterly_financials` | 每檔最多 12 季財務與單季化現金流 | 只讀 |
| `stock_institutional_flows`、`stock_margin_history` | 法人與融資融券歷史 | 只讀 |
| `stock_analysis_cache`、`opportunity_score_history` | 最新分析與點時分數 | 只讀 |
| `stock_sync_state` | 分組游標、處理數、錯誤與成功時間 | 只讀 |

上述公開市場資料表皆啟用 RLS，訪客與一般登入者沒有新增、修改或刪除權限。`data_sync_status` 是未使用的舊表名，fresh migration 不再依賴它；正式進度只讀 `stock_sync_state`。排程經 Vault 權杖呼叫 Edge Function，函式再以伺服器角色寫入。原始碼只包含 publishable key，不包含 service role key 或同步權杖。

## 日期與回測防線

- `public/data/latest.json` 可隨後端更新；`data/snapshots/YYYY-MM-DD.json` 使用 create-only 寫入，同一交易日一旦捕捉就不可覆寫。週末、休市日或後續資料修正不得把較晚資訊倒填進既有點時檔。
- 月營收使用 `availableAt`，財報以季度合理公告可用日切片；正式回測使用每日已保存的點時快照。
- 不足 25 個不同交易日不公布回測成果。
- `scripts/audit-live.mjs` 會核對主要端點日期、必要欄位及 6613 上櫃歷史日線；`npm test` 另驗證後端公開唯讀存取、已存歷史路由、單季損益、累計現金流差分、TTM 現金轉換、市場路由、引擎硬規則、缺漏重正規化、ETF 分榜與資料源失效備援。
