import { expect, test } from "@playwright/test";
import { routeHomeDataStatus } from "./support/home-data-status-fixture.mjs";
import {
	captureViewport,
	verifyTouchTarget,
} from "./support/mobile-audit-helpers.mjs";

test.beforeEach(async ({ page }) => {
	await routeHomeDataStatus(page);
});

test("200% 大字與鍵盤縮短畫面後研究設定仍可完整操作", async ({
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

	const opener = page.getByRole("button", { name: "研究設定" });
	await opener.click();
	const drawer = page.getByRole("dialog", { name: "研究設定" });
	const close = drawer.getByRole("button", { name: "關閉研究設定" });
	await expect(drawer).toBeVisible();
	await expect(close).toBeFocused();

	await page.setViewportSize({ width: 320, height: 320 });
	const finalField = drawer.locator('input[name="max_market_exposure"]');
	const save = drawer.getByRole("button", { name: "儲存於此裝置" });
	await finalField.fill("0.6");
	await save.scrollIntoViewIfNeeded();
	await save.focus();

	const layout = await drawer.evaluate((element) => {
		const sheet = element.querySelector(".drawer-sheet");
		const header = element.querySelector(".drawer-header");
		const form = element.querySelector(".settings-form");
		const saveButton = element.querySelector(".settings-save");
		const rectangles = [sheet, header, form, saveButton].map((node) =>
			node?.getBoundingClientRect(),
		);
		return {
			formClientHeight: form?.clientHeight ?? null,
			formScrollHeight: form?.scrollHeight ?? null,
			headerBottom: rectangles[1]?.bottom ?? null,
			saveBottom: rectangles[3]?.bottom ?? null,
			saveTop: rectangles[3]?.top ?? null,
			sheetBottom: rectangles[0]?.bottom ?? null,
		};
	});
	expect(layout.formScrollHeight).toBeGreaterThan(layout.formClientHeight);
	expect(layout.saveTop).toBeGreaterThanOrEqual(layout.headerBottom - 1);
	expect(layout.saveBottom).toBeLessThanOrEqual(layout.sheetBottom + 1);
	await expect(save).toBeInViewport();
	await verifyTouchTarget(save);
	await captureViewport(page, testInfo, "26-settings-keyboard-large-text-200", {
		includeNavigation: false,
	});

	await save.click();
	const feedback = drawer.getByText("已儲存裝置偏好", { exact: false });
	await feedback.scrollIntoViewIfNeeded();
	await expect(feedback).toBeInViewport();
	await expect(close).toBeInViewport();
	await verifyTouchTarget(close);
	await close.click();
	await expect(drawer).not.toBeVisible();
	await expect(opener).toBeFocused();
});

test("320px 與 200% 大字下驗證狀態說明不會被擠成直排", async ({
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

	const opener = page.getByRole("button", { name: "查看模型驗證報告" });
	await opener.click();
	const drawer = page.getByRole("dialog", { name: "驗證報告" });
	const banner = drawer.locator(".system-banner.compact");
	const badge = banner.locator(".system-badge");
	const close = drawer.getByRole("button", { name: "關閉驗證報告" });
	await expect(drawer).toBeVisible();
	await expect(close).toBeFocused();

	const bannerLayout = await banner.evaluate((element) => {
		const badgeBox = element.querySelector(".system-badge")?.getBoundingClientRect();
		const copyBox = element.querySelector("div")?.getBoundingClientRect();
		return {
			badgeBottom: badgeBox?.bottom ?? null,
			copyTop: copyBox?.top ?? null,
			copyWidth: copyBox?.width ?? null,
		};
	});
	expect(bannerLayout.copyWidth).toBeGreaterThanOrEqual(200);
	expect(bannerLayout.copyTop).toBeGreaterThanOrEqual(bannerLayout.badgeBottom);
	await expect(badge).toBeInViewport();
	await captureViewport(page, testInfo, "27-validation-report-large-text-200", {
		includeNavigation: false,
	});

	const limitations = drawer.locator(".audit-note");
	await limitations.scrollIntoViewIfNeeded();
	await expect(limitations).toBeInViewport();
	await expect(close).toBeInViewport();
	await verifyTouchTarget(close);
	await close.click();
	await expect(drawer).not.toBeVisible();
	await expect(opener).toBeFocused();
});
