const DEFAULT_URL = "https://lfkdkdyaatdlizryiyon.supabase.co";
const DEFAULT_PUBLIC_KEY = "sb_publishable_r3h9eQIYdIqScvmc77avAg_OLgBT6lh";

const env = globalThis.process?.env || {};
const SUPABASE_URL = env.SUPABASE_URL || DEFAULT_URL;
const SUPABASE_PUBLIC_KEY =
  env.SUPABASE_PUBLISHABLE_KEY || env.SUPABASE_ANON_KEY || DEFAULT_PUBLIC_KEY;

function response(payload, status = 200) {
  return Response.json(payload, {
    status,
    headers: { "cache-control": "no-store, max-age=0" },
  });
}

async function fetchWithTimeout(url, options, timeout = 120_000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    return await fetch(url, { ...options, signal: controller.signal, cache: "no-store" });
  } finally {
    clearTimeout(timer);
  }
}

async function verifiedUser(authorization) {
  if (!authorization?.startsWith("Bearer ")) return null;
  const result = await fetchWithTimeout(`${SUPABASE_URL}/auth/v1/user`, {
    headers: {
      accept: "application/json",
      apikey: SUPABASE_PUBLIC_KEY,
      authorization,
    },
  }, 20_000);
  if (!result.ok) return null;
  const user = await result.json().catch(() => null);
  return user?.id ? user : null;
}

export default {
  async fetch(request) {
    if (request.method !== "POST") return response({ error: "Method not allowed" }, 405);
    let body;
    try {
      body = await request.json();
    } catch {
      return response({ error: "請求格式不正確", code: "INVALID_REQUEST" }, 400);
    }
    const symbol = String(body?.symbol || "").trim().toUpperCase();
    if (!/^\d{4,6}[A-Z]?$/.test(symbol)) {
      return response({ error: "股票代號格式不正確", code: "INVALID_SYMBOL" }, 400);
    }
    const authorization = request.headers.get("authorization") || "";
    let user;
    try {
      user = await verifiedUser(authorization);
    } catch {
      return response({ error: "登入驗證暫時無法完成", code: "AUTH_UNAVAILABLE" }, 503);
    }
    if (!user) {
      return response({ error: "請先登入再產生 AI 研究摘要", code: "LOGIN_REQUIRED" }, 401);
    }
    try {
      const upstream = await fetchWithTimeout(`${SUPABASE_URL}/functions/v1/twss-ai-research`, {
        method: "POST",
        headers: {
          accept: "application/json",
          "content-type": "application/json",
          apikey: SUPABASE_PUBLIC_KEY,
          authorization,
        },
        body: JSON.stringify({ mode: "manual", symbol }),
      });
      const payload = await upstream.json().catch(() => ({
        error: "AI 研究服務回應格式不正確",
        code: "AI_BAD_RESPONSE",
      }));
      return response(payload, upstream.status);
    } catch (error) {
      const timedOut = error?.name === "AbortError";
      return response({
        error: timedOut ? "AI 研究處理逾時，請稍後重試" : "AI 研究服務暫時無法連線",
        code: timedOut ? "AI_TIMEOUT" : "AI_UNAVAILABLE",
      }, timedOut ? 504 : 502);
    }
  },
};
