export const TEST_ONLY_HOME_DATA_STATUS = Object.freeze({
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

export const HOME_DATA_ROUTE = "**/rest/v1/home_data_status*";

export async function routeHomeDataStatus(
  page,
  { body = TEST_ONLY_HOME_DATA_STATUS, delayMs = 0, status = 200 } = {},
) {
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
    if (delayMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, delayMs));
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
