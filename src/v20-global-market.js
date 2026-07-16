// Alpha Vantage free keys are intentionally treated as a low-frequency source.
// The public UI must consume the cached result instead of refreshing per user.
const CACHE_TTL_MS = 6 * 60 * 60 * 1000;
const REQUEST_TIMEOUT_MS = 7_000;

const FINNHUB_QUOTES = Object.freeze([
  { key: "sp500", label: "S&P 500（SPY ETF 代理）", symbol: "SPY", proxy: true },
  { key: "nasdaq", label: "NASDAQ 100（QQQ ETF 代理）", symbol: "QQQ", proxy: true },
  { key: "sox", label: "SOX（SOXX ETF 代理）", symbol: "SOXX", proxy: true },
  { key: "tsmAdr", label: "台積電 ADR", symbol: "TSM", proxy: false },
  { key: "nvidia", label: "NVIDIA", symbol: "NVDA", proxy: false },
  { key: "vix", label: "VIX", symbol: "^VIX", proxy: false },
]);

let cache = null;

const finite = (value) => value != null && Number.isFinite(Number(value));
const round = (value, digits = 4) => finite(value) ? Number(Number(value).toFixed(digits)) : null;

function newYorkDate(timestampSeconds) {
  if (!finite(timestampSeconds) || Number(timestampSeconds) <= 0) return null;
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date(Number(timestampSeconds) * 1000));
  const fields = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${fields.year}-${fields.month}-${fields.day}`;
}

async function fetchJson(url, fetchImpl) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetchImpl(url, {
      signal: controller.signal,
      headers: { accept: "application/json" },
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}

function finnhubUrl(symbol, token) {
  const url = new URL("https://finnhub.io/api/v1/quote");
  url.searchParams.set("symbol", symbol);
  url.searchParams.set("token", token);
  return url;
}

function alphaUrl(parameters, apiKey) {
  const url = new URL("https://www.alphavantage.co/query");
  Object.entries(parameters).forEach(([key, value]) => url.searchParams.set(key, value));
  url.searchParams.set("apikey", apiKey);
  return url;
}

async function readFinnhubQuote(definition, token, fetchImpl) {
  const payload = await fetchJson(finnhubUrl(definition.symbol, token), fetchImpl);
  if (!finite(payload?.c) || Number(payload.c) <= 0 || !finite(payload?.t)) {
    throw new Error("quote_unavailable");
  }
  return {
    key: definition.key,
    label: definition.label,
    symbol: definition.symbol,
    value: round(payload.c),
    change: round(payload.d),
    changePercent: round(payload.dp),
    previousClose: round(payload.pc),
    dataDate: newYorkDate(payload.t),
    source: "finnhub",
    proxy: definition.proxy,
  };
}

async function readTreasuryYield(apiKey, fetchImpl) {
  const payload = await fetchJson(alphaUrl({
    function: "TREASURY_YIELD",
    interval: "daily",
    maturity: "10year",
  }, apiKey), fetchImpl);
  const row = Array.isArray(payload?.data)
    ? payload.data.find((item) => finite(item?.value))
    : null;
  if (!row) throw new Error("treasury_unavailable");
  return {
    key: "us10y",
    label: "美國 10 年期公債殖利率",
    symbol: "US10Y",
    value: round(row.value),
    change: null,
    changePercent: null,
    previousClose: null,
    dataDate: /^\d{4}-\d{2}-\d{2}$/.test(String(row.date || "")) ? row.date : null,
    source: "alpha-vantage",
    proxy: false,
  };
}

async function readUsdTwd(apiKey, fetchImpl) {
  const payload = await fetchJson(alphaUrl({
    function: "CURRENCY_EXCHANGE_RATE",
    from_currency: "USD",
    to_currency: "TWD",
  }, apiKey), fetchImpl);
  const row = payload?.["Realtime Currency Exchange Rate"];
  const value = row?.["5. Exchange Rate"];
  if (!finite(value)) throw new Error("fx_unavailable");
  return {
    key: "usdTwd",
    label: "美元兌新台幣",
    symbol: "USD/TWD",
    value: round(value),
    change: null,
    changePercent: null,
    previousClose: null,
    dataDate: String(row?.["6. Last Refreshed"] || "").slice(0, 10) || null,
    source: "alpha-vantage",
    proxy: false,
  };
}

function mergeLastGood(current, previous) {
  const rows = new Map((previous?.indicators || []).map((item) => [item.key, item]));
  for (const item of current) rows.set(item.key, item);
  return [...rows.values()];
}

export async function readV20GlobalMarket(options = {}) {
  const env = options.env || globalThis.process?.env || {};
  const fetchImpl = options.fetchImpl || globalThis.fetch;
  const now = options.now instanceof Date ? options.now : new Date();
  if (typeof fetchImpl !== "function") throw new TypeError("fetch implementation is required");
  if (!options.force && cache?.expiresAt > now.getTime()) return cache.value;

  const finnhubKey = String(env.FINNHUB_API_KEY || "").trim();
  const alphaKey = String(env.ALPHA_VANTAGE_API_KEY || "").trim();
  const degradedSources = [];
  const tasks = [];

  if (finnhubKey) {
    FINNHUB_QUOTES.forEach((definition) => {
      tasks.push({
        source: `finnhub:${definition.key}`,
        promise: readFinnhubQuote(definition, finnhubKey, fetchImpl),
      });
    });
  } else {
    degradedSources.push("finnhub:missing_server_key");
  }

  if (alphaKey) {
    tasks.push({ source: "alpha-vantage:us10y", promise: readTreasuryYield(alphaKey, fetchImpl) });
    tasks.push({ source: "alpha-vantage:usdTwd", promise: readUsdTwd(alphaKey, fetchImpl) });
  } else {
    degradedSources.push("alpha-vantage:missing_server_key");
  }

  const settled = await Promise.allSettled(tasks.map((task) => task.promise));
  const fresh = [];
  settled.forEach((result, index) => {
    if (result.status === "fulfilled") fresh.push(result.value);
    else degradedSources.push(`${tasks[index].source}:update_failed`);
  });

  const indicators = mergeLastGood(fresh, cache?.value);
  const expectedCount = FINNHUB_QUOTES.length + 2;
  const sourceDates = Object.fromEntries(
    indicators.filter((item) => item.dataDate).map((item) => [item.key, item.dataDate]),
  );
  const value = {
    dataState: indicators.length === expectedCount && !degradedSources.length ? "complete" : "partial",
    dataDate: Object.values(sourceDates).sort().at(-1) || null,
    sourceDates,
    fetchedAt: now.toISOString(),
    completeness: round((indicators.length / expectedCount) * 100, 1),
    degradedSources: [...new Set(degradedSources)],
    indicators,
  };
  cache = { value, expiresAt: now.getTime() + CACHE_TTL_MS };
  return value;
}

export const v20GlobalMarketInternals = {
  FINNHUB_QUOTES,
  newYorkDate,
  resetCache() {
    cache = null;
  },
};
