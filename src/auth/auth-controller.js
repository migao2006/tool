import { friendlyAuthError } from "../features/auth/auth-errors.js?v=auth-6";
import {
  hasAuthCallback,
  hasPasswordRecoveryIntent,
  readAuthCallbackError,
  sanitizeAuthCallbackUrl,
} from "../features/auth/auth-callback.js?v=auth-2";
import { installAuthRouteGuard } from "./auth-route-guard.js?v=auth-5";

const GENERIC_RESET_MESSAGE =
  "若此 Email 有帳號，密碼重設連結將會寄出；請同時檢查垃圾郵件匣。";

export class AuthController {
  constructor(dialog, service) {
    this.dialog = dialog;
    this.service = service;
    this.user = null;
    this.ready = false;
    this.recoveryMode = false;
  }

  async start() {
    this.dialog.onSubmit((action, formData) => this.handleSubmit(action, formData));
    this.dialog.onSignOut(() => this.signOut());
    installAuthRouteGuard(
      () => this.authState(),
      (reason) => this.showBlockedReason(reason),
    );

    const callbackError = readAuthCallbackError();
    const recoveryIntent = hasPasswordRecoveryIntent();
    if (!this.service) {
      this.dialog.setAvailable(false);
      this.setReady(true);
      if (callbackError || recoveryIntent) this.showRecoveryCallbackFailure(callbackError);
      return;
    }

    this.service.onAuthStateChange((event, session) => {
      this.handleAuthStateChange(event, session);
    });

    try {
      const { data, error } = await this.service.getSession();
      if (error) throw error;
      this.applyUser(data.session?.user ?? null);
      this.setReady(true);
      if (callbackError) {
        this.showRecoveryCallbackFailure(callbackError);
      } else if (recoveryIntent && !this.recoveryMode && !this.user) {
        this.showRecoveryCallbackFailure();
      } else if (hasAuthCallback() && !recoveryIntent) {
        sanitizeAuthCallbackUrl();
      }
    } catch (error) {
      this.setReady(true);
      if (recoveryIntent || callbackError) {
        this.showRecoveryCallbackFailure(callbackError ?? error);
      } else {
        this.dialog.showMessage(friendlyAuthError(error), "error");
      }
    }
  }

  handleAuthStateChange(event, session) {
    this.applyUser(session?.user ?? null);
    if (event === "PASSWORD_RECOVERY") {
      this.recoveryMode = true;
      this.dialog.setRecoveryMode(true);
      this.dialog.open("update-password");
      this.dialog.showMessage("重設連結已驗證，請設定新密碼。", "info");
      sanitizeAuthCallbackUrl();
      return;
    }
    if (hasAuthCallback() && ["INITIAL_SESSION", "SIGNED_IN", "USER_UPDATED"].includes(event)) {
      sanitizeAuthCallbackUrl();
    }
  }

  showRecoveryCallbackFailure(error = null) {
    this.recoveryMode = false;
    this.dialog.setRecoveryMode(false);
    this.dialog.open("forgot");
    this.dialog.showMessage(
      error ? friendlyAuthError(error) : "密碼重設連結無法驗證，請重新申請。",
      "error",
    );
    sanitizeAuthCallbackUrl();
  }

  applyUser(user) {
    const previousUserId = this.user?.id ?? null;
    this.user = user;
    this.dialog.setUser(user);
    if (this.ready) {
      document.body.dataset.authState = user ? "authenticated" : "anonymous";
      if (previousUserId !== (user?.id ?? null)) this.emitAuthState();
    }
  }

  setReady(ready) {
    const wasReady = this.ready;
    this.ready = ready;
    document.body.dataset.authState = !ready
      ? "pending"
      : this.service
        ? this.user
          ? "authenticated"
          : "anonymous"
        : "unavailable";
    if (ready && !wasReady) this.emitAuthState();
  }

  emitAuthState() {
    globalThis.dispatchEvent(new CustomEvent("alpha-lens:auth-change", {
      detail: { authenticated: Boolean(this.user) },
    }));
  }

  authState() {
    return { available: Boolean(this.service), ready: this.ready, user: this.user };
  }

  showBlockedReason(reason) {
    this.dialog.open("signin");
    if (reason === "unavailable") {
      this.dialog.showMessage("登入服務尚未完成連接。", "warning");
    } else if (reason === "pending") {
      this.dialog.showMessage("正在確認登入狀態，請稍候。", "info");
    } else {
      this.dialog.showMessage("請先登入後再使用自選股。", "info");
    }
  }

  async handleSubmit(action, formData) {
    if (!this.service) return;
    this.dialog.clearMessage();
    this.dialog.setBusy(true);

    try {
      await this.runAction(action, formData);
    } catch (error) {
      this.dialog.showMessage(friendlyAuthError(error), "error");
    } finally {
      this.dialog.setBusy(false);
    }
  }

  async runAction(action, formData) {
    const email = String(formData.get("email") ?? "").trim().toLowerCase();
    const password = String(formData.get("password") ?? "");
    const passwordConfirm = String(formData.get("passwordConfirm") ?? "");
    let response;

    switch (action) {
      case "signin":
        response = await this.service.signInWithPassword(email, password);
        this.throwIfError(response);
        this.applyUser(response.data.user);
        this.dialog.close();
        break;
      case "signup":
        this.assertPasswordConfirmation(password, passwordConfirm);
        response = await this.service.signUp(email, password);
        this.throwIfError(response);
        if (response.data.session) {
          this.applyUser(response.data.user);
          this.dialog.close();
        } else {
          this.dialog.showMessage(
            "確認信已寄出，請點擊信中的確認連結後再登入。",
            "success",
          );
        }
        break;
      case "request-reset":
        try {
          response = await this.service.resetPasswordForEmail(email);
          if (response.error) globalThis.Sentry?.captureException?.(response.error);
        } catch (error) {
          globalThis.Sentry?.captureException?.(error);
        }
        this.dialog.showMessage(GENERIC_RESET_MESSAGE, "success");
        break;
      case "update-password":
        if (!this.recoveryMode) throw new Error("password recovery session missing");
        this.assertPasswordConfirmation(password, passwordConfirm);
        response = await this.service.updatePassword(password);
        this.throwIfError(response);
        this.recoveryMode = false;
        this.dialog.setRecoveryMode(false);
        this.applyUser(response.data.user ?? this.user);
        this.dialog.showView("account");
        this.dialog.showMessage("密碼已更新。", "success");
        sanitizeAuthCallbackUrl();
        break;
      default:
        break;
    }
  }

  assertPasswordConfirmation(password, confirmation) {
    if (password !== confirmation) throw new Error("password mismatch");
    if (password.length < 8) throw new Error("password too short");
  }

  throwIfError(response) {
    if (response.error) throw response.error;
  }

  async signOut() {
    if (!this.service) return;
    this.dialog.setBusy(true);
    try {
      const response = await this.service.signOut();
      this.throwIfError(response);
      this.recoveryMode = false;
      this.dialog.setRecoveryMode(false);
      this.applyUser(null);
      this.dialog.close();
    } catch (error) {
      this.dialog.showMessage(friendlyAuthError(error), "error");
    } finally {
      this.dialog.setBusy(false);
    }
  }
}
