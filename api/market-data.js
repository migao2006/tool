import { handleMarketData } from "../src/market-data.js";
import { authorizeInternalRefresh } from "../src/internal-auth.js";

const json = (payload, status, headers = {}) => new Response(JSON.stringify(payload), {
  status,
  headers: {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store, max-age=0",
    ...headers,
  },
});

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const refreshRequested = url.searchParams.get("refresh") === "1";
    if (refreshRequested) {
      const secret = String(globalThis.process?.env?.TWSS_INTERNAL_REFRESH_TOKEN || "").trim();
      if (!await authorizeInternalRefresh(request, secret)) {
        return json({
          error: "refresh_forbidden",
          code: "REFRESH_FORBIDDEN",
        }, 403);
      }
    } else if (request.method !== "GET") {
      return json({ error: "method_not_allowed", code: "METHOD_NOT_ALLOWED" }, 405, {
        allow: "GET",
      });
    }
    return handleMarketData(request, url);
  },
};
