import { expect, test } from "@playwright/test";
import { routeHomeDataStatus } from "./support/home-data-status-fixture.mjs";
import {
  captureViewport,
  MOBILE_VIEWPORTS,
  scrollToPageMiddle,
  verifyDialogViewport,
  verifyTouchTarget,
} from "./support/mobile-audit-helpers.mjs";

test.beforeEach(async ({ page }) => {
  await routeHomeDataStatus(page);
});

for (const viewport of MOBILE_VIEWPORTS) {
  test(`${viewport.name} 四頁與登入抽屜視覺巡檢`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto("/?api_mode=stale-oos-research", { waitUntil: "domcontentloaded" });
    await expect(page.locator("body")).toHaveAttribute("data-ui-state", "research_only");
    await expect(page.getByRole("heading", { name: "今日總覽" })).toBeVisible();
    await captureViewport(page, testInfo, `01-overview-${viewport.name}`);

    const navigation = page.getByRole("navigation", { name: "主要導覽" });
    await navigation.getByRole("button", { name: "5 日候選" }).click();
    await expect(page.getByRole("heading", { name: "5 日候選股" })).toBeVisible();
    await captureViewport(page, testInfo, `02-candidates-${viewport.name}`);

    await page.locator('[data-open-drawer="candidate-filters"]').click();
    const filterDrawer = page.getByRole("dialog", { name: "篩選候選股" });
    const filterControls = filterDrawer.locator("button, input");
    await verifyTouchTarget(filterControls);
    const filterFontSizes = await filterDrawer.locator(
      ".candidate-choice-trigger, input",
    ).evaluateAll((controls) => controls.map((control) => Number.parseFloat(
      getComputedStyle(control).fontSize,
    )));
    filterFontSizes.forEach((fontSize) => {
      expect(fontSize).toBeGreaterThanOrEqual(16);
    });
    await captureViewport(page, testInfo, `02b-candidate-filters-${viewport.name}`, {
      includeNavigation: false,
    });
    await filterDrawer.locator('[data-choice-for="decision"]').click();
    const choiceSheet = page.getByRole("dialog", { name: "選擇決策" });
    await expect(choiceSheet).toBeVisible();
    await verifyTouchTarget(choiceSheet.locator("button"));
    await captureViewport(page, testInfo, `02c-candidate-choice-${viewport.name}`, {
      includeNavigation: false,
    });
    await choiceSheet.getByRole("button", { name: "取消" }).click();
    await filterDrawer.getByRole("button", { name: "完成", exact: true }).click();

    await page.locator('[data-candidate-list] .candidate-card[data-symbol="OOS1"]')
      .getByRole("button", { name: "查看決策詳情" })
      .click();
    await expect(page.getByRole("heading", { name: /OOS1/u })).toBeVisible();
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
    await captureViewport(page, testInfo, `03-stock-detail-${viewport.name}`);

    await page.evaluate(() => { document.body.dataset.authState = "authenticated"; });
    await navigation.getByRole("button", { name: "自選" }).click();
    await expect(page.getByRole("heading", { name: "自選股" })).toBeVisible();
    const watchFilterLayout = await page.locator(".watch-filters").evaluate((filters) => {
      const container = filters.getBoundingClientRect();
      const buttons = Array.from(filters.querySelectorAll("button")).map((button) => {
        const box = button.getBoundingClientRect();
        return { left: box.left, right: box.right };
      });
      return { buttons, left: container.left, right: container.right };
    });
    expect(watchFilterLayout.buttons).toHaveLength(4);
    watchFilterLayout.buttons.forEach((button) => {
      expect(button.left).toBeGreaterThanOrEqual(watchFilterLayout.left - 1);
      expect(button.right).toBeLessThanOrEqual(watchFilterLayout.right + 1);
    });
    await captureViewport(page, testInfo, `04-watchlist-${viewport.name}`);

    await page.evaluate(() => { document.body.dataset.authState = "anonymous"; });
    const authOpener = page.getByRole("button", { name: "開啟登入" });
    await verifyTouchTarget(authOpener);
    await authOpener.click();
    await verifyDialogViewport(page);
    await expect(page.locator('[data-auth-view="signin"]:not([hidden])').getByLabel("Email"))
      .toBeFocused();
    await captureViewport(page, testInfo, `05-signin-${viewport.name}`, {
      includeNavigation: false,
    });

    const dialog = page.getByRole("dialog", { name: "登入" });
    await dialog.getByRole("button", { name: "建立帳號" }).click();
    await expect(page.getByRole("dialog", { name: "建立帳號" })).toBeVisible();
    await verifyDialogViewport(page);
    await expect(page.locator('[data-auth-view="signup"]:not([hidden])').getByLabel("Email"))
      .toBeFocused();
    await captureViewport(page, testInfo, `06-signup-${viewport.name}`, {
      includeNavigation: false,
    });
    await page.getByRole("button", { name: "關閉" }).click();
    await expect(page.locator("[data-auth-dialog]")).not.toBeVisible();
    await expect(authOpener).toBeFocused();
  });
}

test("手機瀏覽器上一頁與下一頁會恢復各頁捲動位置", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await page.goto("/?api_mode=stale-oos-research", { waitUntil: "domcontentloaded" });
  await page.getByRole("navigation", { name: "主要導覽" })
    .getByRole("button", { name: "5 日候選" })
    .click();
  await expect(page.getByRole("heading", { name: "5 日候選股" })).toBeVisible();

  const candidateScroll = await scrollToPageMiddle(page);
  expect(candidateScroll).toBeGreaterThan(100);
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(candidateScroll);

  await page.locator(".app-page.is-active [data-candidate-list] .candidate-card button")
    .first()
    .evaluate((button) => button.click());
  await expect(page.getByRole("heading", { name: /OOS1/u })).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
  const detailScroll = await scrollToPageMiddle(page);
  expect(detailScroll).toBeGreaterThan(300);
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(detailScroll);

  await page.goBack();
  await expect(page.getByRole("heading", { name: "5 日候選股" })).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(candidateScroll);

  await page.goForward();
  await expect(page.getByRole("heading", { name: /OOS1/u })).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(detailScroll);
});

test("iPhone 橫向畫面不會溢位且登入抽屜可操作", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 814, height: 380 });
  await page.goto("/?api_mode=stale-oos-research", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "今日總覽" })).toBeVisible();
  await expect(page.locator(".topbar")).toBeHidden();
  await captureViewport(page, testInfo, "10-overview-iphone-landscape");

  const navigation = page.getByRole("navigation", { name: "主要導覽" });
  await navigation.getByRole("button", { name: "自選" }).click();
  await expect(page.getByRole("heading", { name: "自選股" })).toBeVisible();
  const authOpener = page.getByRole("button", { name: "開啟登入" });
  await authOpener.click();
  await verifyDialogViewport(page);
  await expect(page.locator('[data-auth-view="signin"]:not([hidden])').getByLabel("Email"))
    .toBeFocused();
  await captureViewport(page, testInfo, "11-signin-iphone-landscape", {
    includeNavigation: false,
  });
  await page.getByRole("button", { name: "關閉" }).click();
  await expect(authOpener).toBeFocused();
});
