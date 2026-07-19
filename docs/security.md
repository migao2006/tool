# Auth 與安全規範

> 2026-07-19 已依目前原生 JavaScript 前端、Supabase Auth 與 Sentry 設定核對。此文件描述安全契約，不代表 prediction／watchlist 後端已正式上線；現況見 [`current-status.md`](current-status.md)。

## 一、Auth

只使用 Supabase Email＋密碼，支援：

- 建立帳號
- Email 確認
- 登入
- Session 恢復
- 登出

Auth UI、controller、service 及樣式必須分離。

Supabase SDK 使用本地 vendored 固定版本，必須透過單一共用 Promise 初始化；目前最多嘗試兩次，之後 fail closed。

Resend 已移除。第一版不提供忘記密碼／重設密碼 UI；若產品公開使用或保存重要個人資料，必須重新評估安全的帳號復原流程。

## 二、Key 與機密

前端只能使用 Supabase publishable key。

禁止在前端、Git 或 logs 中放置：

- `service_role`
- Database password
- Secret key
- 硬編碼、輸出或記錄 Access token
- 硬編碼、輸出或記錄 Refresh token
- 私鑰
- `FINMIND_TOKEN`、`FINMIND_TOKEN_SECONDARY`、`FINMIND_TOKEN_TERTIARY`
- `R2_ACCESS_KEY_ID`、`R2_SECRET_ACCESS_KEY`

FinMind、R2 與 Supabase server-side secret 只能由 GitHub Actions 或後端 service 使用。前端不得
直接讀取 private R2 object；R2 credential 必須限制在本專案 archive bucket 的最小權限。

Supabase URL、publishable key 與 Sentry DSN 是公開客戶端設定，不得誤稱為 server secret。Supabase SDK 可以在瀏覽器安全管理 session；access token 只可由第一方 prediction／watchlist API 的 `Authorization` header 傳送，不得送往其他服務或寫入 log。refresh token 只交由 Supabase SDK 管理。

個人資料表必須啟用 RLS。Policy 使用 `TO authenticated` 並以 `(select auth.uid()) = user_id` 限制資料擁有者；UPDATE 同時需要 `USING` 與 `WITH CHECK`。不得只靠 `TO authenticated` 形成可跨使用者存取的資料表。

目前尚未有自選股持久化 table migration 或正式 prediction／watchlist backend；現有前端介面不得被文件描述成已完成正式儲存。

## 三、Sentry 隱私

- `sendDefaultPii=false`。
- `beforeSend` 移除 `event.user`、URL query 與 hash。
- 不得把 Email、token、密碼、API key、原始行情內容或資料庫回應送入錯誤 context。

登入或資料庫不可用時，顯示真實原因並停用不可能成功的操作，不得模擬成功。
