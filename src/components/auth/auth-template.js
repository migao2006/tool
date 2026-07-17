export const authTitles = Object.freeze({
  signin: "登入",
  signup: "建立帳號",
  otpRequest: "驗證碼登入",
  otpVerify: "輸入驗證碼",
  forgot: "忘記密碼",
  recovery: "設定新密碼",
  account: "帳戶",
});

export function createAccountEntryMarkup() {
  return `
    <button class="auth-account-button" type="button" data-auth-open aria-haspopup="dialog">
      <span class="auth-account-icon" aria-hidden="true"></span>
      <span data-auth-account-label>登入</span>
    </button>`;
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
            <button type="button" data-auth-view-target="forgot">忘記密碼</button>
            <button type="button" data-auth-view-target="signup">建立帳號</button>
          </div>
          <div class="auth-divider"><span>或</span></div>
          <button class="auth-secondary" type="button" data-auth-view-target="otpRequest">使用 Email 驗證碼</button>
        </section>

        <section class="auth-view" data-auth-view="signup" hidden>
          <form data-auth-form="signup">
            <label class="auth-field"><span>Email</span><input name="email" type="email" autocomplete="email" required /></label>
            <label class="auth-field"><span>密碼</span><input name="password" type="password" autocomplete="new-password" minlength="8" required /></label>
            <label class="auth-field"><span>確認密碼</span><input name="passwordConfirm" type="password" autocomplete="new-password" minlength="8" required /></label>
            <button class="auth-primary" type="submit" data-auth-submit>建立帳號</button>
          </form>
          <button class="auth-back" type="button" data-auth-view-target="signin">返回登入</button>
        </section>

        <section class="auth-view" data-auth-view="otpRequest" hidden>
          <p class="auth-description">我們會寄送 6 位數驗證碼。</p>
          <form data-auth-form="otpRequest">
            <label class="auth-field"><span>Email</span><input name="email" type="email" autocomplete="email" required /></label>
            <button class="auth-primary" type="submit" data-auth-submit>寄送驗證碼</button>
          </form>
          <button class="auth-back" type="button" data-auth-view-target="signin">返回登入</button>
        </section>

        <section class="auth-view" data-auth-view="otpVerify" hidden>
          <p class="auth-description">驗證碼已寄到 <strong data-auth-pending-email></strong></p>
          <form data-auth-form="otpVerify">
            <label class="auth-field"><span>6 位數驗證碼</span><input class="auth-code" name="token" type="text" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" maxlength="6" required /></label>
            <button class="auth-primary" type="submit" data-auth-submit>驗證並登入</button>
          </form>
          <button class="auth-back" type="button" data-auth-view-target="otpRequest">重新寄送</button>
        </section>

        <section class="auth-view" data-auth-view="forgot" hidden>
          <p class="auth-description">輸入帳號 Email，我們會寄送密碼重設連結。</p>
          <form data-auth-form="forgot">
            <label class="auth-field"><span>Email</span><input name="email" type="email" autocomplete="email" required /></label>
            <button class="auth-primary" type="submit" data-auth-submit>寄送重設信</button>
          </form>
          <button class="auth-back" type="button" data-auth-view-target="signin">返回登入</button>
        </section>

        <section class="auth-view" data-auth-view="recovery" hidden>
          <form data-auth-form="recovery">
            <label class="auth-field"><span>新密碼</span><input name="password" type="password" autocomplete="new-password" minlength="8" required /></label>
            <label class="auth-field"><span>確認新密碼</span><input name="passwordConfirm" type="password" autocomplete="new-password" minlength="8" required /></label>
            <button class="auth-primary" type="submit" data-auth-submit>儲存新密碼</button>
          </form>
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
