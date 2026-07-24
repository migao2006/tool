import { expect, test } from "@playwright/test";
import { routeHomeDataStatus } from "./support/home-data-status-fixture.mjs";
import { verifyTouchTarget } from "./support/mobile-audit-helpers.mjs";
import { retargetPredictionEvidence } from "./support/policy-evidence-fixture.mjs";

test.beforeEach(async ({ page }) => {
	await routeHomeDataStatus(page);
});

async function routeThreeStockSnapshot(
	page,
	{ systemStatus = "RESEARCH_ONLY" } = {},
) {
	await page.route("**/api/prediction-snapshot**", async (route) => {
		const response = await route.fetch();
		const payload = await response.json();
		payload.system_status = systemStatus;
		const template = payload.predictions[0];
		const allPassedGates = template.gates.map((gate) => ({
			...gate,
			passed: true,
			reason_code: "PASS",
		}));
		const noTradeGates = allPassedGates.map((gate) =>
			gate.gate === "net_quantile_thresholds"
				? {
						...gate,
						passed: false,
						reason_code: "NET_QUANTILE_THRESHOLD_FAIL",
					}
				: gate,
		);
		payload.predictions = [
			retargetPredictionEvidence({
				...template,
				symbol: "6515",
				name: "穎崴",
				decision: "CANDIDATE",
				global_rank: 1,
				industry_rank: 1,
				rank_score: 99,
				reason_codes: [],
				gates: allPassedGates,
			}),
			retargetPredictionEvidence({
				...template,
				symbol: "2330",
				name: "台積電",
				decision: "WATCH",
				global_rank: 2,
				industry_rank: 2,
				rank_score: 98,
				reason_codes: ["OUTSIDE_TOP_K"],
				gates: allPassedGates,
			}),
			retargetPredictionEvidence({
				...template,
				symbol: "2454",
				name: "聯發科",
				decision: "NO_TRADE",
				global_rank: 3,
				industry_rank: 3,
				rank_score: 97,
				reason_codes: ["NET_QUANTILE_THRESHOLD_FAIL"],
				gates: noTradeGates,
			}),
		];
		payload.decision_counts = {
			CANDIDATE: 1,
			WATCH: 1,
			NO_TRADE: 1,
			MISSING_REQUIRED_DATA: 0,
			VALIDATION_FAILED: 0,
			HARD_FAIL: payload.excluded.length,
		};
		await route.fulfill({ response, json: payload });
	});
}

async function openCandidates(page) {
	await page.goto("/", { waitUntil: "domcontentloaded" });
	await page
		.getByRole("navigation", { name: "主要導覽" })
		.getByRole("button", { name: "5 日候選" })
		.click();
}

test("正式 PASS 候選頁只顯示 CANDIDATE", async ({ page }) => {
	await routeThreeStockSnapshot(page, { systemStatus: "PASS" });
	await openCandidates(page);

	const cards = page.locator("[data-candidate-list] .candidate-card");
	await expect(cards).toHaveCount(1);
	await expect(cards.first()).toHaveAttribute("data-symbol", "6515");
	await expect(page.locator("[data-candidate-list]")).not.toContainText("台積電");
	await expect(page.locator("[data-candidate-list]")).not.toContainText("聯發科");
});

test("可用股票代號或名稱搜尋且不改變 Rank Score 順序", async ({ page }) => {
	await routeThreeStockSnapshot(page);
	await openCandidates(page);

	const search = page.getByRole("searchbox", { name: "搜尋股票" });
	const cards = page.locator("[data-candidate-list] .candidate-card");
	const symbols = () =>
		cards.evaluateAll((items) => items.map((item) => item.dataset.symbol));
	await expect(cards).toHaveCount(3);
	expect(await symbols()).toEqual(["6515", "2330", "2454"]);

	await search.fill("2330");
	await expect(cards).toHaveCount(1);
	expect(await symbols()).toEqual(["2330"]);

	await search.fill("台積");
	await expect(cards).toHaveCount(1);
	await expect(cards.first()).toHaveAttribute("data-symbol", "2330");

	await search.fill("２４５４");
	await expect(cards).toHaveCount(1);
	await expect(cards.first()).toHaveAttribute("data-symbol", "2454");

	await search.fill("不存在");
	await expect(cards).toHaveCount(0);
	await expect(page.locator("[data-candidate-list]")).toContainText(
		"沒有符合搜尋或篩選的股票",
	);

	const clear = page.getByRole("button", { name: "清除" });
	await expect(clear).toBeVisible();
	await clear.click();
	await expect(search).toHaveValue("");
	await expect(search).toBeFocused();
	await expect(clear).toBeHidden();
	await expect(cards).toHaveCount(3);
	expect(await symbols()).toEqual(["6515", "2330", "2454"]);

	await search.fill("FAIL1");
	await expect(cards).toHaveCount(0);
	await page.getByRole("button", { name: /資料排除/u }).click();
	const excluded = page.getByRole("dialog", { name: "排除清單" });
	await expect(excluded).toContainText("FAIL1");
	await expect(excluded).toContainText("DATA_QUALITY_HARD_FAIL");
});

test("320px 與 200% 大字仍可操作搜尋且沒有水平溢位", async ({ page }) => {
	await routeThreeStockSnapshot(page);
	await page.setViewportSize({ width: 320, height: 568 });
	await openCandidates(page);
	await page.evaluate(() => {
		document.documentElement.style.fontSize = "32px";
		document.documentElement.style.scrollBehavior = "auto";
	});

	const search = page.getByRole("searchbox", { name: "搜尋股票" });
	await search.fill("2330");
	const clear = page.getByRole("button", { name: "清除" });
	await expect(search).toBeVisible();
	await expect(clear).toBeVisible();
	await verifyTouchTarget(search);
	await verifyTouchTarget(clear);

	const layout = await page.evaluate(() => ({
		clientWidth: document.documentElement.clientWidth,
		scrollWidth: document.documentElement.scrollWidth,
		searchRight:
			document.querySelector(".candidate-search")?.getBoundingClientRect()
				.right ?? 0,
	}));
	expect(layout.scrollWidth).toBeLessThanOrEqual(layout.clientWidth + 1);
	expect(layout.searchRight).toBeLessThanOrEqual(layout.clientWidth + 1);
});

test("iPhone 使用自訂底部選單篩選，選完即關閉且可清除", async ({ page }) => {
	await routeThreeStockSnapshot(page);
	await openCandidates(page);

	const opener = page.locator('[data-open-drawer="candidate-filters"]');
	await expect(opener).toContainText("產業、風險與門檻");
	await opener.click();
	const drawer = page.getByRole("dialog", { name: "篩選候選股" });
	await expect(drawer).toBeVisible();

	const nativeSelect = drawer.locator('select[name="decision"]');
	const decisionTrigger = drawer.locator('[data-choice-for="decision"]');
	await expect(nativeSelect).toBeHidden();
	await verifyTouchTarget(decisionTrigger);
	await decisionTrigger.click();

	const choiceSheet = page.getByRole("dialog", { name: "選擇決策" });
	await expect(choiceSheet).toBeVisible();
	const watchOption = choiceSheet.getByRole("button", { name: "觀察" });
	await verifyTouchTarget(watchOption);
	await watchOption.click();
	await expect(choiceSheet).toBeHidden();
	await expect(decisionTrigger).toContainText("觀察");
	await expect(opener).toContainText("已套用 1 項");
	await expect(page.locator("[data-candidate-list] .candidate-card")).toHaveCount(1);
	await expect(page.locator('[data-candidate-list] .candidate-card[data-symbol="2330"]')).toBeVisible();

	await drawer.getByRole("button", { name: "清除全部" }).click();
	await expect(decisionTrigger).toContainText("全部");
	await expect(opener).toContainText("產業、風險與門檻");
	await expect(page.locator("[data-candidate-list] .candidate-card")).toHaveCount(3);
	await drawer.getByRole("button", { name: "完成", exact: true }).click();
	await expect(drawer).toBeHidden();
	await expect(opener).toBeFocused();
});

test("API 錯誤時搜尋功能會停用", async ({ page }) => {
	await page.goto("/?api_mode=invalid-json", { waitUntil: "domcontentloaded" });
	await page
		.getByRole("navigation", { name: "主要導覽" })
		.getByRole("button", { name: "5 日候選" })
		.click();

	await expect(page.locator("body")).toHaveAttribute(
		"data-ui-state",
		"api_error",
	);
	await expect(
		page.getByRole("searchbox", { name: "搜尋股票" }),
	).toBeDisabled();
});
