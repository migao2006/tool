import { expect, test } from "@playwright/test";
import { routeHomeDataStatus } from "./support/home-data-status-fixture.mjs";
import {
  captureViewport,
  verifyTouchTarget,
} from "./support/mobile-audit-helpers.mjs";

test.beforeEach(async ({ page }) => {
  await routeHomeDataStatus(page);
});

test("320px 放大至 200% 時資料卡、標題與稽核內容會依可用寬度重排", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await page.goto("/?api_mode=stale-oos-research", { waitUntil: "domcontentloaded" });
  await expect(page.locator("body")).toHaveAttribute("data-ui-state", "research_only");
  await page.evaluate(() => {
    document.documentElement.style.fontSize = "32px";
    document.documentElement.style.scrollBehavior = "auto";
  });

  const marketLayout = await page.locator(".market-probabilities").evaluate((grid) => {
    const container = grid.getBoundingClientRect();
    return {
      clientWidth: grid.clientWidth,
      itemRightEdges: Array.from(grid.children, (child) => child.getBoundingClientRect().right),
      right: container.right,
      scrollWidth: grid.scrollWidth,
    };
  });
  expect(marketLayout.scrollWidth).toBeLessThanOrEqual(marketLayout.clientWidth + 1);
  marketLayout.itemRightEdges.forEach((right) => {
    expect(right).toBeLessThanOrEqual(marketLayout.right + 1);
  });

  const modelOutputLayout = await page.locator(".home-data-summary > div").last().evaluate((row) => {
    const label = row.querySelector("span").getBoundingClientRect();
    const value = row.querySelector("strong").getBoundingClientRect();
    return {
      labelBottom: label.bottom,
      labelWidth: label.width,
      rowWidth: row.getBoundingClientRect().width,
      valueTop: value.top,
    };
  });
  expect(modelOutputLayout.labelWidth).toBeGreaterThanOrEqual(modelOutputLayout.rowWidth * 0.6);
  expect(modelOutputLayout.valueTop).toBeGreaterThanOrEqual(modelOutputLayout.labelBottom - 1);
  await page.locator(".market-probabilities").scrollIntoViewIfNeeded();
  await captureViewport(page, testInfo, "25a-overview-critical-layouts-large-text-200");

  await page.getByRole("button", { name: "研究設定" }).click();
  const longSettingLabel = page.locator('.settings-form input[name="estimated_order_notional_ntd"]')
    .locator("xpath=preceding-sibling::span");
  const settingLabelLayout = await longSettingLabel.evaluate((label) => ({
    clientWidth: label.clientWidth,
    scrollWidth: label.scrollWidth,
  }));
  expect(settingLabelLayout.scrollWidth).toBeLessThanOrEqual(settingLabelLayout.clientWidth + 1);
  await longSettingLabel.scrollIntoViewIfNeeded();
  await captureViewport(page, testInfo, "25b-settings-critical-layouts-large-text-200", {
    includeNavigation: false,
  });
  await page.getByRole("button", { name: "關閉研究設定" }).click();

  const navigation = page.getByRole("navigation", { name: "主要導覽" });
  await navigation.getByRole("button", { name: "5 日候選" }).click();
  const candidateHeading = await page.locator('[data-page="opportunities"] > .page-heading')
    .evaluate((heading) => {
      const box = heading.getBoundingClientRect();
      const date = heading.querySelector(".date-badge").getBoundingClientRect();
      return {
        clientWidth: heading.clientWidth,
        dateRight: date.right,
        right: box.right,
        scrollWidth: heading.scrollWidth,
      };
    });
  expect(candidateHeading.scrollWidth).toBeLessThanOrEqual(candidateHeading.clientWidth + 1);
  expect(candidateHeading.dateRight).toBeLessThanOrEqual(candidateHeading.right + 1);
  await captureViewport(page, testInfo, "25c-candidate-critical-layouts-large-text-200");

  const candidateFilters = page.locator("[data-candidate-filters]");
  await candidateFilters.locator('[data-open-drawer="candidate-filters"]').click();
  const filterDrawer = page.getByRole("dialog", { name: "篩選候選股" });
  await verifyTouchTarget(filterDrawer.locator("button, input"));
  await filterDrawer.getByRole("button", { name: "完成", exact: true }).click();

  await page.locator('[data-candidate-list] .candidate-card[data-symbol="OOS1"]')
    .getByRole("button", { name: "查看決策詳情" })
    .click();
  const reasonLayout = await page.locator(".decision-reasons").evaluate((row) => {
    const box = row.getBoundingClientRect();
    const code = row.querySelector("code").getBoundingClientRect();
    return {
      clientWidth: row.clientWidth,
      codeRight: code.right,
      right: box.right,
      scrollWidth: row.scrollWidth,
    };
  });
  expect(reasonLayout.scrollWidth).toBeLessThanOrEqual(reasonLayout.clientWidth + 1);
  expect(reasonLayout.codeRight).toBeLessThanOrEqual(reasonLayout.right + 1);

  const detailLayout = await page.locator(".detail-section-grid").evaluate((grid) => {
    const box = grid.getBoundingClientRect();
    return {
      clientWidth: grid.clientWidth,
      panelRightEdges: Array.from(grid.children, (child) => child.getBoundingClientRect().right),
      right: box.right,
      scrollWidth: grid.scrollWidth,
    };
  });
  expect(detailLayout.scrollWidth).toBeLessThanOrEqual(detailLayout.clientWidth + 1);
  detailLayout.panelRightEdges.forEach((right) => {
    expect(right).toBeLessThanOrEqual(detailLayout.right + 1);
  });

  const gateHeadingLines = await page.locator("#gate-title").evaluate((heading) => {
    const range = document.createRange();
    range.selectNodeContents(heading);
    return range.getClientRects().length;
  });
  expect(gateHeadingLines).toBeLessThanOrEqual(2);
  await page.locator(".decision-reasons").scrollIntoViewIfNeeded();
  await captureViewport(page, testInfo, "25d-detail-reasons-large-text-200");
  await page.locator("#gate-title").scrollIntoViewIfNeeded();
  await captureViewport(page, testInfo, "25e-detail-gates-large-text-200");

  await navigation.getByRole("button", { name: "5 日候選" }).click();
  await page.getByRole("button", { name: /資料排除/u }).click();
  const closeLayout = await page.getByRole("button", { name: "關閉排除清單" }).evaluate((button) => {
    const range = document.createRange();
    range.selectNodeContents(button);
    return {
      clientWidth: button.clientWidth,
      lineCount: range.getClientRects().length,
      scrollWidth: button.scrollWidth,
    };
  });
  expect(closeLayout.lineCount).toBe(1);
  expect(closeLayout.scrollWidth).toBeLessThanOrEqual(closeLayout.clientWidth + 1);
  await captureViewport(page, testInfo, "25f-hard-fail-critical-layouts-large-text-200", {
    includeNavigation: false,
  });
});

test("320px 放大至 200% 時錯誤狀態說明不會被狀態標籤擠壓", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await page.goto("/?api_mode=invalid-json", { waitUntil: "domcontentloaded" });
  await expect(page.locator("body")).toHaveAttribute("data-ui-state", "api_error");
  await page.evaluate(() => {
    document.documentElement.style.fontSize = "32px";
    document.documentElement.style.scrollBehavior = "auto";
  });

  const bannerLayout = await page.locator('[data-page="home"] .system-banner').first().evaluate((banner) => {
    const badge = banner.querySelector(".system-badge").getBoundingClientRect();
    const copy = banner.querySelector("[data-status-copy]").getBoundingClientRect();
    return {
      badgeBottom: badge.bottom,
      copyTop: copy.top,
      copyWidth: copy.width,
      width: banner.getBoundingClientRect().width,
    };
  });
  expect(bannerLayout.copyTop).toBeGreaterThanOrEqual(bannerLayout.badgeBottom - 1);
  expect(bannerLayout.copyWidth).toBeGreaterThanOrEqual(bannerLayout.width * 0.75);
  await captureViewport(page, testInfo, "26-api-error-banner-large-text-200");
});

test("iPhone 橫向候選篩選控制項維持至少 44px", async ({ page }) => {
  await page.setViewportSize({ width: 667, height: 375 });
  await page.goto("/?api_mode=stale-oos-research", { waitUntil: "domcontentloaded" });
  await page.getByRole("navigation", { name: "主要導覽" })
    .getByRole("button", { name: "5 日候選" })
    .click();
  await page.locator('[data-open-drawer="candidate-filters"]').click();
  await verifyTouchTarget(page.locator(
    '[data-drawer="candidate-filters"] button, [data-drawer="candidate-filters"] input',
  ));
});
