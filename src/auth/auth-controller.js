import { friendlyAuthError } from "../features/auth/auth-errors.js?v=auth-4";
import { installAuthRouteGuard } from "./auth-route-guard.js?v=auth-4";

export class AuthController {
  constructor(dialog, service) {
    this.dialog = dialog;
    this.service = service;
    this.user = null;
    this.ready = false;
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

    this.service.onAuthStateChange((_event, session) => {
      this.applyUser(session?.user ?? null);
    });

    try {
      const { data, error } = await this.service.getSession();
      if (error) throw error;
      this.applyUser(data.session?.user ?? null);
      this.setReady(true);
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
          this.dialog.showMessage(
            "確認信已寄出，請點擊信中的確認連結後再登入。",
            "success",
          );
        }
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
}
