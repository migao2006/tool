import { V20PublicError } from "../../src/v20-backend.js";

const CACHE_CONTROL = "no-store, max-age=0";
const CDN_CACHE_CONTROL = "public, s-maxage=60, stale-while-revalidate=300";

function json(payload, status = 200, headers = {}) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "x-content-type-options": "nosniff",
      "access-control-allow-origin": "*",
      "x-twss-api-version": "20.0",
      "cache-control": status < 400 ? CACHE_CONTROL : "no-store, max-age=0",
      "cdn-cache-control": status < 400 ? CDN_CACHE_CONTROL : "no-store",
      "vercel-cdn-cache-control": status < 400 ? CDN_CACHE_CONTROL : "no-store",
      ...headers,
    },
  });
}

export async function handleV20(request, reader) {
  if (request.method === "OPTIONS") {
    return new Response(null, {
      status: 204,
      headers: {
        "access-control-allow-origin": "*",
        "access-control-allow-methods": "GET, OPTIONS",
        "access-control-allow-headers": "content-type",
        "cache-control": "no-store",
      },
    });
  }
  if (request.method !== "GET") {
    return json({ error: { code: "method_not_allowed", message: "GET only" } }, 405, {
      allow: "GET, OPTIONS",
    });
  }
  try {
    return json(await reader(new URL(request.url)));
  } catch (error) {
    if (error instanceof V20PublicError) {
      return json({ error: { code: error.code, message: error.message } }, error.status);
    }
    console.error("[v20-api] request failed", {
      path: new URL(request.url).pathname,
      kind: error instanceof Error ? error.name : "unknown",
    });
    return json({ error: { code: "temporarily_unavailable", message: "Service temporarily unavailable" } }, 503);
  }
}

export const v20ApiInternals = { json, CACHE_CONTROL, CDN_CACHE_CONTROL };
