export const authTitles = Object.freeze({
  signin: "登入",
  signup: "建立帳號",
  account: "帳戶",
});

export function createAccountEntryMarkup() {
  return `
    <div class="auth-entry-card">
      <div class="auth-entry-copy">
        <strong data-auth-entry-title>登入後使用自選股</strong>
        <small data-auth-entry-detail>同步自選清單、持倉與模型警示</small>
      </div>
      <button class="auth-account-button" type="button" data-auth-open aria-haspopup="dialog">
        <span class="auth-account-icon" aria-hidden="true"></span>
        <span data-auth-account-label>登入</span>
      </button>
    </div>`;
}

export function createAuthDialogMarkup() {
  return `
    <dialog class="auth-dialog" data-auth-dialog aria-labelledby="auth-dialog-title">
      <div class="auth-sheet">
        <header class="auth-header">
          <div><small>Alpha Lens</small><h2 id="auth-dialog-title">登入</h2></div>
          <button class="auth-close" type="button" data-auth-close aria-label="關閉">×</button>
        </header>
        <p class="auth-status" data-auth-status role="status" hidden></p>

        <section class="auth-view" data-auth-view="signin">
          <form data-auth-form="signin">
            <label class="auth-field"><span>Email</span><input name="email" type="email" autocomplete="email" required /></label>
            <label class="auth-field"><span>密碼</span><input name="password" type="password" autocomplete="current-password" required /></label>
            <button class="auth-primary" type="submit" data-auth-submit>登入</button>
          </form>
          <div class="auth-link-row">
            <button type="button" data-auth-view-target="signup">建立帳號</button>
          </div>
        </section>

        <section class="auth-view" data-auth-view="signup" hidden>
          <p class="auth-description">建立後需點擊 Supabase 寄送的確認連結。</p>
          <form data-auth-form="signup">
            <label class="auth-field"><span>Email</span><input name="email" type="email" autocomplete="email" required /></label>
            <label class="auth-field"><span>密碼</span><input name="password" type="password" autocomplete="new-password" minlength="8" required /></label>
            <label class="auth-field"><span>確認密碼</span><input name="passwordConfirm" type="password" autocomplete="new-password" minlength="8" required /></label>
            <button class="auth-primary" type="submit" data-auth-submit>建立帳號</button>
          </form>
          <button class="auth-back" type="button" data-auth-view-target="signin">返回登入</button>
        </section>

        <section class="auth-view auth-account-view" data-auth-view="account" hidden>
          <span class="auth-large-icon" aria-hidden="true"></span>
          <strong data-auth-account-email>—</strong>
          <p>登入狀態會安全保留在這台裝置。</p>
          <button class="auth-secondary" type="button" data-auth-signout>登出</button>
        </section>
      </div>
    </dialog>`;
}
