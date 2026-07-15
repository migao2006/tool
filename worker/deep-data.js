const TWSE_OPEN = "https://openapi.twse.com.tw/v1";
const TPEX_OPEN = "https://www.tpex.org.tw/openapi/v1";
const TAIFEX_OPEN = "https://openapi.taifex.com.tw/v1";
const FINMIND = "https://api.finmindtrade.com/api/v4/data";
const TDCC_HOLDINGS = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5";
export const ANALYSIS_VERSION = "16.3-ultimate-data-audit";
const VALID_SYMBOL = /^\d{4,6}[A-Z]?$/i;
const ETF_SYMBOL = /^00\d{2,4}[A-Z]?$/i;

const memoryCache = new Map();
const queues = new Map();
const policies = [
  // The documented FinMind ceiling is hourly, not a one-request-per-second
  // ceiling.  The persistent worker now reserves every call in a sliding
  // 60-minute database ledger, so a short two-lane burst is safe and keeps an
  // Edge invocation well inside its wall-clock limit.
  { match: "api.finmindtrade.com", key: "finmind", gap: 500, concurrency: 2 },
  { match: "openapi.twse.com.tw", key: "twse", gap: 1_250, concurrency: 2 },
  { match: "www.tpex.org.tw", key: "tpex", gap: 1_250, concurrency: 2 },
  { match: "openapi.taifex.com.tw", key: "taifex", gap: 1_250, concurrency: 1 },
  { match: "opendata.tdcc.com.tw", key: "tdcc", gap: 2_000, concurrency: 1 },
];
const providerCircuits = new Map();
const FINMIND_CIRCUIT_CODE = "FINMIND_PROVIDER_COOLDOWN";

const finite = (value) => value != null && Number.isFinite(Number(value));
const number = (value) => {
  if (value == null) return null;
  const cleaned = String(value).trim().replaceAll(",", "").replaceAll("%", "");
  if (!cleaned || ["-", "--", "N/A", "null"].includes(cleaned)) return null;
  const parsed = Number(cleaned.replace(/^\+/, ""));
  return Number.isFinite(parsed) ? parsed : null;
};
const clean = (value) => (value == null ? "" : String(value).trim());
const mean = (values) => {
  const usable = values.filter(finite).map(Number);
  return usable.length ? usable.reduce((sum, value) => sum + value, 0) / usable.length : null;
};
const sum = (values) => values.filter(finite).reduce((total, value) => total + Number(value), 0);
const round = (value, digits = 4) =>
  finite(value) ? Number(Number(value).toFixed(digits)) : null;
const clamp = (value, low, high) => Math.max(low, Math.min(high, value));

function configuredFinmindToken(explicitToken = "") {
  try {
    const direct = String(explicitToken || "").trim();
    if (direct) return direct;
    return String(
      globalThis.process?.env?.FINMIND_TOKEN ||
      globalThis.Deno?.env?.get?.("FINMIND_TOKEN") ||
      "",
    ).trim();
  } catch {
    return "";
  }
}

function finmindCooldownMs(error) {
  const status = Number(error?.status) || 0;
  const message = String(error?.message || "");
  const invalidCredential = status === 401 || status === 403 || (
    status === 400 && (
      /(?:invalid|expired|missing|unauthorized).{0,40}(?:token|authorization)/i.test(message) ||
      /(?:token|authorization).{0,40}(?:invalid|expired|missing|unauthorized)/i.test(message)
    )
  );
  if (invalidCredential || status === 402) return 60 * 60 * 1_000;
  if (status === 429) {
    const retryAfterMs = Number(error?.retryAfter) > 0
      ? Number(error.retryAfter) * 1_000
      : 5 * 60 * 1_000;
    return Math.min(60 * 60 * 1_000, Math.max(60 * 1_000, retryAfterMs));
  }
  return 0;
}

function tripProviderCircuit(url, error) {
  const policy = policyFor(url);
  if (policy.key !== "finmind") return false;
  const cooldownMs = finmindCooldownMs(error);
  if (!cooldownMs) return false;
  const blockedUntil = Date.now() + cooldownMs;
  const existing = providerCircuits.get(policy.key);
  if (!existing || blockedUntil > existing.blockedUntil) {
    providerCircuits.set(policy.key, {
      blockedUntil,
      providerStatus: Number(error?.status) || null,
    });
  }
  try {
    error.code = FINMIND_CIRCUIT_CODE;
  } catch {}
  return true;
}

function assertProviderAvailable(url) {
  const policy = policyFor(url);
  const circuit = providerCircuits.get(policy.key);
  if (!circuit) return;
  if (circuit.blockedUntil <= Date.now()) {
    providerCircuits.delete(policy.key);
    return;
  }
  const error = new Error("FinMind requests are paused after an authentication or rate-limit response");
  error.code = FINMIND_CIRCUIT_CODE;
  // Treat a local open circuit as rate-limited so persistent workers use their
  // existing long backoff instead of immediately trying every queued symbol.
  error.status = 429;
  error.providerStatus = circuit.providerStatus;
  error.retryAfter = Math.max(1, Math.ceil((circuit.blockedUntil - Date.now()) / 1_000));
  throw error;
}

function isoDate(value) {
  const raw = clean(value).replaceAll("/", "").replaceAll("-", "");
  if (/^\d{8}$/.test(raw)) {
    return `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`;
  }
  if (/^\d{7}$/.test(raw)) {
    return `${Number(raw.slice(0, 3)) + 1911}-${raw.slice(3, 5)}-${raw.slice(5, 7)}`;
  }
  return clean(value).slice(0, 10);
}

function taipeiToday() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Taipei",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function addDays(value, days) {
  const date = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return value;
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function monthsAgo(months) {
  const date = new Date(`${taipeiToday()}T00:00:00Z`);
  date.setUTCMonth(date.getUTCMonth() - months);
  return date.toISOString().slice(0, 10);
}

function policyFor(url) {
  return policies.find((item) => url.includes(item.match)) || {
    key: "other",
    gap: 600,
    concurrency: 2,
  };
}

function queueFor(policy) {
  if (!queues.has(policy.key)) {
    queues.set(policy.key, {
      policy,
      active: 0,
      lastStarted: 0,
      jobs: [],
      pumping: false,
    });
  }
  return queues.get(policy.key);
}

const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

function pump(state) {
  if (state.pumping) return;
  state.pumping = true;
  void (async () => {
    while (state.active < state.policy.concurrency && state.jobs.length) {
      const delay = Math.max(0, state.lastStarted + state.policy.gap - Date.now());
      if (delay) await wait(delay);
      const job = state.jobs.shift();
      state.active += 1;
      state.lastStarted = Date.now();
      Promise.resolve()
        .then(job.task)
        .then(job.resolve, job.reject)
        .finally(() => {
          state.active -= 1;
          pump(state);
        });
    }
    state.pumping = false;
    if (state.jobs.length && state.active < state.policy.concurrency) pump(state);
  })();
}

function scheduled(url, task) {
  const state = queueFor(policyFor(url));
  return new Promise((resolve, reject) => {
    state.jobs.push({ task, resolve, reject });
    pump(state);
  });
}

async function request(url, {
  format = "json",
  timeout = 35_000,
  retries = 2,
  finmindToken = "",
} = {}) {
  return scheduled(url, async () => {
    let lastError;
    for (let attempt = 0; attempt <= retries; attempt += 1) {
      assertProviderAvailable(url);
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeout);
      try {
        const headers = {
          accept: format === "json" ? "application/json" : "text/csv,text/plain,*/*",
          "user-agent": "TaiwanStockSmartPicker/16.3",
        };
        const token = configuredFinmindToken(finmindToken);
        if (token && url.includes("api.finmindtrade.com")) {
          headers.authorization = `Bearer ${token}`;
        }
        const response = await fetch(url, { headers, signal: controller.signal });
        if (!response.ok) {
          const error = new Error(`上游 API HTTP ${response.status}`);
          error.status = response.status;
          error.retryAfter = number(response.headers.get("retry-after"));
          throw error;
        }
        return format === "json" ? await response.json() : await response.text();
      } catch (error) {
        lastError = error;
        tripProviderCircuit(url, error);
        const retryable =
          error?.name === "AbortError" ||
          error?.status === 408 ||
          error?.status === 429 ||
          error?.status >= 500;
        if (!retryable || attempt === retries) throw error;
        const retryAfter = error?.retryAfter ? error.retryAfter * 1_000 : 0;
        await wait(Math.max(retryAfter, 1_400 * 2 ** attempt));
      } finally {
        clearTimeout(timer);
      }
    }
    throw lastError;
  });
}

async function cached(key, ttl, factory) {
  const existing = memoryCache.get(key);
  if (existing && Date.now() - existing.createdAt < ttl) return existing.value;
  const pending = Promise.resolve().then(factory);
  memoryCache.set(key, { createdAt: Date.now(), value: pending });
  try {
    const value = await pending;
    memoryCache.set(key, { createdAt: Date.now(), value });
    return value;
  } catch (error) {
    memoryCache.delete(key);
    throw error;
  }
}

function objectRows(payload) {
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload?.data)) return payload.data;
  return [];
}

async function finmind(dataset, symbol, startDate, endDate, options = {}) {
  const params = new URLSearchParams({
    dataset,
    data_id: symbol,
    start_date: startDate,
    end_date: endDate,
  });
  const payload = await request(`${FINMIND}?${params}`, {
    // Scheduled jobs deliberately use zero in-request retries.  A failed symbol
    // is retried by a later batch, which keeps the hourly request ceiling exact
    // instead of allowing one transient 5xx to silently exceed it.
    retries: options.retries ?? 2,
    finmindToken: options.finmindToken,
  });
  if (Number(payload?.status) !== 200 || !Array.isArray(payload?.data)) {
    const error = new Error(payload?.msg || `${dataset} 無資料`);
    error.status = Number(payload?.status) || 502;
    tripProviderCircuit(FINMIND, error);
    throw error;
  }
  return payload.data;
}

function normalizePrice(rows) {
  return rows
    .map((row) => ({
      date: isoDate(row.date),
      open: number(row.open),
      high: number(row.max ?? row.high),
      low: number(row.min ?? row.low),
      close: number(row.close),
      volume: finite(row.Trading_Volume ?? row.volume)
        ? Number(row.Trading_Volume ?? row.volume) / 1_000
        : null,
      value: number(row.Trading_money ?? row.value),
      transactions: number(row.Trading_turnover ?? row.transactions),
    }))
    .filter((row) => /^\d{4}-\d{2}-\d{2}$/.test(row.date) && finite(row.close))
    .sort((a, b) => a.date.localeCompare(b.date));
}

function mergeCurrentQuote(rows, quote) {
  const date = isoDate(quote?.trade_date || quote?.priceDate || quote?.date);
  const close = number(quote?.close);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !finite(close)) return rows;
  const current = {
    date,
    open: number(quote?.open) ?? close,
    high: number(quote?.high) ?? close,
    low: number(quote?.low) ?? close,
    close,
    volume: number(quote?.volume),
    value: number(quote?.value),
    transactions: number(quote?.transactions),
  };
  return [...rows.filter((row) => row.date !== date), current]
    .sort((left, right) => left.date.localeCompare(right.date));
}

function sma(values, period, offset = 0) {
  const end = values.length - offset;
  if (end < period) return null;
  return mean(values.slice(end - period, end));
}

function ema(values, period) {
  if (!values.length) return [];
  const multiplier = 2 / (period + 1);
  const output = [values[0]];
  for (let index = 1; index < values.length; index += 1) {
    output.push(values[index] * multiplier + output[index - 1] * (1 - multiplier));
  }
  return output;
}

function rsi(values, period = 14) {
  if (values.length <= period) return null;
  const changes = values.slice(1).map((value, index) => value - values[index]);
  let gain = mean(changes.slice(0, period).map((value) => Math.max(value, 0)));
  let loss = mean(changes.slice(0, period).map((value) => Math.max(-value, 0)));
  for (const change of changes.slice(period)) {
    gain = (gain * (period - 1) + Math.max(change, 0)) / period;
    loss = (loss * (period - 1) + Math.max(-change, 0)) / period;
  }
  if (!loss) return 100;
  return 100 - 100 / (1 + gain / loss);
}

function atr(rows, period = 14) {
  if (rows.length <= period) return null;
  const ranges = rows.slice(1).map((row, index) =>
    Math.max(
      row.high - row.low,
      Math.abs(row.high - rows[index].close),
      Math.abs(row.low - rows[index].close),
    ),
  );
  return mean(ranges.slice(-period));
}

function stochastic(rows, period = 9) {
  if (rows.length < period) return { k: null, d: null };
  let k = 50;
  let d = 50;
  for (let index = period - 1; index < rows.length; index += 1) {
    const window = rows.slice(index - period + 1, index + 1);
    const high = Math.max(...window.map((row) => row.high));
    const low = Math.min(...window.map((row) => row.low));
    const rsv = high === low ? 50 : ((rows[index].close - low) / (high - low)) * 100;
    k = (2 * k + rsv) / 3;
    d = (2 * d + k) / 3;
  }
  return { k: round(k), d: round(d) };
}

function returnAt(closes, days) {
  return closes.length > days && closes.at(-1 - days)
    ? ((closes.at(-1) / closes.at(-1 - days)) - 1) * 100
    : null;
}

function benchmarkReturn(benchmark, lastDate, days) {
  const usable = benchmark.filter((row) => row.date <= lastDate && finite(row.close));
  const values = usable.map((row) => row.close);
  return returnAt(values, days);
}

function priceSummary(rows, benchmark = []) {
  if (rows.length < 20) return { rows: rows.length, sufficient: false };
  const closes = rows.map((row) => row.close);
  const volumes = rows.map((row) => row.volume);
  const ma = Object.fromEntries(
    [5, 10, 20, 60, 120, 240].map((period) => [`ma${period}`, round(sma(closes, period))]),
  );
  const slopes = Object.fromEntries(
    [20, 60, 120].map((period) => {
      const current = sma(closes, period);
      const prior = sma(closes, period, 5);
      return [`ma${period}Slope5`, current && prior ? round((current / prior - 1) * 100) : null];
    }),
  );
  const ema12 = ema(closes, 12);
  const ema26 = ema(closes, 26);
  const macdSeries = closes.map((_, index) => ema12[index] - ema26[index]);
  const signalSeries = ema(macdSeries, 9);
  const atr14 = atr(rows);
  const last = rows.at(-1);
  const high20 = Math.max(...rows.slice(-20).map((row) => row.high));
  const high60 = Math.max(...rows.slice(-60).map((row) => row.high));
  const priorHigh20 = rows.length > 20
    ? Math.max(...rows.slice(-21, -1).map((row) => row.high))
    : null;
  const volume5 = sma(volumes, 5);
  const volume20 = sma(volumes, 20);
  const upVolume = mean(
    rows.slice(-20).filter((row, index, recent) => index && row.close >= recent[index - 1].close).map((row) => row.volume),
  );
  const downVolume = mean(
    rows.slice(-20).filter((row, index, recent) => index && row.close < recent[index - 1].close).map((row) => row.volume),
  );
  const limitUpStreak = (() => {
    let count = 0;
    for (let index = rows.length - 1; index > 0; index -= 1) {
      const change = (rows[index].close / rows[index - 1].close - 1) * 100;
      if (change < 9.4) break;
      count += 1;
    }
    return count;
  })();
  const jumpAnomaly = rows.slice(-40).some((row, index, recent) =>
    index > 0 && Math.abs(row.close / recent[index - 1].close - 1) >= 0.35,
  );
  const { k, d } = stochastic(rows);
  const market20 = benchmarkReturn(benchmark, last.date, 20);
  const market60 = benchmarkReturn(benchmark, last.date, 60);
  const ret20 = returnAt(closes, 20);
  const ret60 = returnAt(closes, 60);
  return {
    rows: rows.length,
    sufficient: rows.length >= 120,
    lastDate: last.date,
    lastClose: last.close,
    ...ma,
    ...slopes,
    return5: round(returnAt(closes, 5)),
    return20: round(ret20),
    return60: round(ret60),
    relative20: finite(ret20) && finite(market20) ? round(ret20 - market20) : null,
    relative60: finite(ret60) && finite(market60) ? round(ret60 - market60) : null,
    marketReturn20: round(market20),
    high20: round(high20),
    high60: round(high60),
    breakout20: finite(priorHigh20) ? last.close >= priorHigh20 : null,
    distanceHigh20: high20 ? round((last.close / high20 - 1) * 100) : null,
    distanceHigh60: high60 ? round((last.close / high60 - 1) * 100) : null,
    distanceMa20: ma.ma20 ? round((last.close / ma.ma20 - 1) * 100) : null,
    distanceMa60: ma.ma60 ? round((last.close / ma.ma60 - 1) * 100) : null,
    volume5: round(volume5),
    volume20: round(volume20),
    volumeRatio: volume5 && volume20 ? round(volume5 / volume20) : null,
    upDownVolumeRatio: upVolume && downVolume ? round(upVolume / downVolume) : null,
    atr14: round(atr14),
    atrPct: atr14 && last.close ? round((atr14 / last.close) * 100) : null,
    rsi14: round(rsi(closes)),
    macd: round(macdSeries.at(-1)),
    macdSignal: round(signalSeries.at(-1)),
    macdHistogram: round(macdSeries.at(-1) - signalSeries.at(-1)),
    kdK: k,
    kdD: d,
    limitUpStreak,
    jumpAnomaly,
  };
}

function revenueAvailability(row) {
  const created = isoDate(row.create_time);
  if (/^\d{4}-\d{2}-\d{2}$/.test(created)) return created;
  const reported = isoDate(row.date);
  return /^\d{4}-\d{2}-\d{2}$/.test(reported)
    ? `${reported.slice(0, 8)}10`
    : "";
}

function normalizeRevenue(rows) {
  const normalized = rows
    .map((row) => ({
      date: isoDate(row.date),
      period: `${row.revenue_year}-${String(row.revenue_month).padStart(2, "0")}`,
      year: number(row.revenue_year),
      month: number(row.revenue_month),
      revenue: number(row.revenue),
      availableAt: revenueAvailability(row),
    }))
    .filter((row) => finite(row.revenue) && row.year && row.month)
    .sort((a, b) => a.period.localeCompare(b.period));
  const byPeriod = new Map(normalized.map((row) => [row.period, row]));
  normalized.forEach((row, index) => {
    const previous = normalized[index - 1];
    const priorYear = byPeriod.get(`${row.year - 1}-${String(row.month).padStart(2, "0")}`);
    row.mom = previous?.revenue ? round((row.revenue / previous.revenue - 1) * 100) : null;
    row.yoy = priorYear?.revenue ? round((row.revenue / priorYear.revenue - 1) * 100) : null;
    row.yoyStatus = priorYear?.revenue === 0
      ? "prior-year-zero"
      : priorYear ? "ready" : "prior-year-unavailable";
  });
  return normalized;
}

function revenueSummary(rows, prices) {
  if (!rows.length) return { months: 0 };
  const latest = rows.at(-1);
  const monthOrdinal = (row) => Number(row.year) * 12 + Number(row.month) - 1;
  let continuousMonths = 1;
  for (let index = rows.length - 1; index > 0; index -= 1) {
    if (monthOrdinal(rows[index]) - monthOrdinal(rows[index - 1]) !== 1) break;
    continuousMonths += 1;
  }
  const continuousRows = rows.slice(-continuousMonths);
  const yoyValues = continuousRows.length >= 3
    ? continuousRows.slice(-3).map((row) => row.yoy)
    : [];
  let consecutiveAcceleration = 0;
  for (let index = continuousRows.length - 1; index > 0; index -= 1) {
    if (!finite(continuousRows[index].yoy) || !finite(continuousRows[index - 1].yoy) || continuousRows[index].yoy <= continuousRows[index - 1].yoy) break;
    consecutiveAcceleration += 1;
  }
  const sameMonthHistory = rows.filter((row) => row.month === latest.month && row.year < latest.year);
  const prior11 = continuousRows.length >= 12 ? continuousRows.slice(-12, -1) : [];
  const currentYear = rows.filter((row) => row.year === latest.year && row.month <= latest.month);
  const previousYear = rows.filter((row) => row.year === latest.year - 1 && row.month <= latest.month);
  const ytd = sum(currentYear.map((row) => row.revenue));
  const priorYtd = sum(previousYear.map((row) => row.revenue));
  const completeYtd = currentYear.length === latest.month && previousYear.length === latest.month;
  const releaseIndex = prices.findIndex((row) => row.date >= latest.availableAt);
  const postRelease5 = releaseIndex >= 0 && prices[releaseIndex + 5]
    ? round((prices[releaseIndex + 5].close / prices[releaseIndex].close - 1) * 100)
    : null;
  const postReleaseStatus = finite(postRelease5)
    ? "ready"
    : releaseIndex >= 0
      ? "pending-five-trading-days"
      : "release-not-in-price-range";
  const postReleaseObservedDays = releaseIndex >= 0
    ? Math.max(0, prices.length - releaseIndex - 1)
    : null;
  const priorSameMean = mean(sameMonthHistory.slice(-3).map((row) => row.revenue));
  return {
    months: rows.length,
    continuousMonths,
    historyStart: rows[0]?.period || null,
    period: latest.period,
    availableAt: latest.availableAt,
    revenue: latest.revenue,
    yoy: latest.yoy,
    yoyStatus: latest.yoyStatus,
    mom: latest.mom,
    ytdYoy: completeYtd && priorYtd ? round((ytd / priorYtd - 1) * 100) : null,
    avg3Yoy: yoyValues.length === 3 && yoyValues.every(finite) ? round(mean(yoyValues)) : null,
    acceleration: continuousRows.length >= 2 && finite(latest.yoy) && finite(continuousRows.at(-2)?.yoy)
      ? round(latest.yoy - continuousRows.at(-2).yoy)
      : null,
    acceleration3: continuousRows.length >= 3 && finite(continuousRows.at(-3)?.yoy) && finite(latest.yoy)
      ? round((latest.yoy - continuousRows.at(-3).yoy) / 2)
      : null,
    consecutiveAcceleration,
    new12MonthHigh: prior11.length ? latest.revenue > Math.max(...prior11.map((row) => row.revenue)) : null,
    sameMonthRecord: sameMonthHistory.length
      ? latest.revenue > Math.max(...sameMonthHistory.map((row) => row.revenue))
      : null,
    seasonalGrowth: priorSameMean ? round((latest.revenue / priorSameMean - 1) * 100) : null,
    postRelease5,
    postReleaseStatus,
    postReleaseObservedDays,
  };
}

function refreshRevenueReaction(summary, prices) {
  if (!summary?.availableAt || finite(summary.postRelease5)) return summary;
  const releaseIndex = prices.findIndex((row) => row.date >= summary.availableAt);
  if (releaseIndex < 0 || !prices[releaseIndex + 5]) return summary;
  return {
    ...summary,
    postRelease5: round((prices[releaseIndex + 5].close / prices[releaseIndex].close - 1) * 100),
    postReleaseStatus: "ready",
    postReleaseObservedDays: Math.max(5, prices.length - releaseIndex - 1),
  };
}

function pivot(rows) {
  const map = new Map();
  rows.forEach((row) => {
    const date = isoDate(row.date);
    if (!map.has(date)) map.set(date, { date, values: {}, origins: {} });
    const current = map.get(date);
    const type = clean(row.type);
    current.values[type] = number(row.value);
    // FinMind commonly emits an amount followed by a matching `_per` ratio
    // with the same Chinese origin name.  Letting the ratio overwrite the
    // amount turned receivables/inventory into values such as 19 or 31.
    if (!/_per$/i.test(type)) current.origins[clean(row.origin_name)] = number(row.value);
  });
  return [...map.values()].sort((a, b) => a.date.localeCompare(b.date));
}

function statementValue(period, types, originPattern) {
  for (const type of types) {
    if (finite(period?.values?.[type])) return period.values[type];
  }
  if (originPattern) {
    const found = Object.entries(period?.origins || {}).find(([name, value]) =>
      originPattern.test(name) && finite(value),
    );
    if (found) return found[1];
  }
  return null;
}

function receivablesValue(period) {
  const combined = statementValue(
    period,
    ["NotesAndAccountsReceivableNet", "NotesAndAccountsReceivable"],
    /應收票據及帳款.*淨額|應收票據及帳款合計/,
  );
  if (finite(combined)) return combined;
  const components = [
    "AccountsReceivableNet",
    "AccountsReceivable",
    "BillsReceivableNet",
    "NotesReceivableNet",
  ].map((type) => period?.values?.[type]).filter(finite);
  if (components.length) return sum(components);
  return statementValue(period, [], /應收帳款.*淨額|應收票據.*淨額/);
}

function financialRevenueValue(period) {
  const companyRevenue = statementValue(period, ["Revenue"], /營業收入|收益合計/);
  if (finite(companyRevenue)) return { value: companyRevenue, status: "available", basis: "revenue" };
  const financeIncome = statementValue(period, ["Income"], /^收益$/);
  if (finite(financeIncome)) return { value: financeIncome, status: "available", basis: "finance-income" };
  const netInterest = statementValue(period, ["NetInterestIncome"], /利息淨收益|淨利息收入/);
  const netNonInterest = statementValue(period, ["NetNonInterestIncome"], /非利息淨收益|淨非利息收入/);
  if (finite(netInterest) || finite(netNonInterest)) {
    return {
      value: sum([netInterest, netNonInterest]),
      status: "available",
      basis: "bank-net-income-components",
    };
  }
  const insuranceResult = Object.keys(period?.origins || {}).some((name) =>
    /保險服務結果|保險財務結果|其他營業結果/.test(name));
  return insuranceResult
    ? { value: null, status: "source-not-comparable", basis: "insurance-results" }
    : { value: null, status: "source-not-returned", basis: null };
}

function quarterFromDate(date) {
  const month = Number(date.slice(5, 7));
  return Math.ceil(month / 3);
}

function standalone(periods, getter) {
  return periods.map((period, index) => {
    const current = getter(period);
    const previous = periods[index - 1];
    if (!finite(current)) return null;
    if (previous && previous.date.slice(0, 4) === period.date.slice(0, 4)) {
      const prior = getter(previous);
      return finite(prior) ? current - prior : current;
    }
    return current;
  });
}

function financialSummary(incomeRows, balanceRows, cashRows) {
  const incomes = pivot(incomeRows);
  const balances = pivot(balanceRows);
  const cash = pivot(cashRows);
  // FinMind's income-statement rows are already single-quarter values.  Cash
  // flow rows are year-to-date values, so only cash flow needs differencing.
  // Applying `standalone` to both made Q2-Q4 margins/EPS and cash conversion
  // incorrect, especially for smaller TPEx companies.
  const incomeSeries = (getter) => incomes.map((row) => getter(row));
  const revenueDetails = incomeSeries(financialRevenueValue);
  const revenueValues = revenueDetails.map((row) => row.value);
  const grossValues = incomeSeries((row) => statementValue(row, ["GrossProfit"], /營業毛利/));
  const operatingValues = incomeSeries((row) => statementValue(row, ["OperatingIncome"], /營業利益/));
  const netValues = incomeSeries((row) => statementValue(row, ["IncomeAfterTaxes", "ProfitLoss"], /本期淨利|本期稅後/));
  const epsValues = incomeSeries((row) => statementValue(row, ["EPS"], /每股盈餘/));
  const nonOperatingValues = incomeSeries((row) => statementValue(row, ["TotalNonoperatingIncomeAndExpense"], /營業外收入及支出/));
  const interestValues = incomeSeries((row) => statementValue(row, ["FinanceCosts", "InterestExpense"], /財務成本|利息費用/));
  const ocfValues = standalone(cash, (row) => statementValue(row, ["CashProvidedByOperatingActivities"], /營業活動.*淨現金/));
  const capexValues = standalone(cash, (row) => statementValue(row, ["PropertyAndPlantAndEquipment"], /取得不動產、廠房及設備/));
  const balanceMap = new Map(balances.map((row) => [row.date, row]));
  const cashByDate = new Map(cash.map((row, index) => [row.date, { ocf: ocfValues[index], capex: capexValues[index] }]));
  const quarters = incomes.slice(-12).map((income, originalIndex, selected) => {
    const globalIndex = incomes.indexOf(income);
    const balance = balanceMap.get(income.date) || balances.filter((row) => row.date <= income.date).at(-1);
    const cashflow = cashByDate.get(income.date) || {};
    const revenue = revenueValues[globalIndex];
    const grossProfit = grossValues[globalIndex];
    const operatingIncome = operatingValues[globalIndex];
    const netIncome = netValues[globalIndex];
    const equity = statementValue(balance, ["Equity", "EquityAttributableToOwnersOfParent"], /權益總額|權益總計/);
    const assets = statementValue(balance, ["TotalAssets", "Assets"], /資產總額|資產總計/);
    const liabilities = statementValue(balance, ["TotalLiabilities", "Liabilities"], /負債總額|負債總計/);
    const currentAssets = statementValue(balance, ["CurrentAssets"], /^流動資產/);
    const currentLiabilities = statementValue(balance, ["CurrentLiabilities"], /^流動負債/);
    const inventory = statementValue(balance, ["Inventories", "Inventory"], /存貨/);
    const receivables = receivablesValue(balance);
    const interest = interestValues[globalIndex];
    return {
      date: income.date,
      period: `${income.date.slice(0, 4)} Q${quarterFromDate(income.date)}`,
      availableAt: addDays(income.date, quarterFromDate(income.date) === 4 ? 90 : 45),
      revenue: round(revenue, 0),
      revenueStatus: revenueDetails[globalIndex]?.status || "source-not-returned",
      revenueBasis: revenueDetails[globalIndex]?.basis || null,
      netIncome: round(netIncome, 0),
      eps: round(epsValues[globalIndex]),
      grossMargin: revenue ? round((grossProfit / revenue) * 100) : null,
      operatingMargin: revenue ? round((operatingIncome / revenue) * 100) : null,
      netMargin: revenue ? round((netIncome / revenue) * 100) : null,
      roe: equity ? round((netIncome / equity) * 400) : null,
      operatingCashFlow: round(cashflow.ocf, 0),
      freeCashFlow: finite(cashflow.ocf) && finite(cashflow.capex)
        ? round(cashflow.ocf + cashflow.capex, 0)
        : null,
      cashConversion: finite(netIncome) && netIncome > 0 && finite(cashflow.ocf)
        ? round(cashflow.ocf / netIncome)
        : null,
      inventory: round(inventory, 0),
      receivables: round(receivables, 0),
      debtRatio: assets ? round((liabilities / assets) * 100) : null,
      currentRatio: currentLiabilities ? round((currentAssets / currentLiabilities) * 100) : null,
      interestCoverage: interest ? round(operatingIncome / Math.abs(interest)) : null,
      nonOperatingRatio: operatingIncome && finite(nonOperatingValues[globalIndex])
        ? round((nonOperatingValues[globalIndex] / Math.abs(operatingIncome)) * 100)
        : null,
    };
  });
  const latest = quarters.at(-1) || {};
  const quarterOrdinal = (quarter) => Number(quarter?.date?.slice(0, 4)) * 4 + quarterFromDate(quarter?.date || "0000-00-00") - 1;
  const latestOrdinal = quarterOrdinal(latest);
  const yearAgo = quarters.find((quarter) => quarterOrdinal(quarter) === latestOrdinal - 4) || {};
  let continuousQuarters = quarters.length ? 1 : 0;
  for (let index = quarters.length - 1; index > 0; index -= 1) {
    if (quarterOrdinal(quarters[index]) - quarterOrdinal(quarters[index - 1]) !== 1) break;
    continuousQuarters += 1;
  }
  const trailing = continuousQuarters >= 4 ? quarters.slice(-4) : [];
  const completeTtm = trailing.length === 4 && trailing.every((quarter) =>
    finite(quarter.netIncome) && finite(quarter.operatingCashFlow),
  );
  const ttmNetIncome = completeTtm ? sum(trailing.map((quarter) => quarter.netIncome)) : null;
  const ttmOperatingCashFlow = completeTtm
    ? sum(trailing.map((quarter) => quarter.operatingCashFlow))
    : null;
  const completeTtmFcf = trailing.length === 4 && trailing.every((quarter) => finite(quarter.freeCashFlow));
  const ttmFreeCashFlow = completeTtmFcf
    ? sum(trailing.map((quarter) => quarter.freeCashFlow))
    : null;
  const ttmCashConversion = completeTtm && ttmNetIncome > 0
    ? round(ttmOperatingCashFlow / ttmNetIncome)
    : null;
  const cashConversion = completeTtm
    ? ttmCashConversion
    : latest.cashConversion ?? null;
  const cashConversionBasis = completeTtm
    ? ttmNetIncome > 0 ? "TTM" : "TTM-nonpositive-net-income"
    : finite(latest.cashConversion) ? "latest-quarter" : "insufficient-positive-income";
  const growth = (current, previous) => finite(current) && finite(previous) && Number(previous) !== 0
    ? round((Number(current) / Math.abs(Number(previous)) - 1) * 100)
    : null;
  return {
    quarters: quarters.length,
    continuousQuarters,
    sourceCoverage: {
      incomeRows: incomeRows.length,
      balanceRows: balanceRows.length,
      cashflowRows: cashRows.length,
    },
    period: latest.period || "",
    availableAt: latest.availableAt || "",
    revenue: latest.revenue ?? null,
    revenueStatus: latest.revenueStatus || "source-not-returned",
    revenueBasis: latest.revenueBasis || null,
    eps: latest.eps ?? null,
    epsYoy: growth(latest.eps, yearAgo.eps),
    revenueYoy: growth(latest.revenue, yearAgo.revenue),
    grossMargin: latest.grossMargin ?? null,
    grossMarginYoyChange: finite(latest.grossMargin) && finite(yearAgo.grossMargin)
      ? round(latest.grossMargin - yearAgo.grossMargin)
      : null,
    operatingMargin: latest.operatingMargin ?? null,
    operatingMarginYoyChange: finite(latest.operatingMargin) && finite(yearAgo.operatingMargin)
      ? round(latest.operatingMargin - yearAgo.operatingMargin)
      : null,
    netMargin: latest.netMargin ?? null,
    roe: latest.roe ?? null,
    // Scoring uses trailing-four-quarter cash quality to avoid treating one
    // working-capital swing as the company's normal cash conversion.
    operatingCashFlow: ttmOperatingCashFlow ?? latest.operatingCashFlow ?? null,
    freeCashFlow: ttmFreeCashFlow ?? latest.freeCashFlow ?? null,
    cashConversion,
    cashConversionBasis,
    ttmNetIncome,
    ttmOperatingCashFlow,
    ttmFreeCashFlow,
    latestQuarterOperatingCashFlow: latest.operatingCashFlow ?? null,
    latestQuarterFreeCashFlow: latest.freeCashFlow ?? null,
    latestQuarterCashConversion: latest.cashConversion ?? null,
    inventoryYoy: growth(latest.inventory, yearAgo.inventory),
    receivablesYoy: growth(latest.receivables, yearAgo.receivables),
    debtRatio: latest.debtRatio ?? null,
    currentRatio: latest.currentRatio ?? null,
    interestCoverage: latest.interestCoverage ?? null,
    nonOperatingRatio: latest.nonOperatingRatio ?? null,
    history: quarters,
  };
}

function institutionalSummary(rows, prices) {
  const dates = new Map();
  rows.forEach((row) => {
    const date = isoDate(row.date);
    if (!dates.has(date)) dates.set(date, { date, foreign: 0, trust: 0, dealer: 0 });
    const target = dates.get(date);
    const net = (number(row.buy) || 0) - (number(row.sell) || 0);
    const name = clean(row.name).toLowerCase();
    if (name.includes("foreign_investor")) target.foreign += net;
    else if (name.includes("investment_trust")) target.trust += net;
    else if (name.includes("dealer")) target.dealer += net;
  });
  const daily = [...dates.values()].sort((a, b) => a.date.localeCompare(b.date)).map((row) => {
    const price = prices.find((item) => item.date === row.date);
    const inst = row.foreign + row.trust + row.dealer;
    return {
      ...row,
      foreign: round(row.foreign / 1_000),
      trust: round(row.trust / 1_000),
      dealer: round(row.dealer / 1_000),
      inst: round(inst / 1_000),
      intensity: price?.volume ? round((inst / 1_000 / price.volume) * 100) : null,
    };
  });
  const cumulative = (key, period) => round(sum(daily.slice(-period).map((row) => row[key])));
  const streak = (key) => {
    let count = 0;
    for (let index = daily.length - 1; index >= 0; index -= 1) {
      if (daily[index][key] <= 0) break;
      count += 1;
    }
    return count;
  };
  return {
    days: daily.length,
    date: daily.at(-1)?.date || "",
    foreign5: cumulative("foreign", 5),
    foreign10: cumulative("foreign", 10),
    foreign20: cumulative("foreign", 20),
    trust5: cumulative("trust", 5),
    trust10: cumulative("trust", 10),
    trust20: cumulative("trust", 20),
    dealer5: cumulative("dealer", 5),
    inst5: cumulative("inst", 5),
    inst10: cumulative("inst", 10),
    inst20: cumulative("inst", 20),
    foreignStreak: streak("foreign"),
    trustStreak: streak("trust"),
    instStreak: streak("inst"),
    intensity5: round(mean(daily.slice(-5).map((row) => row.intensity))),
    history: daily.slice(-30),
  };
}

function marginSummary(rows) {
  const daily = rows
    .map((row) => ({
      date: isoDate(row.date),
      marginBalance: number(row.MarginPurchaseTodayBalance),
      marginLimit: number(row.MarginPurchaseLimit),
      shortBalance: number(row.ShortSaleTodayBalance),
      note: clean(row.Note),
    }))
    .filter((row) => finite(row.marginBalance))
    .sort((a, b) => a.date.localeCompare(b.date));
  const change = (key, period) => daily.length > period && finite(daily.at(-1)?.[key]) && finite(daily.at(-1 - period)?.[key])
    ? round(daily.at(-1)[key] - daily.at(-1 - period)[key])
    : null;
  const latest = daily.at(-1) || {};
  return {
    days: daily.length,
    date: latest.date || "",
    marginBalance: latest.marginBalance ?? null,
    marginLimit: latest.marginLimit ?? null,
    marginChange5: change("marginBalance", 5),
    marginChange20: change("marginBalance", 20),
    marginUsage: latest.marginLimit ? round((latest.marginBalance / latest.marginLimit) * 100) : null,
    financingEligible: finite(latest.marginLimit) ? Number(latest.marginLimit) > 0 : null,
    note: latest.note || "",
    shortBalance: latest.shortBalance ?? null,
    shortChange5: change("shortBalance", 5),
    shortChange20: change("shortBalance", 20),
    history: daily.slice(-30),
  };
}

function lendingSummary(rows) {
  if (!rows.length) return { rows: 0 };
  const numericKeys = Object.keys(rows[0]).filter((key) => /volume|balance|quantity|shares/i.test(key));
  const normalized = rows.map((row) => ({
    date: isoDate(row.date),
    value: sum(numericKeys.map((key) => number(row[key]))),
  })).sort((a, b) => a.date.localeCompare(b.date));
  return {
    rows: rows.length,
    date: normalized.at(-1)?.date || "",
    latest: round(normalized.at(-1)?.value),
    total20: round(sum(normalized.slice(-20).map((row) => row.value))),
  };
}

function parseCsvLine(line) {
  const result = [];
  let field = "";
  let quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const character = line[index];
    if (character === '"' && line[index + 1] === '"' && quoted) {
      field += '"';
      index += 1;
    } else if (character === '"') quoted = !quoted;
    else if (character === "," && !quoted) {
      result.push(field);
      field = "";
    } else field += character;
  }
  result.push(field);
  return result;
}

async function streamTdccGroups(timeout, retries) {
  return scheduled(TDCC_HOLDINGS, async () => {
    let lastError;
    for (let attempt = 0; attempt <= retries; attempt += 1) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeout);
      try {
        const response = await fetch(TDCC_HOLDINGS, {
          headers: {
            accept: "text/csv,text/plain,*/*",
            "user-agent": "TaiwanStockSmartPicker/16.3",
          },
          signal: controller.signal,
        });
        if (!response.ok) {
          const error = new Error(`上游 API HTTP ${response.status}`);
          error.status = response.status;
          throw error;
        }
        if (!response.body) throw new Error("TDCC 回應沒有資料串流");
        const groups = new Map();
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let headerSkipped = false;
        const consume = (rawLine) => {
          const line = rawLine.replace(/\r$/, "").replace(/^\uFEFF/, "");
          if (!line) return;
          if (!headerSkipped) {
            headerSkipped = true;
            return;
          }
          const [date, symbol, level, people, shares, ratio] = parseCsvLine(line);
          const normalizedSymbol = clean(symbol);
          const normalizedLevel = clean(level);
          if (!/^\d{4,6}$/.test(normalizedSymbol)) return;
          if (!groups.has(normalizedSymbol)) groups.set(normalizedSymbol, { date: isoDate(date), levels: {} });
          groups.get(normalizedSymbol).levels[normalizedLevel] = {
            people: number(people),
            shares: number(shares),
            ratio: number(ratio),
          };
        };
        while (true) {
          const { done, value } = await reader.read();
          buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
          let newline;
          while ((newline = buffer.indexOf("\n")) >= 0) {
            consume(buffer.slice(0, newline));
            buffer = buffer.slice(newline + 1);
          }
          if (done) break;
        }
        consume(buffer);
        return groups;
      } catch (error) {
        lastError = error;
        const retryable = error?.name === "AbortError" || error?.status === 408 || error?.status === 429 || error?.status >= 500;
        if (!retryable || attempt === retries) throw error;
        await wait(1_400 * 2 ** attempt);
      } finally {
        clearTimeout(timer);
      }
    }
    throw lastError;
  });
}

export async function buildTdccSnapshot(options = {}) {
  const timeout = Math.max(5_000, Number(options.timeout) || 60_000);
  const retries = Math.max(0, Number.isFinite(Number(options.retries)) ? Number(options.retries) : 1);
  return cached(`tdcc-current:${timeout}:${retries}`, 12 * 60 * 60 * 1_000, async () => {
    // Stream the weekly file line by line.  Materialising the whole CSV and a
    // second array of lines exceeded the Edge worker memory limit and could
    // stop every other market source from being persisted.
    const groups = await streamTdccGroups(timeout, retries);
    const bySymbol = {};
    groups.forEach((item, symbol) => {
      const total = item.levels["17"]?.shares;
      const largeShares = sum(["12", "13", "14", "15"].map((level) => item.levels[level]?.shares));
      const retailShares = sum(["1", "2", "3"].map((level) => item.levels[level]?.shares));
      bySymbol[symbol] = {
        date: item.date,
        large400Ratio: total ? round((largeShares / total) * 100) : null,
        retail10Ratio: total ? round((retailShares / total) * 100) : null,
        holders: sum(Object.entries(item.levels).filter(([level]) => level !== "17").map(([, value]) => value.people)),
      };
    });
    return { date: Object.values(bySymbol)[0]?.date || "", bySymbol };
  });
}

function activeDisposition(row) {
  const period = clean(row.DispositionPeriod ?? row["處置起迄時間"]);
  const matches = [...period.matchAll(/(\d{2,4})[/.年-](\d{1,2})[/.月-](\d{1,2})/g)];
  if (!matches.length) return true;
  const dates = matches.map((match) => {
    const year = Number(match[1]) < 1911 ? Number(match[1]) + 1911 : Number(match[1]);
    return `${year}-${String(match[2]).padStart(2, "0")}-${String(match[3]).padStart(2, "0")}`;
  });
  return dates.at(-1) >= taipeiToday();
}

function truthyFlag(value) {
  const normalized = clean(value).toLowerCase();
  return Boolean(normalized && !["-", "--", "否", "無", "n", "no", "0"].includes(normalized));
}

function currentlySuspended(row) {
  const haltRaw = row.TradingHaltDate ?? row["暫停交易"];
  const resumeRaw = row.TradingResumptionDate ?? row["恢復交易"];
  if (!truthyFlag(haltRaw)) return false;
  if (!truthyFlag(resumeRaw)) return true;
  const resumed = isoDate(resumeRaw);
  // A completed resumption must not remain permanently hard-excluded merely
  // because it is still present in the announcement feed.
  if (!/^\d{4}-\d{2}-\d{2}$/.test(resumed)) return false;
  return resumed > taipeiToday();
}

export async function buildRiskSnapshot() {
  return cached("risk-current", 10 * 60 * 1_000, async () => {
    const endpoints = [
      ["twseDisposition", `${TWSE_OPEN}/announcement/punish`],
      ["twseAttention", `${TWSE_OPEN}/announcement/notice`],
      ["twseAltered", `${TWSE_OPEN}/exchangeReport/TWT85U`],
      ["twseSuspended", `${TWSE_OPEN}/exchangeReport/TWTAWU`],
      ["otcDisposition", `${TPEX_OPEN}/tpex_disposal_information`],
      ["otcAttention", `${TPEX_OPEN}/tpex_trading_warning_information`],
      ["otcAltered", `${TPEX_OPEN}/tpex_cmode`],
      ["otcSuspended", `${TPEX_OPEN}/tpex_spendi_today`],
    ];
    const settled = await Promise.allSettled(endpoints.map(([, url]) => request(url)));
    const payloads = Object.fromEntries(endpoints.map(([key], index) => [key, settled[index].status === "fulfilled" ? objectRows(settled[index].value) : []]));
    const bySymbol = {};
    const touch = (symbol) => {
      if (!bySymbol[symbol]) bySymbol[symbol] = { hardExcluded: false, flags: [], details: [] };
      return bySymbol[symbol];
    };
    const symbolOf = (row) => clean(row.Code ?? row.SecuritiesCompanyCode ?? row["證券代號"]);
    [...payloads.twseDisposition, ...payloads.otcDisposition].forEach((row) => {
      const symbol = symbolOf(row);
      if (!symbol || !activeDisposition(row)) return;
      const target = touch(symbol);
      target.hardExcluded = true;
      target.disposition = true;
      target.flags.push("處置股票");
      target.details.push(clean(row.DispositionMeasures ?? row.DisposalCondition ?? row.DispositionReasons));
    });
    [...payloads.twseAttention, ...payloads.otcAttention].forEach((row) => {
      const symbol = symbolOf(row);
      if (!symbol) return;
      const target = touch(symbol);
      target.attention = true;
      target.flags.push("注意股票");
      target.details.push(clean(row.TradingInfoForAttention ?? row.TradingInformation));
    });
    payloads.twseAltered.forEach((row) => {
      const symbol = symbolOf(row);
      if (!symbol) return;
      const target = touch(symbol);
      target.hardExcluded = true;
      target.altered = true;
      target.periodic = truthyFlag(row.PeriodicCallAuctionTrading);
      target.flags.push(target.periodic ? "變更交易／分盤" : "變更交易");
    });
    payloads.otcAltered.forEach((row) => {
      const symbol = symbolOf(row);
      if (!symbol) return;
      const flags = [
        ["AlteredTrading", "變更交易"],
        ["PeriodicTrading", "分盤交易"],
        ["ManagedStock", "管理股票"],
        ["SuspensionOfTrading", "停止交易"],
      ].filter(([key]) => truthyFlag(row[key])).map(([, label]) => label);
      if (!flags.length) return;
      const target = touch(symbol);
      target.hardExcluded = true;
      target.altered = flags.includes("變更交易");
      target.periodic = flags.includes("分盤交易");
      target.suspended = flags.includes("停止交易");
      target.flags.push(...flags);
    });
    [...payloads.twseSuspended, ...payloads.otcSuspended].forEach((row) => {
      const symbol = symbolOf(row);
      if (!symbol || !currentlySuspended(row)) return;
      const target = touch(symbol);
      target.hardExcluded = true;
      target.suspended = true;
      target.flags.push("停止／暫停交易");
    });
    Object.values(bySymbol).forEach((item) => {
      item.flags = [...new Set(item.flags)];
      item.details = [...new Set(item.details.filter(Boolean))].slice(0, 4);
    });
    return {
      bySymbol,
      coverage: Object.fromEntries(endpoints.map(([key], index) => [key, settled[index].status === "fulfilled"])),
      fetchedAt: new Date().toISOString(),
    };
  });
}

function normalizeBenchmark(rows, fields) {
  return rows.map((row) => ({
    date: isoDate(row.Date ?? row.date),
    close: number(row[fields.close] ?? row.Close ?? row.ClosingIndex ?? row.price),
  })).filter((row) => /^\d{4}-\d{2}-\d{2}$/.test(row.date) && finite(row.close))
    .sort((a, b) => a.date.localeCompare(b.date));
}

function latestIndexSnapshot(rows, { code, name, source, closeField = "close", changeField = "" }) {
  const normalized = objectRows(rows).map((row) => ({
    date: isoDate(row.Date ?? row.date),
    close: number(row[closeField] ?? row.Close ?? row.ClosingIndex ?? row.close),
    change: changeField ? number(row[changeField]) : null,
  })).filter((row) => /^\d{4}-\d{2}-\d{2}$/.test(row.date) && finite(row.close))
    .sort((left, right) => left.date.localeCompare(right.date));
  const latest = normalized.at(-1);
  if (!latest) return null;
  const previous = normalized.at(-2);
  const change = finite(latest.change)
    ? Number(latest.change)
    : previous && finite(previous.close) ? Number(latest.close) - Number(previous.close) : null;
  const previousClose = finite(change) ? Number(latest.close) - Number(change) : previous?.close;
  return {
    code,
    name,
    dataDate: latest.date,
    value: round(latest.close, 2),
    change: round(change, 2),
    changePercent: finite(change) && finite(previousClose) && Number(previousClose) !== 0
      ? round(Number(change) / Number(previousClose) * 100, 2)
      : null,
    source,
  };
}

function selectTaifexTx(rows) {
  const normalized = objectRows(rows).filter((row) => {
    const contractMonth = clean(row["ContractMonth(Week)"]);
    return clean(row.Contract) === "TX" && /^\d{6}$/.test(contractMonth) &&
      finite(number(row.Last)) && finite(number(row.Volume)) &&
      finite(number(row.SettlementPrice)) && finite(number(row.OpenInterest));
  });
  if (!normalized.length) return null;
  const latestDate = normalized.map((row) => isoDate(row.Date)).filter(Boolean).sort().at(-1);
  const latest = normalized.filter((row) => isoDate(row.Date) === latestDate)
    .sort((left, right) => (number(right.Volume) || 0) - (number(left.Volume) || 0))[0];
  if (!latest) return null;
  return {
    code: "tx",
    name: "台指期",
    dataDate: latestDate,
    value: round(number(latest.Last), 2),
    change: round(number(latest.Change), 2),
    changePercent: round(number(latest["%"]), 2),
    contractMonth: clean(latest["ContractMonth(Week)"]),
    session: "regular",
    volume: number(latest.Volume),
    settlementPrice: number(latest.SettlementPrice),
    openInterest: number(latest.OpenInterest),
    source: "TAIFEX OpenAPI",
  };
}

export async function buildBenchmarks(options = {}) {
  const finmindRetries = options.finmindRetries ?? 2;
  const allowFinmind = options.allowFinmind !== false;
  const officialRetries = Math.max(0, Number.isFinite(Number(options.officialRetries)) ? Number(options.officialRetries) : 2);
  const officialTimeout = Math.max(5_000, Number(options.officialTimeout) || 35_000);
  return cached(`benchmarks:${finmindRetries}:${officialRetries}:${officialTimeout}:${allowFinmind ? "fallback" : "official-only"}`, 6 * 60 * 60 * 1_000, async () => {
    const settled = await Promise.allSettled([
      request(`${TWSE_OPEN}/indicesReport/MI_5MINS_HIST`, { timeout: officialTimeout, retries: officialRetries }),
      request(`${TPEX_OPEN}/tpex_index`, { timeout: officialTimeout, retries: officialRetries }),
      request(`${TAIFEX_OPEN}/DailyMarketReportFut`, { timeout: officialTimeout, retries: officialRetries }),
    ]);
    let listed = settled[0].status === "fulfilled"
      ? normalizeBenchmark(objectRows(settled[0].value), { close: "ClosingIndex" })
      : [];
    let otc = settled[1].status === "fulfilled"
      ? normalizeBenchmark(objectRows(settled[1].value), { close: "Close" })
      : [];
    const source = { listed: "TWSE OpenAPI", otc: "TPEx OpenAPI" };
    const marketIndices = [
      settled[0].status === "fulfilled" ? latestIndexSnapshot(settled[0].value, {
        code: "taiex", name: "加權指數", source: "TWSE OpenAPI", closeField: "ClosingIndex",
      }) : null,
      settled[1].status === "fulfilled" ? latestIndexSnapshot(settled[1].value, {
        code: "tpex", name: "櫃買指數", source: "TPEx OpenAPI", closeField: "Close", changeField: "Change",
      }) : null,
      settled[2].status === "fulfilled" ? selectTaifexTx(settled[2].value) : null,
    ].filter(Boolean);
    // The official OpenAPI index feeds may only expose the current month.  Do
    // not pretend 7–10 observations are a 20/60-day benchmark; use FinMind's
    // documented total-return-index history as the bounded fallback.
    if (allowFinmind && (listed.length < 65 || otc.length < 65)) {
      const endDate = taipeiToday();
      const startDate = monthsAgo(8);
      const historical = await Promise.allSettled([
        listed.length < 65 ? finmind("TaiwanStockTotalReturnIndex", "TAIEX", startDate, endDate, { retries: finmindRetries, finmindToken: options.finmindToken }) : Promise.resolve([]),
        otc.length < 65 ? finmind("TaiwanStockTotalReturnIndex", "TPEx", startDate, endDate, { retries: finmindRetries, finmindToken: options.finmindToken }) : Promise.resolve([]),
      ]);
      const listedHistory = historical[0].status === "fulfilled"
        ? normalizeBenchmark(historical[0].value, { close: "price" })
        : [];
      const otcHistory = historical[1].status === "fulfilled"
        ? normalizeBenchmark(historical[1].value, { close: "price" })
        : [];
      if (listedHistory.length >= 65) {
        listed = listedHistory;
        source.listed = "FinMind TaiwanStockTotalReturnIndex (TAIEX)";
      }
      if (otcHistory.length >= 65) {
        otc = otcHistory;
        source.otc = "FinMind TaiwanStockTotalReturnIndex (TPEx)";
      }
    }
    return {
      listed,
      otc,
      marketIndices,
      source,
      coverage: {
        listed: listed.length >= 65,
        otc: otc.length >= 65,
        taiex: marketIndices.some((item) => item.code === "taiex"),
        tpex: marketIndices.some((item) => item.code === "tpex"),
        tx: marketIndices.some((item) => item.code === "tx"),
      },
    };
  });
}

export async function buildEtfProfiles() {
  return cached("etf-profiles", 12 * 60 * 60 * 1_000, async () => {
    const settled = await Promise.allSettled([
      request(`${TWSE_OPEN}/opendata/t187ap47_L`),
      request("https://mis.twse.com.tw/stock/data/all_etf.txt"),
    ]);
    const rows = settled[0].status === "fulfilled" ? objectRows(settled[0].value) : [];
    const bySymbol = {};
    rows.forEach((row) => {
      const symbol = clean(row["基金代號"]);
      if (!symbol) return;
      const name = clean(row["基金簡稱"] ?? row["基金中文名稱"]);
      const type = clean(row["基金類型"]);
      const note = clean(row["備註"]);
      const benchmark = clean(row["標的指數/追蹤指數名稱"]);
      const direction = etfDirectionFlags({ name, type, note, benchmark });
      bySymbol[symbol] = {
        publishedAt: isoDate(row["出表日期"]),
        fundType: type,
        benchmark,
        foreignExposure: truthyFlag(row["是否包含國外成分股"]),
        units: number(row["發行單位數/轉換數"]),
        inceptionDate: isoDate(row["成立日期"]),
        listingDate: isoDate(row["上市日期"]),
        leveraged: direction.leveraged,
        inverse: direction.inverse,
        bond: /債券|債/i.test(`${type} ${name}`),
      };
    });
    const findEtfRows = (value, depth = 0) => {
      if (depth > 4 || value == null) return [];
      if (Array.isArray(value)) {
        const direct = value.filter((row) => row && typeof row === "object" && ETF_SYMBOL.test(clean(row.a)));
        return direct.length ? direct : value.flatMap((item) => findEtfRows(item, depth + 1));
      }
      if (typeof value === "object") return Object.values(value).flatMap((item) => findEtfRows(item, depth + 1));
      return [];
    };
    const navRows = settled[1].status === "fulfilled" ? findEtfRows(settled[1].value) : [];
    navRows.forEach((row) => {
      const symbol = clean(row.a);
      if (!symbol) return;
      const current = bySymbol[symbol] || {};
      bySymbol[symbol] = {
        ...current,
        estimatedNav: number(row.f),
        premiumDiscount: number(row.g),
        previousNav: number(row.h),
        navUpdatedAt: [clean(row.i), clean(row.j)].filter(Boolean).join(" "),
        navSource: "TWSE MIS all_etf",
      };
    });
    return {
      bySymbol,
      count: Object.keys(bySymbol).length,
      coverage: { profile: rows.length > 0, premiumDiscount: navRows.length > 0 },
    };
  });
}

function etfDirectionFlags({ name = "", type = "", note = "", benchmark = "" } = {}) {
  // MOPS commonly uses the umbrella type `槓桿／反向指數股票型基金`
  // for both long 2x and inverse products.  Treating that generic type as a
  // direction made every 正2 ETF look inverse, so only use an unambiguous type
  // plus the fund name, note and benchmark when deciding direction.
  const genericUmbrella = /槓桿\s*[／/]\s*反向|反向\s*[／/]\s*槓桿/i.test(type);
  const typeDirection = genericUmbrella ? "" : type;
  const directionText = `${name} ${note} ${benchmark} ${typeDirection}`;
  return {
    leveraged: /正(?:向)?\s*2|兩倍|2\s*倍|2X|槓桿/i.test(directionText),
    inverse: /反向|反\s*1|負\s*一倍|-1X/i.test(directionText),
  };
}

export async function buildDeepData(symbol, instrumentType = "股票", market = "上市", options = {}) {
  if (!VALID_SYMBOL.test(symbol)) throw new Error("股票代號格式不正確");
  const isEtf = instrumentType === "ETF" || ETF_SYMBOL.test(symbol);
  const cacheKey = [
    "deep",
    symbol,
    isEtf ? "etf" : "stock",
    options.expectedRevenuePeriod || "no-revenue-period",
    options.expectedFinancialPeriod || "no-financial-period",
    options.expectedTradeDate || options.currentQuote?.trade_date || options.currentQuote?.priceDate || "no-trade-date",
    options.finmindRetries ?? 2,
  ].join(":");
  const factory = async () => {
    const endDate = taipeiToday();
    const finmindRetries = options.finmindRetries ?? 2;
    // TaiwanStockPriceAdj is a paid FinMind dataset and returns HTTP 400 for a
    // free-level token.  Using it unconditionally made every scheduled deep
    // analysis fail before technical indicators could be calculated.  The raw
    // daily feed is available at the documented free level; corporate-action
    // discontinuities remain guarded by `jumpAnomaly`, which disables the
    // technical score instead of treating the artificial jump as momentum.
    const finmindOptions = { retries: finmindRetries, finmindToken: options.finmindToken };
    const pricePromise = finmind("TaiwanStockPrice", symbol, monthsAgo(18), endDate, finmindOptions);
    const benchmarksPromise = options.benchmarks
      ? Promise.resolve(options.benchmarks)
      : buildBenchmarks({ finmindRetries, finmindToken: options.finmindToken });
    const profilePromise = isEtf ? buildEtfProfiles() : Promise.resolve({ bySymbol: {} });
    const tdccPromise = isEtf
      ? Promise.resolve({ bySymbol: {}, date: "" })
      : options.holdings !== undefined
        ? Promise.resolve({ bySymbol: { [symbol]: options.holdings }, date: options.holdings?.date || "" })
        : buildTdccSnapshot();
    const reuseCompatible = options.reuse?.analysisVersion === ANALYSIS_VERSION;
    const reusableRevenue = options.reuse?.revenue;
    const reusableFinancial = options.reuse?.financial;
    const reuseDiagnostics = options.reuse?.sourceDiagnostics || {};
    const reusableSource = (key) => ["ok", "reused"].includes(reuseDiagnostics?.[key]?.status);
    const reuseRevenue = reuseCompatible && !isEtf && reusableRevenue?.period &&
      finite(reusableRevenue.revenue) && Number(reusableRevenue.months) > 0 &&
      reusableSource("revenue") &&
      (!options.expectedRevenuePeriod || options.reuse.revenue.period === options.expectedRevenuePeriod)
      ? options.reuse.revenue
      : null;
    const financialCoverage = reusableFinancial?.sourceCoverage || {};
    const reuseFinancial = reuseCompatible && !isEtf && reusableFinancial?.period &&
      Number(reusableFinancial.quarters) > 0 &&
      Number(financialCoverage.incomeRows) > 0 && Number(financialCoverage.balanceRows) > 0 &&
      Number(financialCoverage.cashflowRows) > 0 &&
      ["income", "balance", "cashflow"].every(reusableSource) &&
      (!options.expectedFinancialPeriod || options.reuse.financial.period === options.expectedFinancialPeriod)
      ? options.reuse.financial
      : null;
    const companyPromises = isEtf ? [] : [
      reuseRevenue ? Promise.resolve([]) : finmind("TaiwanStockMonthRevenue", symbol, monthsAgo(48), endDate, finmindOptions),
      reuseFinancial ? Promise.resolve([]) : finmind("TaiwanStockFinancialStatements", symbol, monthsAgo(52), endDate, finmindOptions),
      reuseFinancial ? Promise.resolve([]) : finmind("TaiwanStockBalanceSheet", symbol, monthsAgo(52), endDate, finmindOptions),
      reuseFinancial ? Promise.resolve([]) : finmind("TaiwanStockCashFlowsStatement", symbol, monthsAgo(52), endDate, finmindOptions),
      finmind("TaiwanStockInstitutionalInvestorsBuySell", symbol, monthsAgo(3), endDate, finmindOptions),
      finmind("TaiwanStockMarginPurchaseShortSale", symbol, monthsAgo(3), endDate, finmindOptions),
      finmind("TaiwanStockSecuritiesLending", symbol, monthsAgo(3), endDate, finmindOptions),
    ];
    const settled = await Promise.allSettled([
      pricePromise,
      benchmarksPromise,
      profilePromise,
      tdccPromise,
      ...companyPromises,
    ]);
    if (settled[0].status !== "fulfilled") throw settled[0].reason;
    const diagnostic = (index, label, reused = false, previous = null) => {
      if (reused) return {
        ...(previous || {}),
        label,
        status: "reused",
        reusedFromStatus: previous?.status || null,
        retryable: false,
      };
      const entry = settled[index];
      if (entry?.status === "fulfilled") {
        const rowCount = objectRows(entry.value).length;
        return { label, status: rowCount ? "ok" : "empty-no-history", rows: rowCount, retryable: false };
      }
      const statusCode = Number(entry?.reason?.status) || null;
      return {
        label,
        status: "upstream-error",
        statusCode,
        retryable: statusCode === 402 || statusCode === 408 || statusCode === 429 || statusCode >= 500 || entry?.reason?.name === "AbortError",
        message: clean(entry?.reason?.message).slice(0, 240),
      };
    };
    const sourceDiagnostics = isEtf ? {
      price: diagnostic(0, "TaiwanStockPrice"),
      benchmark: diagnostic(1, "market benchmark"),
      profile: diagnostic(2, "ETF profile"),
    } : {
      price: diagnostic(0, "TaiwanStockPrice"),
      benchmark: diagnostic(1, "market benchmark"),
      holdings: diagnostic(3, "TDCC holdings", options.holdings !== undefined),
      revenue: diagnostic(4, "TaiwanStockMonthRevenue", Boolean(reuseRevenue), reuseDiagnostics.revenue),
      income: diagnostic(5, "TaiwanStockFinancialStatements", Boolean(reuseFinancial), reuseDiagnostics.income),
      balance: diagnostic(6, "TaiwanStockBalanceSheet", Boolean(reuseFinancial), reuseDiagnostics.balance),
      cashflow: diagnostic(7, "TaiwanStockCashFlowsStatement", Boolean(reuseFinancial), reuseDiagnostics.cashflow),
      institutional: diagnostic(8, "TaiwanStockInstitutionalInvestorsBuySell"),
      margin: diagnostic(9, "TaiwanStockMarginPurchaseShortSale"),
      lending: diagnostic(10, "TaiwanStockSecuritiesLending"),
    };
    if (!isEtf) {
      const essentialFailure = ["revenue", "income", "balance", "cashflow", "institutional", "margin"]
        .map((key) => sourceDiagnostics[key])
        .find((entry) => entry.status === "upstream-error");
      if (essentialFailure) {
        const error = new Error(`${essentialFailure.label}: ${essentialFailure.message || "上游資料取得失敗"}`);
        error.status = essentialFailure.statusCode;
        error.retryable = essentialFailure.retryable;
        throw error;
      }
    }
    const prices = mergeCurrentQuote(
      normalizePrice(settled[0].value),
      options.currentQuote,
    ).slice(-280);
    const benchmarks = settled[1].status === "fulfilled" ? settled[1].value : { listed: [], otc: [] };
    const benchmark = market === "上櫃" ? benchmarks.otc : benchmarks.listed;
    const output = {
      analysisVersion: ANALYSIS_VERSION,
      symbol,
      instrumentType: isEtf ? "ETF" : "股票",
      market,
      source: "FinMind 歷史價量／TWSE／TPEx／TDCC（重大價格不連續會停用技術評分）",
      fetchedAt: new Date().toISOString(),
      price: priceSummary(prices, benchmark),
      priceHistory: prices,
      benchmarkCoverage: benchmarks.coverage || {},
      sourceDiagnostics,
      missing: [],
    };
    if (!output.price.sufficient) output.missing.push(`歷史價量僅 ${output.price.rows || 0} 日（未滿 120 日）`);
    if (isEtf) {
      const profiles = settled[2].status === "fulfilled" ? settled[2].value : { bySymbol: {} };
      output.etf = profiles.bySymbol[symbol] || null;
      if (!output.etf) output.missing.push("ETF 基金基本資料");
      if (!finite(output.etf?.premiumDiscount)) output.missing.push("淨值折溢價");
      output.missing.push("追蹤誤差", "經理費與內扣費用", "成分股集中度");
      return output;
    }
    const rowsAt = (index) => settled[index]?.status === "fulfilled" ? settled[index].value : [];
    const revenue = reuseRevenue ? [] : normalizeRevenue(rowsAt(4));
    output.revenue = reuseRevenue
      ? refreshRevenueReaction(reuseRevenue, prices)
      : revenueSummary(revenue, prices);
    output.revenueHistory = revenue.slice(-40);
    output.financial = reuseFinancial || financialSummary(rowsAt(5), rowsAt(6), rowsAt(7));
    output.institutional = institutionalSummary(rowsAt(8), prices);
    output.margin = marginSummary(rowsAt(9));
    output.lending = lendingSummary(rowsAt(10));
    const tdcc = settled[3].status === "fulfilled" ? settled[3].value : { bySymbol: {} };
    output.holdings = tdcc.bySymbol[symbol] || null;
    output.reused = {
      revenue: Boolean(reuseRevenue),
      financial: Boolean(reuseFinancial),
    };
    if (options.expectedRevenuePeriod &&
        (!output.revenue?.period || output.revenue.period < options.expectedRevenuePeriod)) {
      sourceDiagnostics.revenue = {
        ...sourceDiagnostics.revenue,
        status: "stale-source-period",
        expectedPeriod: options.expectedRevenuePeriod,
        actualPeriod: output.revenue?.period || null,
      };
      output.missing.push(`最新月營收期別落後（來源 ${output.revenue?.period || "無"}／應為 ${options.expectedRevenuePeriod}）`);
    }
    if (options.expectedFinancialPeriod &&
        (!output.financial?.period || output.financial.period < options.expectedFinancialPeriod)) {
      sourceDiagnostics.income = {
        ...sourceDiagnostics.income,
        status: "stale-source-period",
        expectedPeriod: options.expectedFinancialPeriod,
        actualPeriod: output.financial?.period || null,
      };
      output.missing.push(`最新財報期別落後（來源 ${output.financial?.period || "無"}／應為 ${options.expectedFinancialPeriod}）`);
    }
    if (!finite(output.financial?.revenue)) {
      output.missing.push(output.financial?.revenueStatus === "source-not-comparable"
        ? "最新季營業額（該產業報表無可比單一營業額）"
        : "最新季營業額");
    }
    [
      [output.revenue.months >= 24, "24～36 個月月營收"],
      [output.financial.quarters >= 8, "8～12 季財報"],
      [output.institutional.days >= 20, "20 日法人歷史"],
      [output.margin.days >= 20, "20 日融資融券歷史"],
      [Boolean(output.holdings), "集保大戶／散戶結構"],
    ].forEach(([available, label]) => { if (!available) output.missing.push(label); });
    return output;
  };
  return options.bypassCache
    ? factory()
    : cached(cacheKey, 8 * 60 * 60 * 1_000, factory);
}

export async function buildPriceHistory(symbol, market = "上市", months = 18, options = {}) {
  if (!VALID_SYMBOL.test(symbol)) throw new Error("股票代號格式不正確");
  const requestedMonths = clamp(Number(months) || 18, 6, 24);
  return cached(`history:${symbol}:${market}:${requestedMonths}`, 60 * 60 * 1_000, async () => {
    const endDate = taipeiToday();
    const history = normalizePrice(
      await finmind("TaiwanStockPrice", symbol, monthsAgo(requestedMonths), endDate, {
        retries: options.finmindRetries ?? 2,
        finmindToken: options.finmindToken,
      }),
    ).slice(-280);
    if (history.length < 20) throw new Error(`${market} ${symbol} 歷史日線不足`);
    return {
      mode: "live",
      symbol,
      market,
      source: `FinMind TaiwanStockPrice 歷史行情（${market}）`,
      count: history.length,
      period: history.at(-1)?.date || null,
      history,
    };
  });
}

export const deepDataInternals = {
  normalizePrice,
  mergeCurrentQuote,
  priceSummary,
  normalizeRevenue,
  revenueSummary,
  financialSummary,
  institutionalSummary,
  marginSummary,
  etfDirectionFlags,
  latestIndexSnapshot,
  selectTaifexTx,
  finmindCooldownMs,
  validSymbol: (symbol) => VALID_SYMBOL.test(String(symbol || "")),
  isEtfSymbol: (symbol) => ETF_SYMBOL.test(String(symbol || "")),
};
