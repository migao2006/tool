import { mkdir } from "node:fs/promises";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { routeHomeDataStatus } from "./support/home-data-status-fixture.mjs";

const MOBILE_VIEWPORTS = Object.freeze([
  { name: "iphone-se", width: 320, height: 568 },
  { name: "iphone-standard", width: 390, height: 844 },
  { name: "iphone-large", width: 430, height: 932 },
]);

async function verifyTouchTarget(locator) {
  const boxes = await locator.evaluateAll((elements) =>
    elements
      .filter((element) => !element.hidden && element.getClientRects().length > 0)
      .map((element) => {
        const box = element.getBoundingClientRect();
        return { height: box.height, width: box.width };
      }),
  );
  expect(boxes.length).toBeGreaterThan(0);
  boxes.forEach((box) => {
    expect(box.height).toBeGreaterThanOrEqual(43.5);
    expect(box.width).toBeGreaterThanOrEqual(43.5);
  });
}

async function scrollToPageMiddle(page) {
  return page.evaluate(() => {
    const root = document.documentElement;
    const previousBehavior = root.style.scrollBehavior;
    const top = Math.round((root.scrollHeight - window.innerHeight) / 2);
    root.style.scrollBehavior = "auto";
    window.scrollTo({ top, behavior: "auto" });
    root.style.scrollBehavior = previousBehavior;
    return top;
  });
}

async function verifyMobileViewport(page, { includeNavigation = true } = {}) {
  const layout = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    viewportHeight: window.innerHeight,
    overflowSources: Array.from(document.querySelectorAll("body *"))
      .filter((element) => {
        const box = element.getBoundingClientRect();
        return box.width > 0 && (
          box.left < -1 ||
          box.right > window.innerWidth + 1 ||
          element.scrollWidth > element.clientWidth + 1
        );
      })
      .slice(0, 8)
      .map((element) => ({
        className: element.className,
        clientWidth: element.clientWidth,
        overflowX: getComputedStyle(element).overflowX,
        scrollWidth: element.scrollWidth,
        tagName: element.tagName,
        text: element.textContent?.trim().slice(0, 80),
      })),
  }));
  expect(
    layout.scrollWidth,
    `水平溢位來源：${JSON.stringify(layout.overflowSources)}`,
  ).toBeLessThanOrEqual(layout.clientWidth + 1);

  if (!includeNavigation) return;
  const navigation = page.getByRole("navigation", { name: "主要導覽" });
  const box = await navigation.boundingBox();
  expect(box).not.toBeNull();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(layout.clientWidth + 1);
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.y + box.height).toBeLessThanOrEqual(layout.viewportHeight + 1);
  await verifyTouchTarget(navigation.getByRole("button"));
  await verifyTouchTarget(page.locator(".app-page.is-active button"));
}

async function verifyDialogViewport(page) {
  const dialog = page.getByRole("dialog", { name: /登入|建立帳號/u });
  await expect(dialog).toBeVisible();
  const [box, viewport] = await Promise.all([
    dialog.boundingBox(),
    page.evaluate(() => ({ height: window.innerHeight, width: window.innerWidth })),
  ]);
  expect(box).not.toBeNull();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(viewport.width + 1);
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.y + box.height).toBeLessThanOrEqual(viewport.height + 1);
  expect(await page.evaluate(() => {
    const active = document.activeElement;
    return Boolean(active && document.querySelector("[data-auth-dialog]")?.contains(active));
  })).toBe(true);
  await verifyTouchTarget(dialog.getByRole("button"));
  await verifyMobileViewport(page, { includeNavigation: false });
}

async function captureViewport(page, testInfo, name, options) {
  await verifyMobileViewport(page, options);
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

    await page.locator("[data-candidate-filters] summary").click();
    const filterControls = page.locator(
      "[data-candidate-filters] button, [data-candidate-filters] input, [data-candidate-filters] select",
    );
    await verifyTouchTarget(filterControls);
    const filterFontSizes = await page.locator(
      "[data-candidate-filters] input, [data-candidate-filters] select",
    ).evaluateAll((controls) => controls.map((control) => Number.parseFloat(
      getComputedStyle(control).fontSize,
    )));
    filterFontSizes.forEach((fontSize) => {
      expect(fontSize).toBeGreaterThanOrEqual(16);
    });

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

test("320px 長文字不會造成頁面水平溢位", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await page.route("**/prediction-snapshot**", async (route) => {
    const response = await route.fetch();
    const payload = await response.json();
    const prediction = payload.predictions[0];
    prediction.name = "超長名稱測試股份有限公司半導體先進封裝解決方案";
    prediction.industry = "半導體與先進封裝設備暨高效能運算供應鏈產業分類";
    prediction.reason_codes = [
      "RESEARCH_ONLY_NO_FORMAL_DECISION_POLICY_WITH_A_VERY_LONG_UNBROKEN_SUFFIX",
      "UNADJUSTED_PRICE_RESEARCH_ONLY_WITH_ADDITIONAL_PROVENANCE_DETAILS",
      "POINT_IN_TIME_IDENTITY_UNVERIFIED_WITH_HISTORICAL_COVERAGE_GAPS",
    ];
    payload.watchlist = [{ ...prediction }];
    await route.fulfill({ response, json: payload });
  });

  await page.goto("/?api_mode=stale-oos-research", { waitUntil: "domcontentloaded" });
  const navigation = page.getByRole("navigation", { name: "主要導覽" });
  await navigation.getByRole("button", { name: "5 日候選" }).click();
  const card = page.locator('[data-candidate-list] .candidate-card[data-symbol="OOS1"]');
  await expect(card).toContainText("超長名稱測試股份有限公司");
  await captureViewport(page, testInfo, "07-long-content-candidate-iphone-se");

  await card.getByRole("button", { name: "查看決策詳情" }).click();
  await expect(page.getByRole("heading", { name: /超長名稱測試股份有限公司/u })).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
  const reasonLayout = await page.locator(".decision-reasons").evaluate((row) => {
    const label = row.querySelector("span").getBoundingClientRect();
    const code = row.querySelector("code").getBoundingClientRect();
    return { codeTop: code.top, labelBottom: label.bottom };
  });
  expect(reasonLayout.codeTop).toBeGreaterThanOrEqual(reasonLayout.labelBottom);
  await captureViewport(page, testInfo, "08-long-content-detail-iphone-se");

  await page.evaluate(() => { document.body.dataset.authState = "authenticated"; });
  await navigation.getByRole("button", { name: "自選" }).click();
  await expect(page.locator("[data-watchlist-results] .watchlist-card"))
    .toContainText("超長名稱測試股份有限公司");
  await captureViewport(page, testInfo, "09-long-content-watchlist-iphone-se");
});
