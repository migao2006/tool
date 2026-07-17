import { friendlyAuthError } from "../features/auth/auth-errors.js?v=auth-2";
import { installAuthRouteGuard } from "./auth-route-guard.js?v=auth-2";

export class AuthController {
  constructor(dialog, service) {
    this.dialog = dialog;
    this.service = service;
    this.user = null;
    this.pendingEmail = "";
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

    if (!this.service) {
      this.dialog.setAvailable(false);
      this.setReady(true);
      return;
    }

    this.service.onAuthStateChange((event, session) => {
      this.applyUser(session?.user ?? null);
      if (event === "PASSWORD_RECOVERY") {
        this.recoveryMode = true;
        this.dialog.open("recovery");
      }
    });

    try {
      const { data, error } = await this.service.getSession();
      if (error) throw error;
      this.applyUser(data.session?.user ?? null);
      this.setReady(true);
      this.handleRecoveryRedirect();
    } catch (error) {
      this.setReady(true);
      this.dialog.showMessage(friendlyAuthError(error), "error");
    }
  }

  applyUser(user) {
    this.user = user;
    this.dialog.setUser(user);
    if (this.ready) {
      document.body.dataset.authState = user ? "authenticated" : "anonymous";
    }
  }

  setReady(ready) {
    this.ready = ready;
    document.body.dataset.authState = !ready
      ? "pending"
      : this.service
        ? this.user
          ? "authenticated"
          : "anonymous"
        : "unavailable";
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

  handleRecoveryRedirect() {
    const requested =
      new URLSearchParams(window.location.search).get("auth") === "recovery";
    if (!requested) return;

    window.setTimeout(() => {
      if (this.recoveryMode) return;
      this.dialog.open("forgot");
      this.dialog.showMessage("密碼重設連結無效或已過期，請重新寄送。", "error");
      this.clearRecoveryQuery();
    }, 600);
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
        if (password !== passwordConfirm) throw new Error("password mismatch");
        response = await this.service.signUp(email, password);
        this.throwIfError(response);
        if (response.data.session) {
          this.applyUser(response.data.user);
          this.dialog.close();
        } else {
          this.dialog.showMessage("確認信已寄出，請前往信箱完成驗證。", "success");
        }
        break;
      case "otpRequest":
        response = await this.service.sendOtp(email);
        this.throwIfError(response);
        this.pendingEmail = email;
        this.dialog.setPendingEmail(email);
        this.dialog.showView("otpVerify");
        this.dialog.showMessage("驗證碼已寄出。", "success");
        break;
      case "otpVerify":
        response = await this.service.verifyOtp(
          this.pendingEmail,
          String(formData.get("token") ?? "").trim(),
        );
        this.throwIfError(response);
        this.applyUser(response.data.user);
        this.dialog.close();
        break;
      case "forgot":
        response = await this.service.sendPasswordReset(email);
        this.throwIfError(response);
        this.dialog.showMessage("密碼重設信已寄出，請檢查信箱。", "success");
        break;
      case "recovery":
        if (password !== passwordConfirm) throw new Error("password mismatch");
        response = await this.service.updatePassword(password);
        this.throwIfError(response);
        this.clearRecoveryQuery();
        this.dialog.showMessage("新密碼已儲存。", "success");
        window.setTimeout(() => this.dialog.close(), 700);
        break;
      default:
        break;
    }
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
      this.applyUser(null);
      this.dialog.close();
    } catch (error) {
      this.dialog.showMessage(friendlyAuthError(error), "error");
    } finally {
      this.dialog.setBusy(false);
    }
  }

  clearRecoveryQuery() {
    const url = new URL(window.location.href);
    url.searchParams.delete("auth");
    window.history.replaceState(window.history.state, "", url);
  }
}
