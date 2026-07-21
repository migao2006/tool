import { expect, test } from "@playwright/test";

async function installIsolatedAuth(
  page,
  { recovery = false, resetError = false } = {},
) {
  return page.evaluate(async ({ recovery, resetError }) => {
    if (recovery) {
      window.history.replaceState(
        {},
        "",
        "/contract-test?auth_action=password-recovery#access_token=test-token&refresh_token=test-refresh&type=recovery",
      );
    }
    const [{ AuthDialog }, { AuthController }] = await Promise.all([
      import("/src/components/auth/auth-dialog.js?v=auth-8"),
      import("/src/auth/auth-controller.js?v=auth-8"),
    ]);
    const root = document.createElement("div");
    root.id = "recovery-auth-root";
    const entryRoot = document.createElement("div");
    entryRoot.id = "recovery-auth-entry";
    document.body.append(entryRoot, root);

    const calls = { resets: [], updates: [] };
    const user = { id: "recovery-user", email: "owner@example.com" };
    const service = {
      getSession: async () => ({
        data: { session: recovery ? { user } : null },
        error: null,
      }),
      onAuthStateChange(callback) {
        if (recovery) callback("PASSWORD_RECOVERY", { user });
        return () => {};
      },
      resetPasswordForEmail: async (email) => {
        calls.resets.push(email);
        return {
          data: {},
          error: resetError
            ? Object.assign(new Error("User not found"), { code: "user_not_found" })
            : null,
        };
      },
      updatePassword: async (password) => {
        calls.updates.push(password);
        return { data: { user }, error: null };
      },
      signInWithPassword: async () => ({ data: { user }, error: null }),
      signUp: async () => ({ data: { user, session: null }, error: null }),
      signOut: async () => ({ error: null }),
    };
    const dialog = new AuthDialog(root, entryRoot);
    const controller = new AuthController(dialog, service);
    await controller.start();
    window.recoveryAuthUnderTest = { calls, controller, dialog, entryRoot, root };
    return {
      recoveryMode: controller.recoveryMode,
      url: window.location.href,
    };
  }, { recovery, resetError });
}

test.beforeEach(async ({ page }) => {
  await page.goto("/contract-test", { waitUntil: "domcontentloaded" });
});

test.afterEach(async ({ page }) => {
  await page.evaluate(() => {
    const target = window.recoveryAuthUnderTest;
    target?.root.remove();
    target?.entryRoot.remove();
    delete window.recoveryAuthUnderTest;
    window.history.replaceState({}, "", "/contract-test");
  });
});

test("重設信申請使用通用訊息且不揭露帳號是否存在", async ({ page }) => {
  await installIsolatedAuth(page);
  await page.locator("#recovery-auth-entry [data-auth-open]").click();
  const dialog = page.locator("#recovery-auth-root [data-auth-dialog]");
  await dialog.getByRole("button", { name: "忘記密碼" }).click();
  await dialog.getByLabel("Email").fill("unknown@example.com");
  await dialog.getByRole("button", { name: "寄送重設連結" }).click();

  await expect(dialog.locator("[data-auth-status]")).toContainText(
    "若此 Email 有帳號",
  );
  const calls = await page.evaluate(() => window.recoveryAuthUnderTest.calls);
  expect(calls.resets).toEqual(["unknown@example.com"]);
});

test("供應商錯誤不會改變重設信的防枚舉回應", async ({ page }) => {
  await installIsolatedAuth(page, { resetError: true });
  await page.locator("#recovery-auth-entry [data-auth-open]").click();
  const dialog = page.locator("#recovery-auth-root [data-auth-dialog]");
  await dialog.getByRole("button", { name: "忘記密碼" }).click();
  await dialog.getByLabel("Email").fill("missing@example.com");
  await dialog.getByRole("button", { name: "寄送重設連結" }).click();

  await expect(dialog.locator("[data-auth-status]")).toContainText(
    "若此 Email 有帳號",
  );
  await expect(dialog.locator("[data-auth-status]")).not.toContainText(
    "User not found",
  );
});

test("PASSWORD_RECOVERY 只在驗證 session 後更新密碼並清除 URL 機密", async ({ page }) => {
  const initial = await installIsolatedAuth(page, { recovery: true });
  expect(initial.recoveryMode).toBe(true);
  expect(initial.url).not.toContain("access_token");
  expect(initial.url).not.toContain("refresh_token");
  expect(initial.url).not.toContain("auth_action");

  const dialog = page.locator("#recovery-auth-root [data-auth-dialog]");
  await expect(dialog).toHaveAttribute("open", "");
  await expect(dialog).toHaveAccessibleName("設定新密碼");
  const activeView = dialog.locator('[data-auth-view="update-password"]:not([hidden])');
  await activeView.getByLabel("新密碼", { exact: true }).fill("new-safe-password");
  await activeView.getByLabel("確認新密碼").fill("new-safe-password");
  await activeView.getByRole("button", { name: "更新密碼" }).click();

  await expect(dialog.locator("[data-auth-status]")).toHaveText("密碼已更新。");
  await expect(dialog.locator('[data-auth-view="account"]:not([hidden])')).toBeVisible();
  const state = await page.evaluate(() => ({
    calls: window.recoveryAuthUnderTest.calls,
    recoveryMode: window.recoveryAuthUnderTest.controller.recoveryMode,
  }));
  expect(state.calls.updates).toEqual(["new-safe-password"]);
  expect(state.recoveryMode).toBe(false);
});


test("一般 state 查詢參數不會被誤判為驗證 callback", async ({ page }) => {
  const result = await page.evaluate(async () => {
    window.history.replaceState({}, "", "/contract-test?state=ui-filter#home");
    const { hasAuthCallback, sanitizeAuthCallbackUrl } = await import(
      "/src/features/auth/auth-callback.js?v=auth-2"
    );
    const before = window.location.href;
    const detected = hasAuthCallback();
    sanitizeAuthCallbackUrl();
    return { before, after: window.location.href, detected };
  });

  expect(result.detected).toBe(false);
  expect(result.after).toBe(result.before);
  expect(result.after).toContain("state=ui-filter");
});
