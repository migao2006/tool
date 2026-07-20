import { expect, test } from "@playwright/test";
import { routeHomeDataStatus } from "./support/home-data-status-fixture.mjs";
import {
  captureViewport,
  MAX_BOTTOM_NAV_VIEWPORT_RATIO,
  verifyDialogViewport,
  verifyLastContentClearsNavigation,
  verifyTouchTarget,
} from "./support/mobile-audit-helpers.mjs";

const LANDSCAPE_VIEWPORT = Object.freeze({ width: 568, height: 320 });

test.beforeEach(async ({ page }) => {
  await routeHomeDataStatus(page);
});

test("320px 放大至 150% 時個股詳情不會被裁切", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await page.goto("/?api_mode=stale-oos-research", { waitUntil: "domcontentloaded" });
  await expect(page.locator("body")).toHaveAttribute("data-ui-state", "research_only");
  await page.evaluate(() => {
    document.documentElement.style.fontSize = "24px";
    document.documentElement.style.scrollBehavior = "auto";
  });

  await page.getByRole("navigation", { name: "主要導覽" })
    .getByRole("button", { name: "5 日候選" })
    .click();
  await page.locator('[data-candidate-list] .candidate-card[data-symbol="OOS1"]')
    .getByRole("button", { name: "查看決策詳情" })
    .click();
  await expect(page.getByRole("heading", { name: /OOS1/u })).toBeVisible();

  const detailLayout = await page.locator(".detail-section-grid").evaluate((grid) => {
    const shell = document.querySelector(".app-shell")?.getBoundingClientRect();
    const panels = Array.from(grid.children).map((panel) => {
      const box = panel.getBoundingClientRect();
      return { left: box.left, right: box.right, width: box.width };
    });
    const gridBox = grid.getBoundingClientRect();
    return {
      grid: { left: gridBox.left, right: gridBox.right, width: gridBox.width },
      panels,
      shell: shell ? { left: shell.left, right: shell.right, width: shell.width } : null,
    };
  });
  expect(detailLayout.shell).not.toBeNull();
  expect(detailLayout.grid.width).toBeLessThanOrEqual(detailLayout.shell.width + 1);
  detailLayout.panels.forEach((panel) => {
    expect(panel.left).toBeGreaterThanOrEqual(detailLayout.shell.left - 1);
    expect(panel.right).toBeLessThanOrEqual(detailLayout.shell.right + 1);
  });
  for (const selector of [".quantile-fields", ".tab-icon-watchlist"]) {
    const dimensions = await page.locator(selector).first().evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth + 1);
  }
  const quantileColumns = await page.locator(".quantile-fields").evaluate((element) => ({
    columnCount: getComputedStyle(element).gridTemplateColumns.split(" ").length,
    itemWidths: Array.from(element.children, (child) => child.getBoundingClientRect().width),
  }));
  expect(quantileColumns.columnCount).toBe(2);
  quantileColumns.itemWidths.forEach((width) => {
    expect(width).toBeGreaterThanOrEqual(120);
  });
  await captureViewport(page, testInfo, "12-stock-detail-large-text-150");
  await page.locator(".quantile-fields").scrollIntoViewIfNeeded();
  await captureViewport(page, testInfo, "13-stock-detail-quantiles-large-text-150");
});

test("320px 放大至 200% 時四個頁面與登入仍可操作", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await page.goto("/?api_mode=stale-oos-research", { waitUntil: "domcontentloaded" });
  await expect(page.locator("body")).toHaveAttribute("data-ui-state", "research_only");
  await page.evaluate(() => {
    document.documentElement.style.fontSize = "32px";
    document.documentElement.style.scrollBehavior = "auto";
  });

  const navigation = page.getByRole("navigation", { name: "主要導覽" });
  await captureViewport(page, testInfo, "14-overview-large-text-200");
  await page.locator("[data-home-data-status]").evaluate((panel) => {
    panel.scrollIntoView({ block: "start", behavior: "auto" });
  });
  await captureViewport(page, testInfo, "14b-home-data-large-text-200");
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "auto" }));

  await navigation.getByRole("button", { name: "5 日候選" }).click();
  await expect(page.getByRole("heading", { name: "5 日候選股" })).toBeVisible();
  const candidateRankRow = page.locator(
    '[data-candidate-list] .candidate-card[data-symbol="OOS1"] .candidate-values > div',
  ).first();
  const rankScoreLayout = await candidateRankRow.evaluate((row) => {
    const label = row.querySelector("dt");
    const value = row.querySelector("dd");
    const range = document.createRange();
    if (value) range.selectNodeContents(value);
    const labelBox = label?.getBoundingClientRect();
    const valueBox = value?.getBoundingClientRect();
    return {
      labelBottom: labelBox?.bottom ?? null,
      lineCount: value ? range.getClientRects().length : null,
      valueTop: valueBox?.top ?? null,
      valueWidth: valueBox?.width ?? null,
    };
  });
  expect(rankScoreLayout.valueWidth).toBeGreaterThanOrEqual(120);
  expect(rankScoreLayout.valueTop).toBeGreaterThanOrEqual(
    rankScoreLayout.labelBottom - 1,
  );
  expect(rankScoreLayout.lineCount).toBe(1);
  await candidateRankRow.scrollIntoViewIfNeeded();
  await captureViewport(page, testInfo, "15-candidates-large-text-200");

  await page.locator('[data-candidate-list] .candidate-card[data-symbol="OOS1"]')
    .getByRole("button", { name: "查看決策詳情" })
    .click();
  await expect(page.getByRole("heading", { name: /OOS1/u })).toBeVisible();
  const decisionLayout = await page.locator('[data-stock-field="decision"]').evaluate((decision) => {
    const value = decision.getBoundingClientRect();
    const container = decision.closest(".decision-hero")?.getBoundingClientRect();
    return {
      clientWidth: decision.clientWidth,
      containerRight: container?.right ?? null,
      right: value.right,
      scrollWidth: decision.scrollWidth,
    };
  });
  expect(decisionLayout.containerRight).not.toBeNull();
  expect(decisionLayout.scrollWidth).toBeLessThanOrEqual(decisionLayout.clientWidth + 1);
  expect(decisionLayout.right).toBeLessThanOrEqual(decisionLayout.containerRight + 1);
  await captureViewport(page, testInfo, "16-stock-detail-large-text-200");
  await page.locator(".quantile-fields").scrollIntoViewIfNeeded();
  await captureViewport(page, testInfo, "17-stock-detail-quantiles-large-text-200");

  await page.evaluate(() => { document.body.dataset.authState = "authenticated"; });
  await navigation.getByRole("button", { name: "自選" }).click();
  await expect(page.getByRole("heading", { name: "自選股" })).toBeVisible();
  await captureViewport(page, testInfo, "18-watchlist-large-text-200");
  const watchlistIcon = await page.locator(".tab-icon-watchlist").evaluate((icon) => ({
    clientWidth: icon.clientWidth,
    scrollWidth: icon.scrollWidth,
  }));
  expect(watchlistIcon.scrollWidth).toBeLessThanOrEqual(watchlistIcon.clientWidth + 1);
  await verifyLastContentClearsNavigation(page);

  await page.evaluate(() => { document.body.dataset.authState = "anonymous"; });
  const authOpener = page.getByRole("button", { name: "開啟登入" });
  await authOpener.click();
  await verifyDialogViewport(page);
  await captureViewport(page, testInfo, "19-signin-large-text-200", {
    includeNavigation: false,
  });
});

test("iPhone 橫向放大至 200% 時三個入口與登入仍可操作", async ({ page }, testInfo) => {
  await page.setViewportSize(LANDSCAPE_VIEWPORT);
  await page.goto("/?api_mode=stale-oos-research", { waitUntil: "domcontentloaded" });
  await expect(page.locator("body")).toHaveAttribute("data-ui-state", "research_only");
  await page.evaluate(() => {
    document.documentElement.style.fontSize = "32px";
    document.documentElement.style.scrollBehavior = "auto";
  });

  const navigation = page.getByRole("navigation", { name: "主要導覽" });
  await captureViewport(page, testInfo, "20-overview-landscape-large-text-200");
  const navigationBox = await navigation.boundingBox();
  expect(navigationBox).not.toBeNull();
  expect(navigationBox.height).toBeLessThanOrEqual(
    LANDSCAPE_VIEWPORT.height * MAX_BOTTOM_NAV_VIEWPORT_RATIO,
  );
  await verifyLastContentClearsNavigation(page);

  await navigation.getByRole("button", { name: "5 日候選" }).click();
  await expect(page.getByRole("heading", { name: "5 日候選股" })).toBeVisible();
  await captureViewport(page, testInfo, "21-candidates-landscape-large-text-200");
  await verifyLastContentClearsNavigation(page);

  await page.locator('[data-candidate-list] .candidate-card[data-symbol="OOS1"]')
    .getByRole("button", { name: "查看決策詳情" })
    .click();
  await expect(page.getByRole("heading", { name: /OOS1/u })).toBeVisible();
  await captureViewport(page, testInfo, "22-detail-landscape-large-text-200");
  await verifyLastContentClearsNavigation(page);

  await navigation.getByRole("button", { name: "自選" }).click();
  await expect(page.getByRole("heading", { name: "自選股" })).toBeVisible();
  await captureViewport(page, testInfo, "23-watchlist-landscape-large-text-200");
  await verifyLastContentClearsNavigation(page);

  const authOpener = page.getByRole("button", { name: "開啟登入" });
  await authOpener.click();
  await verifyDialogViewport(page);
  const dialog = page.getByRole("dialog", { name: "登入" });
  const signInView = page.locator('[data-auth-view="signin"]:not([hidden])');
  const email = signInView.getByLabel("Email");
  const password = signInView.getByLabel("密碼");
  await expect(email).toBeFocused();
  await email.fill("mobile-audit@example.com");
  await password.fill("not-a-real-password");
  await expect(email).toHaveValue("mobile-audit@example.com");
  await expect(password).toHaveValue("not-a-real-password");
  await captureViewport(page, testInfo, "24-signin-landscape-large-text-200", {
    includeNavigation: false,
  });
  const submitButton = dialog.getByRole("button", { name: "登入", exact: true });
  await submitButton.scrollIntoViewIfNeeded();
  await expect(submitButton).toBeVisible();
  await verifyTouchTarget(submitButton);
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(authOpener).toBeFocused();
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
