import {
  authTitles,
  createAccountEntryMarkup,
  createAuthDialogMarkup,
} from "./auth-template.js";

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
    this.bindEvents();
  }

  bindEvents() {
    this.entryRoot.addEventListener("click", () => {
      this.open(this.user ? "account" : "signin");
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
    this.dialog.addEventListener("close", () => {
      document.body.classList.remove("auth-modal-open");
    });
  }

  onSubmit(handler) {
    this.submitHandler = handler;
  }

  onSignOut(handler) {
    this.signOutHandler = handler;
  }

  open(view = "signin") {
    this.showView(view);
    if (!this.dialog.open) {
      if (typeof this.dialog.showModal === "function") {
        this.dialog.showModal();
      } else {
        this.dialog.setAttribute("open", "");
      }
    }
    document.body.classList.add("auth-modal-open");
  }

  close() {
    if (!this.dialog.open) return;
    if (typeof this.dialog.close === "function") {
      this.dialog.close();
    } else {
      this.dialog.removeAttribute("open");
    }
    document.body.classList.remove("auth-modal-open");
  }

  showView(view) {
    this.clearMessage();
    this.root.querySelectorAll("[data-auth-view]").forEach((section) => {
      section.hidden = section.dataset.authView !== view;
    });
    this.title.textContent = authTitles[view] ?? "帳戶";
    if (!this.available && view !== "account") {
      this.showMessage("登入服務尚未完成連接。", "warning");
    }
  }

  setUser(user) {
    this.user = user;
    const label = this.entryRoot.querySelector("[data-auth-account-label]");
    const button = this.entryRoot.querySelector("[data-auth-open]");
    label.textContent = user ? "帳戶" : "登入";
    button.setAttribute("aria-label", user ? "開啟帳戶" : "開啟登入");
    this.root.querySelector("[data-auth-account-email]").textContent =
      user?.email ?? "—";
  }

  setAvailable(available) {
    this.available = available;
    this.updateSubmitState();
  }

  setBusy(busy) {
    this.busy = busy;
    this.updateSubmitState();
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

  setPendingEmail(email) {
    this.root.querySelector("[data-auth-pending-email]").textContent = email;
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
