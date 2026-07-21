# Auth 與安全規範

> 2026-07-21 已依目前原生 JavaScript 前端、Supabase Auth、Prediction Edge Function 與 Sentry 設定核對。Prediction 唯讀端點已接入；Watchlist 持久化仍未上線。現況見 [`current-status.md`](current-status.md)。

## 一、Auth

只使用 Supabase Email＋密碼，支援：

- 建立帳號
- Email 確認
- 登入
- Session 恢復
- 忘記密碼／寄送重設信
- 驗證 recovery callback 後更新密碼
- 登出

Auth UI、controller、service 及樣式必須分離。

Supabase SDK 使用本地 vendored 固定版本，必須透過單一共用 Promise 初始化；目前最多嘗試兩次，之後 fail closed。

密碼復原使用 Supabase Auth 的 PKCE 流程。前端只接受同源 `redirectTo`，必須由 Supabase Dashboard 的 Redirect URLs allowlist 明確允許；SDK 收到 `PASSWORD_RECOVERY` 事件並建立有效 session 後，才顯示更新密碼表單並呼叫 `updateUser`。重設信申請成功畫面一律使用通用訊息，不透露 Email 是否存在。callback query／fragment 中的 code、token 與錯誤內容在 SDK 處理後立即由 History API 清除，不寫入 log 或 Sentry。

正式對外寄信必須設定專用 SMTP、寄件網域驗證與合理 rate limit；Supabase 預設測試寄信服務不得視為正式交付保證。

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

目前尚未有自選股持久化 table migration 或 watchlist backend；`watchlistPersistenceEnabled` 必須維持 `false`，按鈕保持 disabled，資料層在讀取 session 或送出請求前回 `WATCHLIST_NOT_AVAILABLE`。Prediction 唯讀端點不得被誤寫成自選股已完成正式儲存。

## 三、Sentry 隱私

- `sendDefaultPii=false`。
- `beforeSend` 移除 `event.user`、URL query 與 hash。
- 不得把 Email、token、密碼、API key、原始行情內容或資料庫回應送入錯誤 context。

登入或資料庫不可用時，顯示真實原因並停用不可能成功的操作，不得模擬成功。

## 四、Prediction API 邊界保護

- 每個 request 具有可回傳的 `X-Request-Id`，log 只能保存低敏感度的結構化欄位，不得保存 token、原始 IP、Email、完整 URL query 或資料庫回應。
- 單次 PostgREST 查詢與整體 Edge Function request 必須各自設 deadline；timeout 時 fail closed，並回穩定錯誤碼。
- 公開 endpoint 的持久化限流由 service-role-only、`SECURITY INVOKER` RPC 原子更新。`anon` 與 `authenticated` 不得直接讀寫 rate-limit table 或執行 RPC。
- 資料庫只保存 opaque HMAC-SHA256 client key；該值由專用 server-side secret 與明確指定、經部署環境確認不可由外部用戶任意覆寫的 client-address header 產生。不得保存原始 client address，也不得把普通 SHA-256 誤稱為匿名化。HMAC key 仍屬可連結的營運識別碼，必須限制保存期限與存取權限。
- `PREDICTION_RATE_LIMIT_ENABLED` 預設關閉。只有在 migration、privilege validation、rollback 演練與專用 HMAC secret 都完成後才能開啟；開啟後 rate-limit backend 異常不得 fail open。
