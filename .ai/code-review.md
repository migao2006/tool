# 程式審查與安全清理規範

## 審查順序

1. 確認需求、輸入輸出、時間語意與受影響範圍。
2. 檢查資料洩漏、權限、機密、RLS、錯誤處理與不可回復操作。
3. 檢查依賴方向、重複邏輯、公開契約與向後相容性。
4. 檢查測試是否涵蓋失敗、空資料、stale、hard fail 與 unsupported horizon。
5. 檢查 Git diff、未追蹤檔、產生物、意外刪除與文件同步。

## 金融與資料檢查

- `available_at <= decision_at` 必須能稽核；無時區 datetime 不得進入對齊流程。
- 同一 decision date 不得拆到不同 fold，label entry/exit window 必須 purge。
- 排名 query 是完整日期橫截面，不是股票代號。
- 成本包含雙邊手續費、最低費用、賣出稅、spread、slippage、impact 與容量。
- Hard fail 不得進入正式推薦；研究結果不得包裝成正式績效。

## 刪檔證據

刪除 tracked file 前，依適用情況檢查：

- import、文字引用、連結、設定、package script 與命令使用。
- CI workflow、部署設定、test config、migration、排程與 runtime entry point。
- glob、目錄掃描、動態 import、檔名慣例及 vendored runtime 載入。
- `git log -- <path>`、替代檔案與歷史目的。

只有具合理證據證明不再需要時才能刪除。用途不明、證據不足、屬歷史紀錄或可能由動態載入使用時必須保留，記錄缺少證據與下一步。

不得以 broad recursive delete 清理 repository。每次先列出精確目標；不得刪除 repository 外內容、正式資料、remote object、branch、release、deployment history 或使用者 secret。

## 受保護內容

除非替代方案已確認且有明確理由，不得刪除 entry point、migration、schema、lockfile、法律或安全文件、Production 設定、workflow、`.env.example`、模型與資料 artifact、provenance、歷史決策、完成任務紀錄及動態載入檔案。

## Migration 審查

下列視為高風險：大表鎖定、NOT NULL、unique/foreign key、型別轉換、大量 backfill、RLS/Auth 變更及無法安全回復的操作。必須檢查 migration history、非正式環境結果、向後相容性與 rollback。

## 完成報告

只列實際執行結果。刪除項目逐檔記錄原因、reference checks、replacement 與驗證；不刪除候選記錄風險、缺少證據與建議驗證。最後列出刪除檔案數、移除目錄數、`.gitignore` 變更及保留候選數。
