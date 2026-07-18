import { expect, test } from "@playwright/test";

test("後端 fixture 符合正式 5 日快照契約", async ({ page }) => {
  await page.goto("/contract-test", { waitUntil: "domcontentloaded" });

  await expect(page.locator("body")).toHaveText('{"ok":true,"status":"PASS"}');
});

test("iPhone 版只顯示三個主要入口並可開啟個股詳情", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });

  await expect(page.locator("body")).toHaveAttribute("data-ui-state", "ready");
  const navigation = page.getByRole("navigation", { name: "主要導覽" });
  const navigationButtons = navigation.getByRole("button");
  await expect(navigationButtons).toHaveCount(3);
  await expect(navigationButtons).toHaveText([
    "總覽",
    "5 日候選",
    "自選",
  ]);

  await navigation.getByRole("button", { name: "5 日候選" }).click();
  await expect(page.getByRole("heading", { name: "5 日候選股" })).toBeVisible();
  const testCandidate = page.locator('[data-page="opportunities"] .candidate-card[data-symbol="TEST1"]');
  await expect(testCandidate).toBeVisible();
  await expect(testCandidate).toContainText("Rank Score（當日橫斷面排名百分位）");

  await testCandidate.getByRole("button", { name: "查看決策詳情" }).click();
  await expect(page.getByRole("heading", { name: /TEST1/u })).toBeVisible();
  await expect(navigation.getByRole("button")).toHaveCount(3);
  await expect(page.locator('[data-page="stock"]')).toHaveAttribute("data-horizon", "5");
});

test("API 契約錯誤時顯示 FAIL，且不把 fixture 當成候選", async ({ page }) => {
  await page.goto("/?api_mode=contract-error", { waitUntil: "domcontentloaded" });

  await expect(page.locator("body")).toHaveAttribute("data-ui-state", "api_error");
  await expect(page.locator("body")).toHaveAttribute("data-system-status", "FAIL");
  await expect(page.getByText("服務暫時無法使用").first()).toBeVisible();

  await page.getByRole("navigation", { name: "主要導覽" })
    .getByRole("button", { name: "5 日候選" })
    .click();
  await expect(page.locator('[data-candidate-list] .candidate-card')).toHaveCount(0);
  await expect(page.locator("[data-candidate-list]")).toContainText("無正式候選股");
});
