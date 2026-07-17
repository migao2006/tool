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
      "x-twss-api-version": "20.2",
      "cache-control": status < 400 ? CACHE_CONTROL : "no-store, max-age=0",
      "cdn-cache-control": status < 400 ? CDN_CACHE_CONTROL : "no-store",
      "vercel-cdn-cache-control": status < 400 ? CDN_CACHE_CONTROL : "no-store",
      ...headers,
    },
  });
}

function requestId(request) {
  const platformId = request.headers.get("x-vercel-id") || request.headers.get("x-request-id");
  if (platformId) return String(platformId).replace(/[^a-zA-Z0-9_.:-]/g, "").slice(0, 120) || "unknown";
  return globalThis.crypto?.randomUUID?.() || "unknown";
}

function logRequest(level, payload) {
  const entry = JSON.stringify({ service: "twss-v20-api", ...payload });
  if (level === "error") console.error(entry);
  else console.log(entry);
}

export async function handleV20(request, reader, options = {}) {
  const startedAt = Date.now();
  const url = new URL(request.url);
  const route = url.pathname;
  const id = requestId(request);
  logRequest("info", { level: "info", msg: "start", route, method: request.method, requestId: id });

  const done = (response) => {
    logRequest("info", {
      level: "info",
      msg: "done",
      route,
      method: request.method,
      requestId: id,
      status: response.status,
      ms: Date.now() - startedAt,
    });
    return response;
  };

  const methods = Array.isArray(options.methods) && options.methods.length
    ? [...new Set(options.methods.map((method) => String(method).toUpperCase()))]
    : ["GET"];
  const allowMethods = [...methods, "OPTIONS"].join(", ");
  const allowHeaders = Array.isArray(options.allowHeaders) && options.allowHeaders.length
    ? [...new Set(options.allowHeaders.map(String))].join(", ")
    : "content-type";

  if (request.method === "OPTIONS") {
    return done(new Response(null, {
      status: 204,
      headers: {
        "access-control-allow-origin": "*",
        "access-control-allow-methods": allowMethods,
        "access-control-allow-headers": allowHeaders,
        "cache-control": "no-store",
      },
    }));
  }
  if (!methods.includes(request.method.toUpperCase())) {
    return done(json({ error: { code: "method_not_allowed", message: `${methods.join(", ")} only` } }, 405, {
      allow: allowMethods,
    }));
  }
  try {
    return done(json(await reader(url)));
  } catch (error) {
    if (error instanceof V20PublicError) {
      return done(json({ error: { code: error.code, message: error.message } }, error.status));
    }
    logRequest("error", {
      level: "error",
      msg: "failed",
      route,
      method: request.method,
      requestId: id,
      status: 503,
      kind: error instanceof Error ? error.name : "unknown",
      ms: Date.now() - startedAt,
    });
    return json({ error: { code: "temporarily_unavailable", message: "Service temporarily unavailable" } }, 503);
  }
}

export const v20ApiInternals = { json, requestId, logRequest, CACHE_CONTROL, CDN_CACHE_CONTROL };
