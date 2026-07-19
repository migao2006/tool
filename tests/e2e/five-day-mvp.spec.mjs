import { expect, test } from "@playwright/test";

const TEST_ONLY_HOME_DATA_STATUS = Object.freeze({
  status_key: "latest",
  contract_version: "home-data-status.v1",
  as_of_date: "2026-07-17",
  latest_available_at: "2026-07-18T01:00:00Z",
  securities_count: 2_104,
  twse_securities_count: 1_096,
  tpex_securities_count: 1_008,
  daily_bars_latest_date: "2026-07-17",
  daily_bars_latest_count: 2_080,
  twse_daily_bars_latest_count: 1_080,
  tpex_daily_bars_latest_count: 1_000,
  production_ready_daily_bars_count: 2_040,
  historical_landing_count: 14_000,
  historical_parsed_count: 12_000,
  historical_quarantined_count: 2_000,
  historical_production_eligible_count: 0,
  data_sources_count: 4,
  source_codes: ["MOPS", "TPEX", "TWSE", "FINMIND"],
  prediction_runs_count: 0,
  stock_predictions_count: 0,
  market_predictions_count: 0,
  model_output_status: "RESEARCH_ONLY",
  reason_codes: ["MODEL_OUTPUT_NOT_AVAILABLE"],
  updated_at: "2026-07-18T01:10:00Z",
});

const HOME_DATA_ROUTE = "**/rest/v1/home_data_status*";

async function routeHomeDataStatus(page, { body = TEST_ONLY_HOME_DATA_STATUS, status = 200 } = {}) {
  await page.route(HOME_DATA_ROUTE, async (route) => {
    if (route.request().method() === "OPTIONS") {
      await route.fulfill({
        status: 204,
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Headers": "authorization, apikey, content-type",
          "Access-Control-Allow-Methods": "GET, OPTIONS",
        },
      });
      return;
    }
    await route.fulfill({
      status,
      contentType: "application/json",
      headers: {
        "Access-Control-Allow-Origin": "*",
        "Content-Profile": "public",
      },
      body: JSON.stringify(body),
    });
  });
}

test.beforeEach(async ({ page }) => {
  await routeHomeDataStatus(page);
});

async function stubSentry(page) {
  await page.route("**/src/vendor/sentry-10.66.0.min.js", (route) =>
    route.fulfill({
      contentType: "application/javascript",
      body: `
        globalThis.__capturedSentryErrors = [];
        globalThis.Sentry = {
          init() {},
          captureException(error) {
            globalThis.__capturedSentryErrors.push({
              code: error?.code ?? null,
              message: error?.message ?? String(error),
            });
          },
        };
      `,
    }));
}

function capturedSentryErrors(page) {
  return page.evaluate(() => globalThis.__capturedSentryErrors ?? []);
}

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

test("研究快照顯示已完成欄位，缺值維持破折號", async ({ page }) => {
  await page.goto("/?api_mode=research", { waitUntil: "domcontentloaded" });

  await expect(page.locator("body")).toHaveAttribute("data-ui-state", "research_only");
  const banner = page.locator('[data-page="home"] .system-banner').first();
  await expect(banner).toHaveClass(/is-badge-only/u);
  await expect(banner.locator("[data-system-status-label]")).toHaveText("RESEARCH_ONLY");
  await expect(banner.locator("[data-status-copy]")).toBeHidden();

  await expect(page.locator('[data-overview-field="market_p_up"]')).toHaveText("62.0%");
  await expect(page.locator('[data-overview-field="market_p_neutral"]')).toHaveText("—");
  await expect(page.locator("[data-market-state]")).toHaveText("部分更新");
  await expect(page.locator('[data-overview-count="CANDIDATE"]')).toHaveText("—");
  await expect(page.locator('[data-overview-candidates] .candidate-card[data-symbol="RESEARCH1"]')).toBeVisible();

  const navigation = page.getByRole("navigation", { name: "主要導覽" });
  await expect(navigation.getByRole("button")).toHaveCount(3);
  await navigation.getByRole("button", { name: "5 日候選" }).click();
  const researchCard = page.locator('[data-candidate-list] .candidate-card[data-symbol="RESEARCH1"]');
  await expect(researchCard).toBeVisible();
  await expect(researchCard).toContainText("94.0");
  await expect(researchCard.locator(".decision-badge")).toHaveText("—");

  await researchCard.getByRole("button", { name: "查看決策詳情" }).click();
  await expect(page.getByRole("heading", { name: "RESEARCH1" })).toBeVisible();
  await expect(page.locator('[data-stock-field="decision"]')).toHaveText("—");
  await expect(page.locator('[data-stock-field="rank_score"]')).toHaveText("94.0");
  await expect(page.locator('[data-stock-field="net_q10"]')).toHaveText("—");
  await expect(page.locator('[data-stock-field="net_q50"]')).toHaveText("1.2%");

  await page.evaluate(() => { document.body.dataset.authState = "authenticated"; });
  await navigation.getByRole("button", { name: "自選" }).click();
  const watchCard = page.locator('[data-watchlist-results] .watchlist-card');
  await expect(watchCard).toBeVisible();
  await expect(watchCard).toContainText("RESEARCH1");
  await expect(watchCard.locator(".decision-badge")).toHaveText("—");
});

test("首頁只把資料庫真實摘要顯示為 RAW／RESEARCH_ONLY", async ({ page }) => {
  await page.goto("/?api_mode=contract-error", { waitUntil: "domcontentloaded" });

  const panel = page.locator("[data-home-data-status]");
  await expect(panel).toHaveAttribute("data-state", "ready");
  await expect(panel).toContainText("RAW DATA");
  await expect(panel).toContainText("RESEARCH_ONLY");
  await expect(panel).toContainText("2,104 檔");
  await expect(panel).toContainText("上市 1,096／上櫃 1,008");
  await expect(panel).toContainText("landing");
  await expect(panel).toContainText("14,000");
  await expect(panel).toContainText("隔離 quarantine");
  await expect(panel).toContainText("2,000");
  await expect(panel).toContainText("個股輸出 0／市場輸出 0");

  await expect(page.locator('[data-overview-field="market_p_up"]')).toHaveText("—");
  await expect(page.locator("[data-overview-candidates] .candidate-card")).toHaveCount(0);
});

test("首頁資料庫摘要沒有 latest 列時顯示 empty", async ({ page }) => {
  await page.unroute(HOME_DATA_ROUTE);
  await routeHomeDataStatus(page, { body: null });
  await page.goto("/", { waitUntil: "domcontentloaded" });

  const panel = page.locator("[data-home-data-status]");
  await expect(panel).toHaveAttribute("data-state", "empty");
  await expect(panel).toContainText("尚無同步摘要");
});

test("首頁資料庫摘要請求失敗時顯示 error 且不使用舊資料", async ({ page }) => {
  await page.unroute(HOME_DATA_ROUTE);
  await routeHomeDataStatus(page, {
    status: 503,
    body: { code: "TEST_ONLY_FIXTURE", message: "unavailable" },
  });
  await page.goto("/", { waitUntil: "domcontentloaded" });

  const panel = page.locator("[data-home-data-status]");
  await expect(panel).toHaveAttribute("data-state", "error");
  await expect(panel).toContainText("無法讀取同步摘要");
  await expect(panel).toContainText("未以舊資料或假資料替代");
});

test("Supabase SDK 載入較慢時仍能完成登入初始化", async ({ page }) => {
  await stubSentry(page);
  let attempts = 0;
  await page.route("**/src/vendor/supabase-2.110.7.min.js*", async (route) => {
    attempts += 1;
    await new Promise((resolve) => setTimeout(resolve, 1_200));
    await route.continue();
  });

  await page.goto("/", { waitUntil: "domcontentloaded" });

  await expect(page.locator("body")).toHaveAttribute("data-auth-state", "anonymous");
  expect(attempts).toBe(1);
  expect(await capturedSentryErrors(page)).toEqual([]);
});

test("Supabase SDK 首次失敗時只重試一次並恢復", async ({ page }) => {
  await stubSentry(page);
  let attempts = 0;
  await page.route("**/src/vendor/supabase-2.110.7.min.js*", async (route) => {
    attempts += 1;
    if (attempts === 1) {
      await route.abort("failed");
      return;
    }
    await route.continue();
  });

  await page.goto("/", { waitUntil: "domcontentloaded" });

  await expect(page.locator("body")).toHaveAttribute("data-auth-state", "anonymous");
  expect(attempts).toBe(2);
  expect(await capturedSentryErrors(page)).toEqual([]);
});

test("Supabase SDK 持續失敗時停用登入且只回報一次", async ({ page }) => {
  await stubSentry(page);
  let attempts = 0;
  await page.route("**/src/vendor/supabase-2.110.7.min.js*", async (route) => {
    attempts += 1;
    await route.abort("failed");
  });

  await page.goto("/", { waitUntil: "domcontentloaded" });

  await expect(page.locator("body")).toHaveAttribute("data-auth-state", "unavailable");
  expect(attempts).toBe(2);
  expect(await page.locator("[data-auth-submit]").evaluateAll(
    (buttons) => buttons.every((button) => button.disabled),
  )).toBe(true);
  await expect.poll(() => capturedSentryErrors(page)).toHaveLength(1);
  expect(await capturedSentryErrors(page)).toEqual([
    expect.objectContaining({ code: "SUPABASE_SDK_LOAD_FAILED" }),
  ]);
});
