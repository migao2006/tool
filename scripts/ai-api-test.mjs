import assert from "node:assert/strict";
import handler from "../api/ai-research.js";

const originalFetch = globalThis.fetch;
const calls = [];
globalThis.fetch = async (input, options = {}) => {
  const url = new URL(String(input));
  calls.push({ url, options });
  if (url.pathname === "/auth/v1/user") {
    return Response.json({ id: "00000000-0000-4000-8000-000000000001", email: "test@example.test" });
  }
  if (url.pathname === "/functions/v1/twss-ai-research") {
    return Response.json({
      available: true,
      cached: false,
      symbol: "2330",
      analysis: { verdict: "中性觀察", summary: "測試摘要", aiConfidence: 70 },
    });
  }
  throw new Error(`unexpected URL ${url}`);
};

try {
  const invalid = await handler.fetch(new Request("https://example.test/api/ai-research", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ symbol: "2330' or true" }),
  }));
  assert.equal(invalid.status, 400);

  const anonymous = await handler.fetch(new Request("https://example.test/api/ai-research", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ symbol: "2330" }),
  }));
  assert.equal(anonymous.status, 401);
  assert.equal((await anonymous.json()).code, "LOGIN_REQUIRED");

  const authorized = await handler.fetch(new Request("https://example.test/api/ai-research", {
    method: "POST",
    headers: { "content-type": "application/json", authorization: "Bearer test-user-jwt" },
    body: JSON.stringify({ symbol: "2330" }),
  }));
  assert.equal(authorized.status, 200);
  assert.equal((await authorized.json()).available, true);
  assert.equal(calls.filter(({ url }) => url.pathname === "/auth/v1/user").length, 1);
  const edgeCall = calls.find(({ url }) => url.pathname === "/functions/v1/twss-ai-research");
  assert.equal(edgeCall.options.headers.authorization, "Bearer test-user-jwt");
  assert.equal("x-twss-sync-token" in edgeCall.options.headers, false);
  assert.equal(JSON.parse(edgeCall.options.body).mode, "manual");
  assert.equal(JSON.parse(edgeCall.options.body).symbol, "2330");
} finally {
  globalThis.fetch = originalFetch;
}

console.log("AI API tests passed: authenticated manual proxy, input validation, and no sync-token exposure");
