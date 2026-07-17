import assert from "node:assert/strict";
import marketDataApi from "../api/market-data.js";

const original = process.env.TWSS_INTERNAL_REFRESH_TOKEN;
try {
  process.env.TWSS_INTERNAL_REFRESH_TOKEN = "internal-refresh-test-token";

  const publicRefresh = await marketDataApi.fetch(new Request(
    "https://smart.example/api/market-data?type=sources&refresh=1",
  ));
  assert.equal(publicRefresh.status, 403);
  assert.equal((await publicRefresh.json()).code, "REFRESH_FORBIDDEN");

  const wrongToken = await marketDataApi.fetch(new Request(
    "https://smart.example/api/market-data?type=sources&refresh=1",
    { method: "POST", headers: { "x-twss-refresh-token": "wrong" } },
  ));
  assert.equal(wrongToken.status, 403);

  const internalRefresh = await marketDataApi.fetch(new Request(
    "https://smart.example/api/market-data?type=sources&refresh=1",
    {
      method: "POST",
      headers: { "x-twss-refresh-token": process.env.TWSS_INTERNAL_REFRESH_TOKEN },
    },
  ));
  assert.equal(internalRefresh.status, 200);

  const publicRead = await marketDataApi.fetch(new Request(
    "https://smart.example/api/market-data?type=sources",
  ));
  assert.equal(publicRead.status, 200);

  const unrequestedPost = await marketDataApi.fetch(new Request(
    "https://smart.example/api/market-data?type=sources",
    { method: "POST" },
  ));
  assert.equal(unrequestedPost.status, 405);

  console.log("Market-data refresh authorization tests passed");
} finally {
  if (original === undefined) delete process.env.TWSS_INTERNAL_REFRESH_TOKEN;
  else process.env.TWSS_INTERNAL_REFRESH_TOKEN = original;
}
