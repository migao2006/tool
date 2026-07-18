# Auth 與安全規範

## 一、Auth

只使用 Supabase Email＋密碼，支援：

- 建立帳號
- Email 確認
- 登入
- Session 恢復
- 登出

Auth UI、controller、service 及樣式必須分離。

Supabase SDK 必須透過單一共用 Promise 初始化；失敗只能有限次重試，之後 fail closed。

## 二、Key 與機密

前端只能使用 Supabase publishable key。

禁止在前端、Git 或 logs 中放置：

- `service_role`
- Database password
- Secret key
- Access token
- Refresh token
- 私鑰
- `FINMIND_TOKEN`、`FINMIND_TOKEN_SECONDARY`、`FINMIND_TOKEN_TERTIARY`
- `R2_ACCESS_KEY_ID`、`R2_SECRET_ACCESS_KEY`

FinMind、R2 與 Supabase server-side secret 只能由 GitHub Actions 或後端 service 使用。前端不得
直接讀取 private R2 object；R2 credential 必須限制在本專案 archive bucket 的最小權限。

個人資料表必須啟用 RLS，並以 `auth.uid()` 限制資料擁有者。

登入或資料庫不可用時，顯示真實原因並停用不可能成功的操作，不得模擬成功。
