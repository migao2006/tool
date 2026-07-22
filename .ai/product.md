# 產品與顯示規範

正式產品只有四個使用者頁面：今日總覽、5 日候選股、個股決策詳情、自選股。底部導覽只顯示總覽、5 日候選、自選；個股詳情由股票項目進入。

## 產品範圍

- 第一版唯一正式 horizon 是 5；2、3、10 日不得顯示成可操作功能。
- API、型別與元件仍需接受 horizon；不支援值明確回傳 `UNSUPPORTED_HORIZON`。
- ETF 與普通股票分離，本版普通股票候選頁不顯示 ETF。
- 不新增管理員、自動下單、持倉損益或複雜投資組合頁面。
- 不顯示精確未來股價、虛構 AI 信心、未經 OOS 校準的 expected return 或獲利保證。

## 狀態語意

- 系統：`PASS`、`RESEARCH_ONLY`、`FAIL`。
- 個股決策：`CANDIDATE`、`WATCH`、`NO_TRADE`。
- 候選資格：`ELIGIBLE`、`EXCLUDED`。
- 資料品質：`PASS`、`WARN`、`HARD_FAIL`。

`HARD_FAIL` 必須進入 excluded 集合；系統為 `FAIL` 時不得產生 `CANDIDATE`。`WATCH` 不是正式推薦，`NO_TRADE` 也不代表資料錯誤。

## 顯示契約

- Rank Score 只表示當日橫截面排名百分位，不是機率、報酬、信心或勝率。
- P10/P50/P90 是條件報酬分位數，不是最低、平均、最高報酬或保證區間。
- 排序只能使用 rank model 的 Rank Score 或 global rank；前端不得建立 final score。
- 沒有真實值時顯示 `—`、尚無資料或尚未更新，不得使用假股票及 placeholder 數字。
- 所有頁面處理 loading、empty、stale、API error、hard fail、research only 與 fail。
- 重要狀態不得只靠顏色；觸控區至少 44×44 px，處理 iPhone safe area 與大字體。

## 個股決策順序

詳情頁依序顯示 data quality、tradability、liquidity/capacity、market exposure、calibrated probability、net quantile、rank eligibility、position limits。

每個 gate 顯示通過狀態、實際值、門檻、reason code 與來源日期。技術稽核資訊可以折疊，但不得刪除。

## Auth

Auth 使用 Supabase Email＋密碼，支援建立帳號、Email 確認、登入、session 恢復與登出。Auth UI、controller、service 與樣式分離；SDK 初始化失敗要 fail closed，不得模擬成功。

第一版不主動提供忘記密碼 UI；若公開使用或保存重要個人資料，需重新評估安全的帳號復原流程。完整細節見 `docs/product-ui.md` 與 `docs/security.md`。
