import assert from "node:assert/strict";
import {
  readV20GlobalMarket,
  v20GlobalMarketInternals,
} from "../src/v20-global-market.js";

function response(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

v20GlobalMarketInternals.resetCache();
const missingKeys = await readV20GlobalMarket({
  env: {},
  now: new Date("2026-07-16T02:00:00Z"),
  fetchImpl: async () => {
    throw new Error("must not request without keys");
  },
});
assert.equal(missingKeys.dataState, "partial");
assert.equal(missingKeys.completeness, 0);
assert.deepEqual(missingKeys.indicators, []);
assert.ok(missingKeys.degradedSources.includes("finnhub:missing_server_key"));
assert.ok(missingKeys.degradedSources.includes("alpha-vantage:missing_server_key"));

v20GlobalMarketInternals.resetCache();
const calls = [];
const complete = await readV20GlobalMarket({
  env: { FINNHUB_API_KEY: "server-finnhub", ALPHA_VANTAGE_API_KEY: "server-alpha" },
  now: new Date("2026-07-16T02:00:00Z"),
  fetchImpl: async (input) => {
    const url = new URL(input);
    calls.push(url);
    assert.ok(!url.toString().includes("undefined"));
    if (url.hostname === "finnhub.io") {
      return response({ c: 100, d: 1, dp: 1.01, pc: 99, t: 1784156400 });
    }
    if (url.searchParams.get("function") === "TREASURY_YIELD") {
      return response({ data: [{ date: "2026-07-15", value: "4.23" }] });
    }
    return response({
      "Realtime Currency Exchange Rate": {
        "5. Exchange Rate": "29.6500",
        "6. Last Refreshed": "2026-07-15 23:59:00",
      },
    });
  },
});
assert.equal(calls.length, 8);
assert.equal(complete.dataState, "complete");
assert.equal(complete.completeness, 100);
assert.equal(complete.indicators.length, 8);
assert.equal(complete.indicators.find((item) => item.key === "sp500").proxy, true);
assert.equal(complete.indicators.find((item) => item.key === "us10y").value, 4.23);
assert.equal(complete.indicators.find((item) => item.key === "usdTwd").value, 29.65);
assert.ok(calls.every((url) => url.searchParams.has(url.hostname === "finnhub.io" ? "token" : "apikey")));

console.log("v20 global market tests passed");
