import { expect, test } from "@playwright/test";
import { routeHomeDataStatus } from "./support/home-data-status-fixture.mjs";
import {
	captureViewport,
	verifyDialogViewport,
	verifyTouchTarget,
} from "./support/mobile-audit-helpers.mjs";

test.beforeEach(async ({ page }) => {
	await routeHomeDataStatus(page);
});

test("200% 大字與鍵盤縮短畫面後建立帳號仍可完整操作", async ({
	page,
}, testInfo) => {
	await page.setViewportSize({ width: 320, height: 568 });
	await page.goto("/?api_mode=stale-oos-research", {
		waitUntil: "domcontentloaded",
	});
	await page.evaluate(() => {
		document.documentElement.style.fontSize = "32px";
		document.documentElement.style.scrollBehavior = "auto";
	});
	await page
		.getByRole("navigation", { name: "主要導覽" })
		.getByRole("button", { name: "自選" })
		.click();
	await page.getByRole("button", { name: "開啟登入" }).click();
	await page
		.getByRole("dialog", { name: "登入" })
		.getByRole("button", { name: "建立帳號" })
		.click();

	await page.setViewportSize({ width: 320, height: 320 });
	const dialog = page.getByRole("dialog", { name: "建立帳號" });
	const signUpView = page.locator('[data-auth-view="signup"]:not([hidden])');
	const email = signUpView.getByLabel("Email");
	const password = signUpView.getByLabel("密碼", { exact: true });
	const confirmation = signUpView.getByLabel("確認密碼");
	const submit = signUpView.getByRole("button", {
		name: "建立帳號",
		exact: true,
	});
	const close = dialog.getByRole("button", { name: "關閉" });

	await verifyDialogViewport(page);
	await email.fill("mobile-keyboard-audit@example.com");
	await password.fill("not-a-real-password");
	await confirmation.fill("not-a-real-password");
	await expect(email).toHaveValue("mobile-keyboard-audit@example.com");
	await expect(password).toHaveValue("not-a-real-password");
	await expect(confirmation).toHaveValue("not-a-real-password");

	await submit.scrollIntoViewIfNeeded();
	await submit.focus();
	await expect(submit).toBeFocused();
	await expect(submit).toBeInViewport();
	await verifyTouchTarget(submit);
	await captureViewport(page, testInfo, "25-signup-keyboard-large-text-200", {
		includeNavigation: false,
	});

	await expect(close).toBeVisible();
	await expect(close).toBeInViewport();
	const box = await close.boundingBox();
	expect(box).not.toBeNull();
	expect(box.y).toBeGreaterThanOrEqual(0);
	expect(box.y + box.height).toBeLessThanOrEqual(320);
	await close.click();
	await expect(dialog).not.toBeVisible();
	await expect(page.getByRole("button", { name: "開啟登入" })).toBeFocused();
});

test("登入處理中保留焦點並阻止 Escape 關閉", async ({ page }) => {
	await page.goto("/contract-test", { waitUntil: "domcontentloaded" });

	const busyState = await page.evaluate(async () => {
		const { AuthDialog } = await import(
			"/src/components/auth/auth-dialog.js?v=auth-8"
		);
		const root = document.createElement("div");
		const entryRoot = document.createElement("div");
		document.body.append(entryRoot, root);
		const authDialog = new AuthDialog(root, entryRoot);
		const opener = entryRoot.querySelector("[data-auth-open]");
		opener.focus();
		authDialog.open("signin");
		const submit = root.querySelector(
			'[data-auth-form="signin"] [data-auth-submit]',
		);
		submit.focus();
		authDialog.setBusy(true);
		window.authDialogUnderTest = {
			authDialog,
			entryRoot,
			opener,
			root,
			submit,
		};
		return {
			activeInside: authDialog.dialog.contains(document.activeElement),
			ariaBusy: authDialog.dialog.getAttribute("aria-busy"),
			open: authDialog.dialog.open,
		};
	});

	expect(busyState).toEqual({
		activeInside: true,
		ariaBusy: "true",
		open: true,
	});
	await page.keyboard.press("Escape");
	await expect(page.getByRole("dialog", { name: "登入" })).toBeVisible();

	const result = await page.evaluate(() => {
		const { authDialog, entryRoot, opener, root, submit } =
			window.authDialogUnderTest;
		authDialog.setBusy(false);
		const focusRestored = document.activeElement === submit;
		authDialog.close();
		const openerRestored = document.activeElement === opener;
		root.remove();
		entryRoot.remove();
		delete window.authDialogUnderTest;
		return { focusRestored, openerRestored };
	});

	expect(result).toEqual({
		focusRestored: true,
		openerRestored: true,
	});
});
