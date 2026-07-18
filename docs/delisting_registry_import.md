# 官方下市事件登錄

這個匯入器只保存 TWSE 與 TPEx 官方公布的終止上市／上櫃事件，不會把舊代號直接連到今天的股票主檔。

## 資料來源

- TWSE OpenAPI：`/company/suspendListingCsvAndHtml`
- TPEx 官方網站 JSON：`/www/zh-tw/company/deListed`

TPEx 端點不在 OpenAPI Swagger 內，因此匯入器會嚴格檢查 `stat`、欄位名稱、廣告筆數與實際資料筆數。兩個來源都沒有逐筆公告時間。

## 時間契約

- `termination_date` 是事件生效日。
- `first_observed_at` 與 `available_at` 都是本專案實際擷取時間。
- `available_at_basis` 固定為 `FIRST_OBSERVED_AT_RETRIEVAL`。
- 歷史終止日期不得被誤當成歷史上已可取得的時間。

所以這些資料目前只能作身分研究，不能回放到第一次擷取以前的 point-in-time 訓練。

## 身分隔離

資料寫入 `market_data.delisting_registry_observations`，表內刻意沒有 `security_id`。匯入流程不會修改：

- `market_data.securities`
- `market_data.security_history`
- 任何歷史股票池或模型特徵

原因是代號可能重用、轉板或對應不同公司。取得足夠的歷史上市期間、統編或其他不可變識別證據前，`identity_resolution_status` 固定為 `UNRESOLVED`，系統狀態固定為 `RESEARCH_ONLY`。

## 執行

只抓取並驗證：

```powershell
python -m scripts.import_delisting_registry --dry-run
```

寫入 Supabase：

```powershell
python -m scripts.import_delisting_registry
```

正式寫入要求 `snapshot_date` 等於兩個來源在台北時區的實際擷取日期。GitHub workflow 的手動執行預設為 dry run，每週排程才會正式保存新觀測版本。

TWSE 與 TPEx 來源會先透過共用協調器受限平行抓取（全域最多 4、單一來源最多 2），
全部來源成功且通過驗證後才開始寫入，並固定依 TWSE、TPEx 順序產生結果。
