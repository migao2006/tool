import { expect, test } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { join } from "node:path";
import { routeHomeDataStatus } from "./support/home-data-status-fixture.mjs";

async function verifyMobileViewport(page) {
  const layout = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    viewportHeight: window.innerHeight,
  }));
  expect(layout.scrollWidth).toBeLessThanOrEqual(layout.clientWidth + 1);

  const navigation = page.getByRole("navigation", { name: "主要導覽" });
  const box = await navigation.boundingBox();
  expect(box).not.toBeNull();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(layout.clientWidth + 1);
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.y + box.height).toBeLessThanOrEqual(layout.viewportHeight + 1);
}

async function captureViewport(page, testInfo, name) {
  await verifyMobileViewport(page);
  const auditDirectory = join(process.cwd(), "artifacts", "mobile-ui-audit");
  await mkdir(auditDirectory, { recursive: true });
  const screenshotPath = join(auditDirectory, `${name}.png`);
  await page.screenshot({ path: screenshotPath, fullPage: false });
  await testInfo.attach(name, {
    path: screenshotPath,
    contentType: "image/png",
  });
}

test.beforeEach(async ({ page }) => {
  await routeHomeDataStatus(page);
});

test("iPhone 四頁視覺巡檢並保存截圖", async ({ page }, testInfo) => {
  await page.goto("/?api_mode=stale-oos-research", { waitUntil: "domcontentloaded" });
  await expect(page.locator("body")).toHaveAttribute("data-ui-state", "research_only");
  await expect(page.getByRole("heading", { name: "今日總覽" })).toBeVisible();
  await captureViewport(page, testInfo, "01-overview-iphone");

  const navigation = page.getByRole("navigation", { name: "主要導覽" });
  await navigation.getByRole("button", { name: "5 日候選" }).click();
  await expect(page.getByRole("heading", { name: "5 日候選股" })).toBeVisible();
  await captureViewport(page, testInfo, "02-candidates-iphone");

  await page.locator('[data-candidate-list] .candidate-card[data-symbol="OOS1"]')
    .getByRole("button", { name: "查看決策詳情" })
    .click();
  await expect(page.getByRole("heading", { name: /OOS1/u })).toBeVisible();
  await captureViewport(page, testInfo, "03-stock-detail-iphone");

  await navigation.getByRole("button", { name: "自選" }).click();
  await expect(page.getByRole("heading", { name: "自選股" })).toBeVisible();
  await captureViewport(page, testInfo, "04-watchlist-iphone");
});
