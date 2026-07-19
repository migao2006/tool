import {
  authTitles,
  createAccountEntryMarkup,
  createAuthDialogMarkup,
} from "./auth-template.js?v=auth-5";

export class AuthDialog {
  constructor(root, entryRoot) {
    root.innerHTML = createAuthDialogMarkup();
    entryRoot.innerHTML = createAccountEntryMarkup();

    this.root = root;
    this.entryRoot = entryRoot;
    this.dialog = root.querySelector("[data-auth-dialog]");
    this.status = root.querySelector("[data-auth-status]");
    this.title = root.querySelector("#auth-dialog-title");
    this.available = true;
    this.busy = false;
    this.user = null;
    this.submitHandler = () => {};
    this.signOutHandler = () => {};
    this.returnFocus = null;
    this.busyFocus = null;
    this.bindEvents();
  }

  bindEvents() {
    this.entryRoot.addEventListener("click", (event) => {
      const opener = event.target.closest("[data-auth-open]");
      if (!opener) return;
      this.open(this.user ? "account" : "signin", opener);
    });

    this.root.addEventListener("click", (event) => {
      if (this.busy) return;
      if (event.target.closest("[data-auth-close]")) this.close();
      if (event.target.closest("[data-auth-signout]")) this.signOutHandler();

      const viewButton = event.target.closest("[data-auth-view-target]");
      if (viewButton) this.showView(viewButton.dataset.authViewTarget);
    });

    this.root.addEventListener("submit", (event) => {
      const form = event.target.closest("[data-auth-form]");
      if (!form) return;
      event.preventDefault();
      if (this.busy) return;
      this.submitHandler(form.dataset.authForm, new FormData(form));
    });

    this.dialog.addEventListener("click", (event) => {
      if (!this.busy && event.target === this.dialog) this.close();
    });
    this.dialog.addEventListener("cancel", (event) => {
      if (this.busy) event.preventDefault();
    });
    this.dialog.addEventListener("close", () => {
      document.body.classList.remove("auth-modal-open");
      this.restoreFocus();
    });
  }

  onSubmit(handler) {
    this.submitHandler = handler;
  }

  onSignOut(handler) {
    this.signOutHandler = handler;
  }

  open(view = "signin", opener = document.activeElement) {
    const wasOpen = this.dialog.open;
    if (!wasOpen) this.returnFocus = opener instanceof HTMLElement ? opener : null;
    this.showView(view);
    if (!wasOpen) {
      if (typeof this.dialog.showModal === "function") {
        this.dialog.showModal();
      } else {
        this.dialog.setAttribute("open", "");
      }
    }
    document.body.classList.add("auth-modal-open");
    this.focusView(view);
  }

  close() {
    if (!this.dialog.open) return;
    if (typeof this.dialog.close === "function") {
      this.dialog.close();
    } else {
      this.dialog.removeAttribute("open");
      this.restoreFocus();
    }
    document.body.classList.remove("auth-modal-open");
  }

  focusView(view) {
    const activeView = this.root.querySelector(`[data-auth-view="${view}"]`);
    activeView?.querySelector("input, button:not(:disabled)")?.focus();
  }

  restoreFocus() {
    const target = this.returnFocus;
    this.returnFocus = null;
    if (!(target instanceof HTMLElement) || !target.isConnected) return;
    target.focus();
    window.requestAnimationFrame(() => {
      if (!this.dialog.open && target.isConnected) target.focus();
    });
  }

  showView(view) {
    this.clearMessage();
    this.root.querySelectorAll("[data-auth-view]").forEach((section) => {
      section.hidden = section.dataset.authView !== view;
    });
    this.title.textContent = authTitles[view] ?? "帳戶";
    if (this.dialog.open) this.focusView(view);
    if (!this.available && view !== "account") {
      this.showMessage("登入服務尚未完成連接。", "warning");
    }
  }

  setUser(user) {
    this.user = user;
    const label = this.entryRoot.querySelector("[data-auth-account-label]");
    const button = this.entryRoot.querySelector("[data-auth-open]");
    const title = this.entryRoot.querySelector("[data-auth-entry-title]");
    const detail = this.entryRoot.querySelector("[data-auth-entry-detail]");
    label.textContent = user ? "帳戶" : "登入";
    title.textContent = user ? "帳戶已連接" : "登入後使用自選股";
    detail.textContent = user?.email ?? "同步自選清單與模型警示";
    button.setAttribute("aria-label", user ? "開啟帳戶" : "開啟登入");
    this.root.querySelector("[data-auth-account-email]").textContent =
      user?.email ?? "—";
  }

  setAvailable(available) {
    this.available = available;
    this.updateSubmitState();
  }

  setBusy(busy) {
    if (busy && this.dialog.open) this.busyFocus = document.activeElement;
    this.busy = busy;
    this.dialog.setAttribute("aria-busy", String(busy));
    this.updateSubmitState();
    if (busy && this.dialog.open) {
      this.dialog.focus();
    } else if (!busy && this.dialog.open) {
      if (this.busyFocus instanceof HTMLElement && this.busyFocus.isConnected) {
        this.busyFocus.focus();
      } else {
        const view = this.root.querySelector("[data-auth-view]:not([hidden])")?.dataset.authView;
        if (view) this.focusView(view);
      }
    }
    if (!busy) this.busyFocus = null;
  }

  updateSubmitState() {
    this.root
      .querySelectorAll(
        "[data-auth-submit], [data-auth-view-target], [data-auth-close], [data-auth-signout]",
      )
      .forEach((button) => {
        const needsService = button.matches("[data-auth-submit]");
        button.disabled = this.busy || (needsService && !this.available);
      });
  }

  showMessage(message, tone = "info") {
    this.status.textContent = message;
    this.status.dataset.tone = tone;
    this.status.hidden = false;
  }

  clearMessage() {
    this.status.textContent = "";
    this.status.hidden = true;
    delete this.status.dataset.tone;
  }
}
