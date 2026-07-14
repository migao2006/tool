const TWSE_OPEN = "https://openapi.twse.com.tw/v1";
const TPEX_OPEN = "https://www.tpex.org.tw/openapi/v1";
const FINMIND = "https://api.finmindtrade.com/api/v4/data";
const TDCC_HOLDINGS = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5";
export const ANALYSIS_VERSION = "16.2-persistent-backend-cash-ttm";

const memoryCache = new Map();
const queues = new Map();
const policies = [
  { match: "api.finmindtrade.com", key: "finmind", gap: 1_350, concurrency: 1 },
  { match: "openapi.twse.com.tw", key: "twse", gap: 1_250, concurrency: 2 },
  { match: "www.tpex.org.tw", key: "tpex", gap: 1_250, concurrency: 2 },
  { match: "opendata.tdcc.com.tw", key: "tdcc", gap: 2_000, concurrency: 1 },
];

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

function addDays(value, days) {
  const date = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return value;
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function monthsAgo(months) {
  const date = new Date();
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

async function request(url, { format = "json", timeout = 35_000, retries = 2 } = {}) {
  return scheduled(url, async () => {
    let lastError;
    for (let attempt = 0; attempt <= retries; attempt += 1) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeout);
      try {
        const headers = {
          accept: format === "json" ? "application/json" : "text/csv,text/plain,*/*",
          "user-agent": "TaiwanStockSmartPicker/16.2",
        };
        const token = globalThis.process?.env?.FINMIND_TOKEN;
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

async function finmind(dataset, symbol, startDate, endDate) {
  const params = new URLSearchParams({
    dataset,
    data_id: symbol,
    start_date: startDate,
    end_date: endDate,
  });
  const payload = await request(`${FINMIND}?${params}`);
  if (Number(payload?.status) !== 200 || !Array.isArray(payload?.data)) {
    const error = new Error(payload?.msg || `${dataset} 無資料`);
    error.status = Number(payload?.status) || 502;
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
  });
  return normalized;
}

function revenueSummary(rows, prices) {
  if (!rows.length) return { months: 0 };
  const latest = rows.at(-1);
  const yoyValues = rows.slice(-3).map((row) => row.yoy);
  let consecutiveAcceleration = 0;
  for (let index = rows.length - 1; index > 0; index -= 1) {
    if (!finite(rows[index].yoy) || !finite(rows[index - 1].yoy) || rows[index].yoy <= rows[index - 1].yoy) break;
    consecutiveAcceleration += 1;
  }
  const sameMonthHistory = rows.filter((row) => row.month === latest.month && row.year < latest.year);
  const prior11 = rows.slice(-12, -1);
  const currentYear = rows.filter((row) => row.year === latest.year && row.month <= latest.month);
  const previousYear = rows.filter((row) => row.year === latest.year - 1 && row.month <= latest.month);
  const ytd = sum(currentYear.map((row) => row.revenue));
  const priorYtd = sum(previousYear.map((row) => row.revenue));
  const releaseIndex = prices.findIndex((row) => row.date >= latest.availableAt);
  const postRelease5 = releaseIndex >= 0 && prices[releaseIndex + 5]
    ? round((prices[releaseIndex + 5].close / prices[releaseIndex].close - 1) * 100)
    : null;
  const priorSameMean = mean(sameMonthHistory.slice(-3).map((row) => row.revenue));
  return {
    months: rows.length,
    period: latest.period,
    availableAt: latest.availableAt,
    revenue: latest.revenue,
    yoy: latest.yoy,
    mom: latest.mom,
    ytdYoy: priorYtd ? round((ytd / priorYtd - 1) * 100) : null,
    avg3Yoy: round(mean(yoyValues)),
    acceleration: finite(latest.yoy) && finite(rows.at(-2)?.yoy)
      ? round(latest.yoy - rows.at(-2).yoy)
      : null,
    acceleration3: finite(rows.at(-3)?.yoy) && finite(latest.yoy)
      ? round((latest.yoy - rows.at(-3).yoy) / 2)
      : null,
    consecutiveAcceleration,
    new12MonthHigh: prior11.length ? latest.revenue > Math.max(...prior11.map((row) => row.revenue)) : null,
    sameMonthRecord: sameMonthHistory.length
      ? latest.revenue > Math.max(...sameMonthHistory.map((row) => row.revenue))
      : null,
    seasonalGrowth: priorSameMean ? round((latest.revenue / priorSameMean - 1) * 100) : null,
    postRelease5,
  };
}

function refreshRevenueReaction(summary, prices) {
  if (!summary?.availableAt || finite(summary.postRelease5)) return summary;
  const releaseIndex = prices.findIndex((row) => row.date >= summary.availableAt);
  if (releaseIndex < 0 || !prices[releaseIndex + 5]) return summary;
  return {
    ...summary,
    postRelease5: round((prices[releaseIndex + 5].close / prices[releaseIndex].close - 1) * 100),
  };
}

function pivot(rows) {
  const map = new Map();
  rows.forEach((row) => {
    const date = isoDate(row.date);
    if (!map.has(date)) map.set(date, { date, values: {}, origins: {} });
    const current = map.get(date);
    current.values[clean(row.type)] = number(row.value);
    current.origins[clean(row.origin_name)] = number(row.value);
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
  const revenueValues = incomeSeries((row) => statementValue(row, ["Revenue"], /營業收入|收益合計/));
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
    const receivables = statementValue(balance, ["AccountsReceivable", "NotesAndAccountsReceivable"], /應收帳款|應收票據及帳款/);
    const interest = interestValues[globalIndex];
    return {
      date: income.date,
      period: `${income.date.slice(0, 4)} Q${quarterFromDate(income.date)}`,
      availableAt: addDays(income.date, quarterFromDate(income.date) === 4 ? 90 : 45),
      revenue: round(revenue, 0),
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
      cashConversion: netIncome ? round(cashflow.ocf / netIncome) : null,
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
  const yearAgo = quarters.at(-5) || {};
  const trailing = quarters.slice(-4);
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
  const growth = (current, previous) => finite(current) && finite(previous) && Number(previous) !== 0
    ? round((Number(current) / Math.abs(Number(previous)) - 1) * 100)
    : null;
  return {
    quarters: quarters.length,
    period: latest.period || "",
    availableAt: latest.availableAt || "",
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
    cashConversion: ttmCashConversion ?? latest.cashConversion ?? null,
    cashConversionBasis: ttmCashConversion == null ? "latest-quarter" : "TTM",
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
    marginChange5: change("marginBalance", 5),
    marginChange20: change("marginBalance", 20),
    marginUsage: latest.marginLimit ? round((latest.marginBalance / latest.marginLimit) * 100) : null,
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

export async function buildTdccSnapshot() {
  return cached("tdcc-current", 12 * 60 * 60 * 1_000, async () => {
    const csv = await request(TDCC_HOLDINGS, { format: "text", timeout: 60_000, retries: 1 });
    const lines = csv.replace(/^\uFEFF/, "").split(/\r?\n/).slice(1).filter(Boolean);
    const groups = new Map();
    for (const line of lines) {
      const [date, symbol, level, people, shares, ratio] = parseCsvLine(line);
      // TDCC pads many four-digit stock symbols with spaces in the fixed-width
      // export (for example "2330  ").  Trim every key before validating it.
      const normalizedSymbol = clean(symbol);
      const normalizedLevel = clean(level);
      if (!/^\d{4,6}$/.test(normalizedSymbol)) continue;
      if (!groups.has(normalizedSymbol)) groups.set(normalizedSymbol, { date: isoDate(date), levels: {} });
      groups.get(normalizedSymbol).levels[normalizedLevel] = {
        people: number(people),
        shares: number(shares),
        ratio: number(ratio),
      };
    }
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
  return dates.at(-1) >= new Date().toISOString().slice(0, 10);
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
  return resumed > new Date().toISOString().slice(0, 10);
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

export async function buildBenchmarks() {
  return cached("benchmarks", 6 * 60 * 60 * 1_000, async () => {
    const settled = await Promise.allSettled([
      request(`${TWSE_OPEN}/indicesReport/MI_5MINS_HIST`),
      request(`${TPEX_OPEN}/tpex_index`),
    ]);
    let listed = settled[0].status === "fulfilled"
      ? normalizeBenchmark(objectRows(settled[0].value), { close: "ClosingIndex" })
      : [];
    let otc = settled[1].status === "fulfilled"
      ? normalizeBenchmark(objectRows(settled[1].value), { close: "Close" })
      : [];
    const source = { listed: "TWSE OpenAPI", otc: "TPEx OpenAPI" };
    // The official OpenAPI index feeds may only expose the current month.  Do
    // not pretend 7–10 observations are a 20/60-day benchmark; use FinMind's
    // documented total-return-index history as the bounded fallback.
    if (listed.length < 65 || otc.length < 65) {
      const endDate = new Date().toISOString().slice(0, 10);
      const startDate = monthsAgo(8);
      const historical = await Promise.allSettled([
        listed.length < 65 ? finmind("TaiwanStockTotalReturnIndex", "TAIEX", startDate, endDate) : Promise.resolve([]),
        otc.length < 65 ? finmind("TaiwanStockTotalReturnIndex", "TPEx", startDate, endDate) : Promise.resolve([]),
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
      source,
      coverage: { listed: listed.length >= 65, otc: otc.length >= 65 },
    };
  });
}

export async function buildEtfProfiles() {
  return cached("etf-profiles", 12 * 60 * 60 * 1_000, async () => {
    const rows = objectRows(await request(`${TWSE_OPEN}/opendata/t187ap47_L`));
    const bySymbol = {};
    rows.forEach((row) => {
      const symbol = clean(row["基金代號"]);
      if (!symbol) return;
      const name = clean(row["基金簡稱"] ?? row["基金中文名稱"]);
      const type = clean(row["基金類型"]);
      const note = clean(row["備註"]);
      const combined = `${name} ${type} ${note}`;
      bySymbol[symbol] = {
        publishedAt: isoDate(row["出表日期"]),
        fundType: type,
        benchmark: clean(row["標的指數/追蹤指數名稱"]),
        foreignExposure: truthyFlag(row["是否包含國外成分股"]),
        units: number(row["發行單位數/轉換數"]),
        inceptionDate: isoDate(row["成立日期"]),
        listingDate: isoDate(row["上市日期"]),
        leveraged: /槓桿|正2|兩倍|2X/i.test(combined),
        inverse: /反向|反1|-1X/i.test(combined),
        bond: /債券|債/i.test(`${type} ${name}`),
      };
    });
    return { bySymbol, count: Object.keys(bySymbol).length };
  });
}

export async function buildDeepData(symbol, instrumentType = "股票", market = "上市", options = {}) {
  if (!/^\d{4,6}$/.test(symbol)) throw new Error("股票代號格式不正確");
  const isEtf = instrumentType === "ETF" || /^00\d{2,4}$/.test(symbol);
  return cached(`deep:${symbol}:${isEtf ? "etf" : "stock"}`, 8 * 60 * 60 * 1_000, async () => {
    const endDate = new Date().toISOString().slice(0, 10);
    const pricePromise = finmind("TaiwanStockPrice", symbol, monthsAgo(18), endDate);
    const benchmarksPromise = buildBenchmarks();
    const profilePromise = isEtf ? buildEtfProfiles() : Promise.resolve({ bySymbol: {} });
    const tdccPromise = isEtf ? Promise.resolve({ bySymbol: {}, date: "" }) : buildTdccSnapshot().catch(() => ({ bySymbol: {}, date: "" }));
    const reuseCompatible = options.reuse?.analysisVersion === ANALYSIS_VERSION;
    const reuseRevenue = reuseCompatible && !isEtf && options.reuse?.revenue &&
      (!options.expectedRevenuePeriod || options.reuse.revenue.period === options.expectedRevenuePeriod)
      ? options.reuse.revenue
      : null;
    const reuseFinancial = reuseCompatible && !isEtf && options.reuse?.financial &&
      (!options.expectedFinancialPeriod || options.reuse.financial.period === options.expectedFinancialPeriod)
      ? options.reuse.financial
      : null;
    const companyPromises = isEtf ? [] : [
      reuseRevenue ? Promise.resolve([]) : finmind("TaiwanStockMonthRevenue", symbol, monthsAgo(48), endDate),
      reuseFinancial ? Promise.resolve([]) : finmind("TaiwanStockFinancialStatements", symbol, monthsAgo(52), endDate),
      reuseFinancial ? Promise.resolve([]) : finmind("TaiwanStockBalanceSheet", symbol, monthsAgo(52), endDate),
      reuseFinancial ? Promise.resolve([]) : finmind("TaiwanStockCashFlowsStatement", symbol, monthsAgo(52), endDate),
      finmind("TaiwanStockInstitutionalInvestorsBuySell", symbol, monthsAgo(3), endDate),
      finmind("TaiwanStockMarginPurchaseShortSale", symbol, monthsAgo(3), endDate),
      finmind("TaiwanStockSecuritiesLending", symbol, monthsAgo(3), endDate),
    ];
    const settled = await Promise.allSettled([
      pricePromise,
      benchmarksPromise,
      profilePromise,
      tdccPromise,
      ...companyPromises,
    ]);
    if (settled[0].status !== "fulfilled") throw settled[0].reason;
    const prices = normalizePrice(settled[0].value).slice(-280);
    const benchmarks = settled[1].status === "fulfilled" ? settled[1].value : { listed: [], otc: [] };
    const benchmark = market === "上櫃" ? benchmarks.otc : benchmarks.listed;
    const output = {
      analysisVersion: ANALYSIS_VERSION,
      symbol,
      instrumentType: isEtf ? "ETF" : "股票",
      market,
      source: "FinMind 歷史公開資料／TWSE／TPEx／TDCC",
      fetchedAt: new Date().toISOString(),
      price: priceSummary(prices, benchmark),
      priceHistory: prices,
      benchmarkCoverage: benchmarks.coverage || {},
      missing: [],
    };
    if (isEtf) {
      const profiles = settled[2].status === "fulfilled" ? settled[2].value : { bySymbol: {} };
      output.etf = profiles.bySymbol[symbol] || null;
      if (!output.etf) output.missing.push("ETF 基金基本資料");
      output.missing.push("淨值折溢價", "追蹤誤差", "經理費與內扣費用", "成分股集中度");
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
    [
      [output.revenue.months >= 24, "24～36 個月月營收"],
      [output.financial.quarters >= 8, "8～12 季財報"],
      [output.institutional.days >= 20, "20 日法人歷史"],
      [output.margin.days >= 20, "20 日融資融券歷史"],
      [Boolean(output.holdings), "集保大戶／散戶結構"],
    ].forEach(([available, label]) => { if (!available) output.missing.push(label); });
    return output;
  });
}

export async function buildPriceHistory(symbol, market = "上市", months = 18) {
  if (!/^\d{4,6}$/.test(symbol)) throw new Error("股票代號格式不正確");
  const requestedMonths = clamp(Number(months) || 18, 6, 24);
  return cached(`history:${symbol}:${market}:${requestedMonths}`, 60 * 60 * 1_000, async () => {
    const endDate = new Date().toISOString().slice(0, 10);
    const history = normalizePrice(
      await finmind("TaiwanStockPrice", symbol, monthsAgo(requestedMonths), endDate),
    ).slice(-280);
    if (history.length < 20) throw new Error(`${market} ${symbol} 歷史日線不足`);
    return {
      mode: "live",
      symbol,
      market,
      source: `FinMind TaiwanStockPrice（${market}）`,
      count: history.length,
      period: history.at(-1)?.date || null,
      history,
    };
  });
}

export const deepDataInternals = {
  normalizePrice,
  priceSummary,
  normalizeRevenue,
  revenueSummary,
  financialSummary,
  institutionalSummary,
  marginSummary,
};
