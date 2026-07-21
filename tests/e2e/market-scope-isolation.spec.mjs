import { expect, test } from "@playwright/test";
import { routeHomeDataStatus } from "./support/home-data-status-fixture.mjs";

test.beforeEach(async ({ page }) => {
  await routeHomeDataStatus(page);
});

function scopeSwitch(page, label) {
  return page.locator(`[data-market-scope-switch][aria-label="${label}"]`);
}

test("上市與上櫃使用獨立快照，空的上櫃資料不回退上市", async ({ page }) => {
  const predictionRequests = [];
  page.on("request", (request) => {
    if (request.url().includes("prediction-snapshot")) {
      predictionRequests.push(new URL(request.url()));
    }
  });

  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator('[data-overview-candidates] [data-stock-key="TWSE:TEST1"]')).toBeVisible();

  await scopeSwitch(page, "總覽市場資料集")
    .getByRole("button", { name: "上櫃" })
    .click();
  await expect(page.locator('[data-overview-candidates] .candidate-card')).toHaveCount(0);
  await expect(page.locator("[data-overview-candidates]")).toContainText("上櫃尚無研究結果");
  await expect(page.locator("#market-heading")).toHaveText("上櫃市場判斷");

  await page.getByRole("navigation", { name: "主要導覽" })
    .getByRole("button", { name: "5 日候選" })
    .click();
  const candidateSwitch = scopeSwitch(page, "候選股市場資料集");
  await expect(candidateSwitch.getByRole("button", { name: "上櫃" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(page.locator("[data-candidate-list]")).toContainText("上櫃尚無研究結果");
  await expect(page.locator('[data-candidate-list] .candidate-card')).toHaveCount(0);

  await candidateSwitch.getByRole("button", { name: "上市" }).click();
  const listedCard = page.locator('[data-candidate-list] [data-stock-key="TWSE:TEST1"]');
  await expect(listedCard).toBeVisible();
  await listedCard.getByRole("button", { name: "查看決策詳情" }).click();
  await expect(page).toHaveURL(/#stock\/TWSE\/TEST1$/u);
  await expect(page.getByRole("heading", { name: /TEST1/u })).toBeVisible();

  const markets = predictionRequests.map((url) => url.searchParams.get("market"));
  expect(markets).toEqual(["TWSE", "TPEX"]);
});

test("上櫃 API 錯誤不會覆蓋已載入的上市快照", async ({ page }) => {
  await page.route("**/api/prediction-snapshot**", async (route) => {
    const market = new URL(route.request().url()).searchParams.get("market");
    if (market === "TPEX") {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: '{"code":"TPEX_SNAPSHOT_UNAVAILABLE"}',
      });
      return;
    }
    await route.continue();
  });

  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator('[data-overview-candidates] [data-stock-key="TWSE:TEST1"]')).toBeVisible();
  const marketSwitch = scopeSwitch(page, "總覽市場資料集");

  await marketSwitch.getByRole("button", { name: "上櫃" }).click();
  await expect(page.locator("body")).toHaveAttribute("data-ui-state", "api_error");
  await expect(page.locator('[data-overview-candidates] .candidate-card')).toHaveCount(0);

  await marketSwitch.getByRole("button", { name: "上市" }).click();
  await expect(page.locator("body")).toHaveAttribute("data-ui-state", "ready");
  await expect(page.locator('[data-overview-candidates] [data-stock-key="TWSE:TEST1"]')).toBeVisible();
});
