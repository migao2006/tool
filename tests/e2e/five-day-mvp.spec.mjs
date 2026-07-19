import { expect, test } from "@playwright/test";
import { HOME_DATA_ROUTE, routeHomeDataStatus } from "./support/home-data-status-fixture.mjs";

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
  const marketPanel = page.getByRole("region", { name: "市場判斷" });
  const dataPanel = page.getByRole("region", { name: "資料庫同步摘要" });
  const [marketBox, dataBox] = await Promise.all([marketPanel.boundingBox(), dataPanel.boundingBox()]);
  expect(marketBox).not.toBeNull();
  expect(dataBox).not.toBeNull();
  expect(dataBox.y).toBeGreaterThan(marketBox.y);
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
  await expect(page.locator('[data-stock-field="decision_at"]')).toHaveText("2026/07/17 16:00");
});

test("大量候選結果在手機分批顯示", async ({ page }) => {
  await page.route("**/api/prediction-snapshot**", async (route) => {
    const response = await route.fetch();
    const payload = await response.json();
    const template = payload.predictions[0];
    payload.predictions = Array.from({ length: 80 }, (_, index) => ({
      ...template,
      symbol: `T${String(index + 1).padStart(4, "0")}`,
      global_rank: index + 1,
      industry_rank: index + 1,
      rank_score: 100 - index * 0.1,
    }));
    await route.fulfill({ response, json: payload });
  });

  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.getByRole("navigation", { name: "主要導覽" })
    .getByRole("button", { name: "5 日候選" })
    .click();

  const cards = page.locator('[data-candidate-list] .candidate-card');
  await expect(cards).toHaveCount(25);
  await expect(page.locator("[data-candidate-pagination-summary]")).toHaveText("目前顯示 25／80 檔");
  await page.getByRole("button", { name: "顯示更多" }).click();
  await expect(cards).toHaveCount(50);
  await expect(page.locator("[data-candidate-pagination-summary]")).toHaveText("目前顯示 50／80 檔");

  await page.locator("[data-candidate-filters] summary").click();
  const rankScoreMinimum = page.locator('[data-candidate-filters] input[name="rank_score_min"]');
  await rankScoreMinimum.fill("99");
  await expect(cards).toHaveCount(11);
  await expect(page.locator("[data-candidate-pagination]")).toBeHidden();

  await rankScoreMinimum.fill("");
  await expect(cards).toHaveCount(25);
  await expect(page.locator("[data-candidate-pagination-summary]")).toHaveText("目前顯示 25／80 檔");
  await page.getByRole("button", { name: "顯示更多" }).click();
  await page.getByRole("button", { name: "顯示更多" }).click();
  await page.getByRole("button", { name: "顯示更多" }).click();
  await expect(cards).toHaveCount(80);
  const paginationSummary = page.locator("[data-candidate-pagination-summary]");
  await expect(paginationSummary).toHaveText("目前顯示 80／80 檔");
  await expect(paginationSummary).toBeFocused();
  await expect(page.getByRole("button", { name: "顯示更多" })).toBeHidden();
});

test("裝置研究偏好不會破壞已發布的固定快照請求", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("alpha-lens:five-day-research-settings", JSON.stringify({
      commission_discount: 0.5,
      cost_profile: "base_cost",
      max_adv_participation: 0.01,
    }));
  });
  const predictionUrls = [];
  page.on("request", (request) => {
    if (request.url().includes("prediction-snapshot")) predictionUrls.push(request.url());
  });

  await page.goto("/", { waitUntil: "domcontentloaded" });

  await expect(page.locator("body")).toHaveAttribute("data-ui-state", "ready");
  expect(predictionUrls.length).toBeGreaterThan(0);
  predictionUrls.forEach((value) => {
    const url = new URL(value);
    expect(url.searchParams.get("horizon")).toBe("5");
    expect(url.searchParams.has("cost_profile")).toBe(false);
    expect(url.searchParams.has("commission_discount")).toBe(false);
    expect(url.searchParams.has("max_adv_participation")).toBe(false);
  });
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
  await expect(page.locator("[data-candidate-pagination]")).toBeHidden();
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

test("歷史 OOS 研究快照的 NO_TRADE 排序與已完成輸出仍可檢視", async ({ page }) => {
  await page.goto("/?api_mode=stale-oos-research", { waitUntil: "domcontentloaded" });

  await expect(page.locator("body")).toHaveAttribute("data-ui-state", "research_only");
  const banner = page.locator('[data-page="home"] .system-banner').first();
  await expect(banner).toHaveClass(/is-badge-only/u);
  await expect(banner.locator("[data-system-status-label]")).toHaveText("RESEARCH_ONLY");
  await expect(banner.locator("[data-status-copy]")).toBeHidden();
  await expect(page.locator("[data-overview-list-title]")).toHaveText("5 日歷史研究排序");
  const overviewCard = page.locator('[data-overview-candidates] .candidate-card[data-symbol="OOS1"]');
  await expect(overviewCard).toBeVisible();
  await expect(overviewCard).toContainText("Rank Score 97.0");
  await expect(overviewCard).toContainText("校準後 UP 61.0%");
  await expect(overviewCard).toContainText("條件 P50 1.3%");
  await expect(overviewCard).not.toContainText("FORMAL_LABEL_FACTORY_NOT_USED");
  await expect(page.locator('[data-overview-count="NO_TRADE"]')).toHaveText("1");

  const navigation = page.getByRole("navigation", { name: "主要導覽" });
  await navigation.getByRole("button", { name: "5 日候選" }).click();
  await expect(page.locator('[data-candidate-filters] select[name="decision"]')).toBeEnabled();
  await expect(page.locator('[data-candidate-filters] button[data-value="TWSE"]')).toBeEnabled();
  await expect(page.locator("[data-candidate-list-title]")).toHaveText("5 日歷史研究結果");
  const researchCard = page.locator('[data-candidate-list] .candidate-card[data-symbol="OOS1"]');
  await expect(researchCard).toBeVisible();
  await expect(researchCard.locator(".decision-badge")).toHaveText("NO_TRADE");
  await expect(researchCard).toContainText("97.0");
  await expect(researchCard).toContainText("61.0%／27.0%／12.0%");
  await expect(researchCard).toContainText("-2.4%／1.3%／4.6%");
  await expect(researchCard.locator("[data-reason-summary]")).toHaveText(
    "RESEARCH_ONLY_NO_FORMAL_DECISION_POLICY · UNADJUSTED_PRICE_RESEARCH_ONLY · 另 3 項稽核資訊",
  );
  await expect(researchCard).not.toContainText("FORMAL_LABEL_FACTORY_NOT_USED");

  await researchCard.getByRole("button", { name: "查看決策詳情" }).click();
  await expect(page.getByRole("heading", { name: /OOS1/u })).toBeVisible();
  await expect(page.locator('[data-stock-field="decision"]')).toHaveText("NO_TRADE");
  await expect(page.locator('[data-stock-field="rank_score"]')).toHaveText("97.0");
  await expect(page.locator('[data-stock-field="calibrated_p_up"]')).toHaveText("61.0%");
  await expect(page.locator('[data-stock-field="net_q10"]')).toHaveText("-2.4%");
  await expect(page.locator('[data-stock-field="net_q50"]')).toHaveText("1.3%");
  await expect(page.locator('[data-stock-field="net_q90"]')).toHaveText("4.6%");
  await expect(page.locator(".decision-gates code")).toHaveText(
    Array(8).fill("RESEARCH_ONLY_NO_FORMAL_DECISION_POLICY"),
  );
  await expect(page.locator("[data-stock-gate-state]")).toHaveText("正式決策政策尚未執行");
  await expect(page.locator('[data-stock-field="reason_codes"]')).toHaveText(
    "RESEARCH_ONLY_NO_FORMAL_DECISION_POLICY · UNADJUSTED_PRICE_RESEARCH_ONLY · 另 3 項稽核資訊",
  );
  const auditDetails = page.locator(".audit-details");
  await expect(auditDetails).not.toHaveAttribute("open", "");
  await auditDetails.getByText("技術稽核資訊").click();
  await expect(auditDetails.locator('[data-audit-field="reason_codes"]')).toHaveText(
    "RESEARCH_ONLY_NO_FORMAL_DECISION_POLICY · UNADJUSTED_PRICE_RESEARCH_ONLY · FORMAL_LABEL_FACTORY_NOT_USED · POINT_IN_TIME_IDENTITY_UNVERIFIED · MARKET_EXPOSURE_NOT_AVAILABLE",
  );
});

test("研究決策政策會顯示八層真實 gate 並維持 NO_TRADE", async ({ page }) => {
	await page.goto("/?api_mode=gated-research", {
		waitUntil: "domcontentloaded",
	});

	await expect(page.locator("body")).toHaveAttribute(
		"data-ui-state",
		"research_only",
	);
	const navigation = page.getByRole("navigation", { name: "主要導覽" });
	await navigation.getByRole("button", { name: "5 日候選" }).click();
	const card = page.locator(
		'[data-candidate-list] .candidate-card[data-symbol="GATED1"]',
	);
	await expect(card).toBeVisible();
	await expect(card.locator(".decision-badge")).toHaveText("NO_TRADE");
	await card.getByRole("button", { name: "查看決策詳情" }).click();

	await expect(page.locator("[data-stock-gate-state]")).toHaveText(
		"研究決策 gate 已評估",
	);
	const gates = page.locator(".decision-gates > li");
	await expect(gates).toHaveCount(8);
	await expect(
		gates.filter({ has: page.locator(".gate-step") }).locator(".gate-step"),
	).toHaveCount(8);
	await expect(page.locator(".decision-gates > li.is-pass")).toHaveCount(4);
	await expect(page.locator(".decision-gates > li.is-fail")).toHaveCount(4);
	const liquidity = page.locator('[data-gate="liquidity_capacity_gate"]');
	await expect(liquidity).toContainText("通過");
	await expect(liquidity).toContainText('"adv20_ntd":1000000000');
	await expect(liquidity).toContainText("2026-07-17");
	const tradability = page.locator('[data-gate="tradability_gate"]');
	await expect(tradability).toContainText("未通過");
	await expect(tradability).toContainText("MISSING");
	await expect(tradability).toContainText("FORMAL_INPUT_MISSING");
	await expect(page.locator('[data-page="stock"]')).not.toContainText(
		"正式決策政策尚未執行",
	);
	await expect(page.locator('[data-page="stock"]')).not.toContainText(
		"RESEARCH_ONLY_NO_FORMAL_DECISION_POLICY",
	);
});

test("研究快照 gate 缺漏時會 fail closed", async ({ page }) => {
	await page.goto("/?api_mode=partial-gates", {
		waitUntil: "domcontentloaded",
	});

	await expect(page.locator("body")).toHaveAttribute(
		"data-ui-state",
		"api_error",
	);
	await expect(page.locator("body")).toHaveAttribute(
		"data-system-status",
		"FAIL",
	);
	await expect(
		page.locator("[data-candidate-list] .candidate-card"),
	).toHaveCount(0);
});

test("正式 PASS 快照若過期仍維持 fail-closed", async ({ page }) => {
  await page.goto("/contract-test", { waitUntil: "domcontentloaded" });

  const resolvedState = await page.evaluate(async () => {
    const { resolveSnapshotUiState } = await import("/src/core/ui-state.js");
    return resolveSnapshotUiState({
      systemStatus: "PASS",
      stale: true,
      dataQualityHardFail: false,
      predictions: [{ decision: "CANDIDATE" }],
      candidates: [{ decision: "CANDIDATE" }],
      reasonCodes: [],
    });
  });

  expect(resolvedState).toBe("stale");
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
