import {
  buildBenchmarks,
  buildEtfProfiles,
  buildRiskSnapshot,
} from "./deep-data.js";
import {
  readDataHealth,
  readBackendAnalysis,
  readBackendHistory,
  readBackendRankings,
  readRankingBacktest,
  readBackendStatus,
} from "./backend-store.js";

const SUPABASE_EDGE = "https://lfkdkdyaatdlizryiyon.supabase.co/functions/v1/twss-market-data";
const SUPABASE_HISTORY_EDGE = "https://lfkdkdyaatdlizryiyon.supabase.co/functions/v1/twss-sync-batch";
const TWSE_OPEN = "https://openapi.twse.com.tw/v1";
const TWSE_WEB = "https://www.twse.com.tw";
const TPEX_OPEN = "https://www.tpex.org.tw/openapi/v1";
const VERSION = "17.2";

const FINANCIAL_CATEGORIES = ["ci", "fh", "basi", "bd", "ins", "mim"];

const industryNames = {
  "01": "水泥工業",
  "02": "食品工業",
  "03": "塑膠工業",
  "04": "紡織纖維",
  "05": "電機機械",
  "06": "電器電纜",
  "07": "化學生技醫療",
  "08": "玻璃陶瓷",
  "09": "造紙工業",
  "10": "鋼鐵工業",
  "11": "橡膠工業",
  "12": "汽車工業",
  "14": "建材營造",
  "15": "航運業",
  "16": "觀光餐旅",
  "17": "金融保險業",
  "18": "貿易百貨",
  "19": "綜合",
  "20": "其他業",
  "21": "化學工業",
  "22": "生技醫療業",
  "23": "油電燃氣業",
  "24": "半導體業",
  "25": "電腦及週邊設備業",
  "26": "光電業",
  "27": "通信網路業",
  "28": "電子零組件業",
  "29": "電子通路業",
  "30": "資訊服務業",
  "31": "其他電子業",
  "35": "綠能環保",
  "36": "數位雲端",
  "37": "運動休閒",
  "38": "居家生活",
};

let stockCache = null;
let revenueCache = null;
let financialCache = null;

const requestQueues = new Map();
const SOURCE_POLICIES = [
  { match: "openapi.twse.com.tw", key: "twse-openapi", gap: 1_200, limit: 2 },
  { match: "www.twse.com.tw", key: "twse-web", gap: 1_500, limit: 1 },
  { match: "www.tpex.org.tw", key: "tpex-openapi", gap: 1_200, limit: 2 },
  { match: "mops.twse.com.tw", key: "mops", gap: 1_800, limit: 1 },
  { match: "supabase.co", key: "supabase", gap: 350, limit: 2 },
];

function pick(row, ...keys) {
  if (!row) return undefined;
  for (const key of keys) {
    if (row[key] !== undefined && row[key] !== "") return row[key];
  }
}

function numeric(value) {
  if (value == null) return null;
  const raw = String(value)
    .trim()
    .replaceAll(",", "")
    .replaceAll("%", "")
    .replaceAll("−", "-");
  if (!raw || ["-", "--", "---", "N/A", "null"].includes(raw)) return null;
  const parsed = Number(raw.replace(/^\+/, ""));
  return Number.isFinite(parsed) ? parsed : null;
}

function text(value) {
  return value == null ? "" : String(value).trim();
}

function prefer(value, fallback = null) {
  return value == null || value === "" ? fallback : value;
}

function industry(value) {
  const raw = text(value);
  return industryNames[raw.padStart(2, "0")] || raw || "未分類";
}

function tableToRows(fields, data) {
  if (!Array.isArray(fields) || !Array.isArray(data)) return [];
  return data.map((item) => {
    if (!Array.isArray(item)) return item;
    const row = {};
    fields.forEach((field, index) => {
      if (row[field] === undefined) row[field] = item[index];
    });
    return row;
  });
}

function rows(value) {
  if (Array.isArray(value)) return value;
  if (Array.isArray(value?.data)) {
    return value.data.some(Array.isArray)
      ? tableToRows(value.fields, value.data)
      : value.data;
  }
  const table = Array.isArray(value?.tables)
    ? value.tables.find((item) => Array.isArray(item?.data) && item.data.length)
    : null;
  return table ? tableToRows(table.fields, table.data) : [];
}

function rowsFromNamedTable(value, titleText) {
  const table = Array.isArray(value?.tables)
    ? value.tables.find(
        (item) => text(item?.title).includes(titleText) && Array.isArray(item?.data),
      )
    : null;
  return table ? tableToRows(table.fields, table.data) : [];
}

function twseMarginRows(value) {
  const table = Array.isArray(value?.tables)
    ? value.tables.find(
        (item) =>
          text(item?.title).includes("融資融券彙總") && Array.isArray(item?.data),
      )
    : null;
  if (!table) return [];
  return table.data
    .filter(Array.isArray)
    .map((item) => ({
      股票代號: text(item[0]),
      股票名稱: item[1],
      融資買進: item[2],
      融資賣出: item[3],
      融資現金償還: item[4],
      融資前日餘額: item[5],
      融資今日餘額: item[6],
      融券買進: item[8],
      融券賣出: item[9],
      融券現券償還: item[10],
      融券前日餘額: item[11],
      融券今日餘額: item[12],
    }))
    .filter((row) => /^\d{4}$/.test(row.股票代號));
}

function symbolOf(row) {
  return text(
    pick(
      row,
      "Code",
      "股票代號",
      "證券代號",
      "公司代號",
      "SecuritiesCompanyCode",
      "代號",
      "Symbol",
    ),
  );
}

function instrumentTypeOf(symbol) {
  if (/^00\d{2,4}[A-Z]?$/i.test(symbol)) return "ETF";
  if (/^[1-9]\d{3}$/.test(symbol)) return "股票";
  return "其他";
}

function isSupportedSymbol(symbol) {
  return instrumentTypeOf(symbol) !== "其他";
}

function isCompanySymbol(symbol) {
  return instrumentTypeOf(symbol) === "股票";
}

function nameOf(row) {
  return text(
    pick(
      row,
      "Name",
      "股票名稱",
      "證券名稱",
      "公司名稱",
      "公司簡稱",
      "CompanyName",
      "名稱",
    ),
  );
}

function mapBySymbol(items) {
  return new Map(
    items.map((row) => [symbolOf(row), row]).filter(([symbol]) => symbol),
  );
}

function sharesToLots(value) {
  const parsed = numeric(value);
  return parsed == null ? null : parsed / 1000;
}

function dateText(value) {
  const raw = text(value).replaceAll("/", "").replaceAll("-", "");
  if (/^\d{8}$/.test(raw)) {
    return `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`;
  }
  if (/^\d{7}$/.test(raw)) {
    const year = Number(raw.slice(0, 3)) + 1911;
    return `${year}-${raw.slice(3, 5)}-${raw.slice(5, 7)}`;
  }
  return text(value);
}

function dateFromTitle(value) {
  const match = text(value).match(/(\d{3})年(\d{2})月(\d{2})日/);
  if (!match) return "";
  return `${Number(match[1]) + 1911}-${match[2]}-${match[3]}`;
}

function payloadDate(payload, fallbackRows = []) {
  return (
    dateText(payload?.date) ||
    dateFromTitle(payload?.title) ||
    dateFromTitle(payload?.tables?.find((table) => table?.title)?.title) ||
    dateText(pick(fallbackRows[0], "Date", "日期", "出表日期", "資料日期"))
  );
}

function latestDate(...values) {
  const dates = values
    .flat(Infinity)
    .map(dateText)
    .filter((value) => /^\d{4}-\d{2}-\d{2}$/.test(value));
  return dates.sort().at(-1) || "";
}

function queryDate(value) {
  return dateText(value).replaceAll("-", "");
}

function periodText(row) {
  const direct = text(
    pick(row, "資料年月", "年月", "YearMonth", "DataYearMonth"),
  )
    .replaceAll("/", "")
    .replaceAll("-", "");
  if (/^\d{6}$/.test(direct)) {
    return `${direct.slice(0, 4)}-${direct.slice(4, 6)}`;
  }
  if (/^\d{5}$/.test(direct)) {
    return `${Number(direct.slice(0, 3)) + 1911}-${direct.slice(3, 5)}`;
  }
  const year = numeric(pick(row, "年度", "年", "Year"));
  const month = numeric(pick(row, "月份", "月", "Month"));
  if (year != null && month != null) {
    return `${year < 1911 ? year + 1911 : year}-${String(month).padStart(2, "0")}`;
  }
  return dateText(pick(row, "出表日期", "資料日期", "Date")).slice(0, 7);
}

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function sourcePolicy(url) {
  return (
    SOURCE_POLICIES.find((policy) => url.includes(policy.match)) || {
      key: "other",
      gap: 500,
      limit: 2,
    }
  );
}

function queueFor(policy) {
  if (!requestQueues.has(policy.key)) {
    requestQueues.set(policy.key, {
      active: 0,
      lastStartedAt: 0,
      launching: false,
      jobs: [],
      policy,
    });
  }
  return requestQueues.get(policy.key);
}

function pumpQueue(state) {
  if (state.launching) return;
  state.launching = true;
  void (async () => {
    while (state.active < state.policy.limit && state.jobs.length) {
      const wait = Math.max(
        0,
        state.lastStartedAt + state.policy.gap - Date.now(),
      );
      if (wait) await sleep(wait);
      const job = state.jobs.shift();
      state.active += 1;
      state.lastStartedAt = Date.now();
      Promise.resolve()
        .then(job.task)
        .then(job.resolve, job.reject)
        .finally(() => {
          state.active -= 1;
          pumpQueue(state);
        });
    }
    state.launching = false;
    if (state.active < state.policy.limit && state.jobs.length) pumpQueue(state);
  })();
}

function scheduledRequest(url, task) {
  const state = queueFor(sourcePolicy(url));
  return new Promise((resolve, reject) => {
    state.jobs.push({ task, resolve, reject });
    pumpQueue(state);
  });
}

async function fetchAttempt(url, timeout) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(url, {
      headers: {
        accept: "application/json",
        "user-agent": `TaiwanStockSmartPicker/${VERSION}`,
      },
      signal: controller.signal,
    });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      const error = new Error(body?.error || `Upstream ${response.status}`);
      error.status = response.status;
      error.code = body?.code || null;
      error.retryAfterAt = body?.retryAfterAt || null;
      error.retryAfter = Number(response.headers.get("retry-after")) || null;
      throw error;
    }
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}

async function fetchJson(url, timeout = 24_000, retries = 2) {
  return scheduledRequest(url, async () => {
    let lastError;
    for (let attempt = 0; attempt <= retries; attempt += 1) {
      try {
        return await fetchAttempt(url, timeout);
      } catch (error) {
        lastError = error;
        const retryable =
          error?.name === "AbortError" ||
          error?.status === 408 ||
          error?.status === 429 ||
          error?.status >= 500;
        if (!retryable || attempt === retries) throw error;
        const retryAfter = error?.retryAfter ? error.retryAfter * 1_000 : 0;
        await sleep(Math.max(retryAfter, 1_200 * 2 ** attempt) + 150);
      }
    }
    throw lastError;
  });
}

async function fetchEdge(search, timeout = 38_000) {
  return fetchJson(`${SUPABASE_EDGE}${search}`, timeout);
}

function institutionalFields(row, existing = {}) {
  const foreign = sharesToLots(
    pick(
      row,
      "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference",
      "ForeignInvestorsInclude MainlandAreaInvestors-Difference",
      "ForeignInvestorsIncludeMainlandAreaInvestors-Difference",
      "ForeignInvestorsBuySell",
      "ForeignInvestorsNetBuySell",
      "ForeignInvestmentBuySell",
      "ForeignInvestmentNetBuySell",
      "外陸資買賣超股數(不含外資自營商)",
      "外資及陸資買賣超股數(不含外資自營商)",
      "外資及陸資買賣超股數",
      "外資買賣超",
    ),
  );
  const trust = sharesToLots(
    pick(
      row,
      "SecuritiesInvestmentTrustCompanies-Difference",
      "InvestmentTrustBuySell",
      "InvestmentTrustNetBuySell",
      "投信買賣超股數",
      "投信買賣超",
    ),
  );
  let dealer = sharesToLots(
    pick(
      row,
      "Dealers-Difference",
      "DealerBuySell",
      "DealerNetBuySell",
      "DealersBuySell",
      "DealersNetBuySell",
      "自營商買賣超股數",
      "自營商買賣超",
    ),
  );
  if (dealer == null) {
    const own = sharesToLots(
      pick(row, "DealerSelfBuySell", "自營商買賣超股數(自行買賣)"),
    );
    const hedge = sharesToLots(
      pick(row, "DealerHedgingBuySell", "自營商買賣超股數(避險)"),
    );
    dealer = own == null && hedge == null ? null : (own || 0) + (hedge || 0);
  }
  const total = sharesToLots(
    pick(
      row,
      "TotalDifference",
      "TotalBuySell",
      "TotalNetBuySell",
      "三大法人買賣超股數",
      "合計買賣超",
    ),
  );
  return {
    foreign: prefer(foreign, existing.foreign),
    trust: prefer(trust, existing.trust),
    dealer: prefer(dealer, existing.dealer),
    inst: prefer(
      total,
      foreign == null && trust == null && dealer == null
        ? existing.inst
        : (foreign || 0) + (trust || 0) + (dealer || 0),
    ),
  };
}

function marginFields(row, existing = {}) {
  const marginBalance = numeric(
    pick(
      row,
      "MarginPurchaseBalance",
      "BalanceOfMarginPurchase",
      "TodayBalanceOfMarginPurchase",
      "融資今日餘額",
      "資餘額",
    ),
  );
  const previousMargin = numeric(
    pick(
      row,
      "MarginPurchaseBalancePreviousDay",
      "PreviousBalanceOfMarginPurchase",
      "融資前日餘額",
      "前資餘額",
    ),
  );
  const shortBalance = numeric(
    pick(
      row,
      "ShortSaleBalance",
      "BalanceOfShortSale",
      "TodayBalanceOfShortSale",
      "融券今日餘額",
      "券餘額",
    ),
  );
  const previousShort = numeric(
    pick(
      row,
      "ShortSaleBalancePreviousDay",
      "PreviousBalanceOfShortSale",
      "融券前日餘額",
      "前券餘額",
    ),
  );
  const marginBuy = numeric(
    pick(row, "MarginPurchase", "MarginPurchaseBuy", "融資買進", "資買"),
  );
  const marginSell = numeric(
    pick(
      row,
      "MarginSales",
      "MarginSale",
      "MarginPurchaseSale",
      "融資賣出",
      "資賣",
    ),
  );
  const cashRedemption = numeric(
    pick(row, "CashRedemption", "融資現金償還", "現償"),
  );
  const shortSell = numeric(pick(row, "ShortSale", "融券賣出", "券賣"));
  const shortBuy = numeric(
    pick(
      row,
      "ShortConvering",
      "ShortCovering",
      "ShortBuy",
      "融券買進",
      "券買",
    ),
  );
  const stockRedemption = numeric(
    pick(row, "StockRedemption", "融券現券償還", "券償"),
  );
  const marginFlow =
    marginBuy == null && marginSell == null && cashRedemption == null
      ? null
      : (marginBuy || 0) - (marginSell || 0) - (cashRedemption || 0);
  const shortFlow =
    shortSell == null && shortBuy == null && stockRedemption == null
      ? null
      : (shortSell || 0) - (shortBuy || 0) - (stockRedemption || 0);
  const marginChange = prefer(
    numeric(pick(row, "ChangeOfMarginPurchase", "融資增減", "資增減")),
    marginBalance != null && previousMargin != null
      ? marginBalance - previousMargin
      : prefer(marginFlow, existing.marginChange),
  );
  const shortChange = prefer(
    numeric(pick(row, "ChangeOfShortSale", "融券增減", "券增減")),
    shortBalance != null && previousShort != null
      ? shortBalance - previousShort
      : prefer(shortFlow, existing.shortChange),
  );
  return {
    marginBalance: prefer(marginBalance, existing.marginBalance),
    marginChange,
    shortBalance: prefer(shortBalance, existing.shortBalance),
    shortChange,
  };
}

function signedDifference(row) {
  const difference = numeric(pick(row, "Change", "漲跌價差", "漲跌"));
  if (difference == null) return null;
  const sign = text(pick(row, "漲跌(+/-)", "漲跌符號"));
  if (sign.includes("-") || /green|down/i.test(sign)) return -Math.abs(difference);
  if (sign.includes("+") || /red|up/i.test(sign)) return Math.abs(difference);
  return difference;
}

function officialStock(row, market, maps, existing = {}) {
  const symbol = symbolOf(row);
  if (!isSupportedSymbol(symbol)) return null;
  const instrumentType = instrumentTypeOf(symbol);
  const valuation = maps.valuations.get(symbol);
  const company = maps.companies.get(symbol);
  const institutional = maps.institutional.get(symbol);
  const margin = maps.margin.get(symbol);
  const close = numeric(pick(row, "ClosingPrice", "Close", "收盤價", "收盤"));
  const difference = signedDifference(row);
  const previous = close != null && difference != null ? close - difference : null;
  const volume = numeric(pick(row, "TradeVolume", "TradingShares", "成交股數"));
  return {
    ...existing,
    symbol,
    instrumentType,
    name: nameOf(row) || text(existing.name),
    industry:
      instrumentType === "ETF"
        ? "ETF"
        : industry(
            pick(
              company,
              "產業別",
              "Industry",
              "產業類別",
              "SecuritiesIndustryCode",
            ) ?? existing.industry,
          ),
    market,
    close: prefer(close, existing.close),
    change:
      previous && difference != null ? (difference / previous) * 100 : existing.change,
    open: prefer(
      numeric(pick(row, "OpeningPrice", "Open", "開盤價", "開盤")),
      existing.open,
    ),
    high: prefer(
      numeric(pick(row, "HighestPrice", "High", "最高價", "最高")),
      existing.high,
    ),
    low: prefer(
      numeric(pick(row, "LowestPrice", "Low", "最低價", "最低")),
      existing.low,
    ),
    volume: volume == null ? existing.volume : volume / 1000,
    value: prefer(
      numeric(pick(row, "TradeValue", "TransactionAmount", "成交金額")),
      existing.value,
    ),
    transactions: prefer(
      numeric(pick(row, "Transaction", "TransactionNumber", "成交筆數")),
      existing.transactions,
    ),
    pe: prefer(
      numeric(pick(valuation, "PEratio", "PriceEarningRatio", "本益比")),
      prefer(numeric(pick(row, "本益比")), existing.pe),
    ),
    pb: prefer(
      numeric(pick(valuation, "PBratio", "PriceBookRatio", "股價淨值比")),
      existing.pb,
    ),
    yield: prefer(
      numeric(
        pick(valuation, "DividendYield", "YieldRatio", "殖利率(%)", "殖利率"),
      ),
      existing.yield,
    ),
    ...institutionalFields(institutional, existing),
    ...marginFields(margin, existing),
    demo: false,
  };
}

function fulfilled(result, fallback = null) {
  return result?.status === "fulfilled" ? result.value : fallback;
}

async function buildStocks() {
  const initial = await Promise.allSettled([
    fetchJson(`${TWSE_OPEN}/exchangeReport/STOCK_DAY_ALL`),
    fetchJson(`${TWSE_OPEN}/exchangeReport/BWIBBU_ALL`),
    fetchJson(`${TWSE_OPEN}/opendata/t187ap03_L`),
    fetchJson(`${TWSE_OPEN}/exchangeReport/MI_MARGN`),
    fetchJson(`${TPEX_OPEN}/tpex_mainboard_daily_close_quotes`),
    fetchJson(`${TPEX_OPEN}/tpex_mainboard_peratio_analysis`),
    fetchJson(`${TPEX_OPEN}/mopsfin_t187ap03_O`),
    fetchJson(`${TPEX_OPEN}/tpex_mainboard_margin_balance`),
    fetchJson(`${TPEX_OPEN}/tpex_3insti_daily_trading`),
  ]);

  const twseOpenPricePayload = fulfilled(initial[0], []);
  const twseOpenPrices = rows(twseOpenPricePayload);
  const twseOpenValuationPayload = fulfilled(initial[1], []);
  const twseOpenValuations = rows(twseOpenValuationPayload);
  const twseCompanies = rows(fulfilled(initial[2], []));
  const twseOpenMargin = rows(fulfilled(initial[3], []));
  const tpexPricePayload = fulfilled(initial[4], []);
  const tpexPrices = rows(tpexPricePayload);
  const tpexValuationPayload = fulfilled(initial[5], []);
  const tpexValuations = rows(tpexValuationPayload);
  const tpexCompanies = rows(fulfilled(initial[6], []));
  const tpexMarginPayload = fulfilled(initial[7], []);
  const tpexMargin = rows(tpexMarginPayload);
  const tpexInstitutionalPayload = fulfilled(initial[8], []);
  const tpexInstitutional = rows(tpexInstitutionalPayload);
  let edge = null;
  if (twseOpenPrices.length < 20 || tpexPrices.length < 20) {
    edge = await fetchEdge("?type=stocks", 20_000).catch(() => null);
  }
  const edgeStocks =
    edge && Array.isArray(edge.stocks)
      ? edge.stocks.map((stock) => ({
          ...stock,
          symbol: text(stock.symbol),
          instrumentType:
            stock.instrumentType || instrumentTypeOf(text(stock.symbol)),
        }))
      : [];

  const openTwsePriceDate = payloadDate(twseOpenPricePayload, twseOpenPrices);
  const tpexPriceDate = payloadDate(tpexPricePayload, tpexPrices);
  const tpexMarginDate = payloadDate(tpexMarginPayload, tpexMargin);
  const targetDate = latestDate(tpexPriceDate, openTwsePriceDate);
  const target = queryDate(targetDate);
  const marginTarget = queryDate(tpexMarginDate);

  const refreshed = await Promise.allSettled([
    target
      ? fetchJson(
          `${TWSE_WEB}/rwd/zh/afterTrading/MI_INDEX?date=${target}&type=ALLBUT0999&response=json`,
          24_000,
        )
      : Promise.resolve(null),
    target
      ? fetchJson(
          `${TWSE_WEB}/rwd/zh/afterTrading/BWIBBU_d?date=${target}&selectType=ALL&response=json`,
          20_000,
        )
      : Promise.resolve(null),
    marginTarget
      ? fetchJson(
          `${TWSE_WEB}/rwd/zh/marginTrading/MI_MARGN?date=${marginTarget}&selectType=STOCK&response=json`,
          20_000,
        )
      : Promise.resolve(null),
    target
      ? fetchJson(
          `${TWSE_WEB}/rwd/zh/fund/T86?date=${target}&response=json&selectType=ALLBUT0999`,
          45_000,
        )
      : Promise.resolve(null),
  ]);

  const currentTwsePricePayload = fulfilled(refreshed[0], null);
  const currentTwsePrices = rowsFromNamedTable(
    currentTwsePricePayload,
    "每日收盤行情",
  );
  const twsePrices =
    currentTwsePrices.length >= 20 ? currentTwsePrices : twseOpenPrices;
  const twsePriceDate =
    currentTwsePrices.length >= 20
      ? payloadDate(currentTwsePricePayload, currentTwsePrices)
      : openTwsePriceDate;

  const currentTwseValuationPayload = fulfilled(refreshed[1], null);
  const currentTwseValuations = rows(currentTwseValuationPayload);
  const twseValuations =
    currentTwseValuations.length >= 20
      ? currentTwseValuations
      : twseOpenValuations;
  const twseValuationDate =
    currentTwseValuations.length >= 20
      ? payloadDate(currentTwseValuationPayload, currentTwseValuations)
      : payloadDate(twseOpenValuationPayload, twseOpenValuations);

  const currentTwseMarginPayload = fulfilled(refreshed[2], null);
  const currentTwseMargin = twseMarginRows(currentTwseMarginPayload);
  const twseMargin =
    currentTwseMargin.length >= 20 ? currentTwseMargin : twseOpenMargin;
  const twseMarginDate =
    currentTwseMargin.length >= 20
      ? payloadDate(currentTwseMarginPayload, currentTwseMargin)
      : "";

  const refreshedTwseInstitutionalPayload = fulfilled(
    refreshed[3],
    null,
  );
  const refreshedTwseInstitutional = rows(refreshedTwseInstitutionalPayload);
  const twseInstitutional = refreshedTwseInstitutional;
  const twseInstitutionalDate =
    refreshedTwseInstitutional.length >= 20
      ? payloadDate(refreshedTwseInstitutionalPayload, refreshedTwseInstitutional)
      : "";

  if (
    twsePrices.length < 20 &&
    tpexPrices.length < 20 &&
    edgeStocks.length < 20
  ) {
    throw new Error("TWSE、TPEx 與備援來源目前皆無法取得盤後資料");
  }

  const edgeMap = new Map(
    edgeStocks.map((row) => [text(pick(row, "symbol", "Code", "股票代號")), row]),
  );
  const listedMaps = {
    valuations: mapBySymbol(twseValuations),
    companies: mapBySymbol(twseCompanies),
    institutional: mapBySymbol(twseInstitutional),
    margin: mapBySymbol(twseMargin),
  };
  const otcMaps = {
    valuations: mapBySymbol(tpexValuations),
    companies: mapBySymbol(tpexCompanies),
    institutional: mapBySymbol(tpexInstitutional),
    margin: mapBySymbol(tpexMargin),
  };
  const listed = twsePrices
    .map((row) =>
      officialStock(row, "上市", listedMaps, edgeMap.get(symbolOf(row)) || {}),
    )
    .filter(Boolean);
  const otc = tpexPrices
    .map((row) =>
      officialStock(row, "上櫃", otcMaps, edgeMap.get(symbolOf(row)) || {}),
    )
    .filter(Boolean);
  const official = [...listed, ...otc];
  const officialSymbols = new Set(official.map((stock) => stock.symbol));
  const fallbackOnly = edgeStocks.filter(
    (stock) =>
      isSupportedSymbol(text(stock.symbol)) &&
      !officialSymbols.has(text(stock.symbol)),
  );
  const rawStocks = official.length >= 20 ? [...official, ...fallbackOnly] : edgeStocks;
  let riskSnapshot = { bySymbol: {}, coverage: {} };
  try {
    riskSnapshot = await buildRiskSnapshot();
  } catch {
    // Risk source failures lower confidence in the scoring layer; they must not
    // make the entire market snapshot disappear.
  }
  const riskCoverageValues = Object.values(riskSnapshot.coverage || {});
  const riskCoverageComplete = riskCoverageValues.length === 8 && riskCoverageValues.every(Boolean);
  const stocks = rawStocks.map((stock) => {
    const risk = riskSnapshot.bySymbol?.[stock.symbol] || {};
    return {
      ...stock,
      risk: { ...risk, coverageComplete: riskCoverageComplete },
      disp: risk.disposition === true || stock.disp === true,
      full: risk.altered === true || stock.full === true,
      suspended: risk.suspended === true,
      hardExcluded: risk.hardExcluded === true,
    };
  });
  const instruments = {
    listed: stocks.filter(
      (stock) => stock.market === "上市" && stock.instrumentType !== "ETF",
    ).length,
    otc: stocks.filter(
      (stock) => stock.market === "上櫃" && stock.instrumentType !== "ETF",
    ).length,
    etf: stocks.filter((stock) => stock.instrumentType === "ETF").length,
  };

  const tpexValuationDate = payloadDate(
    tpexValuationPayload,
    tpexValuations,
  );
  const tpexInstitutionalDate = payloadDate(
    tpexInstitutionalPayload,
    tpexInstitutional,
  );
  const twseCompanyDate = dateText(pick(twseCompanies[0], "出表日期", "Date"));
  const tpexCompanyDate = dateText(pick(tpexCompanies[0], "Date", "出表日期"));
  const priceDate =
    latestDate(twsePriceDate, tpexPriceDate) ||
    text(edge?.date) ||
    new Date().toISOString().slice(0, 10);
  const bothMarkets = listed.length >= 20 && otc.length >= 20;

  return {
    ...(edge || {}),
    stocks,
    date: priceDate,
    mode: bothMarkets ? "live" : "partial",
    markets: {
      listed: listed.length,
      otc: otc.length,
      fallback: fallbackOnly.length,
    },
    instruments,
    dates: {
      price: {
        twse: twsePriceDate,
        tpex: tpexPriceDate,
        latest: priceDate,
      },
      valuation: {
        twse: twseValuationDate,
        tpex: tpexValuationDate,
        latest: latestDate(twseValuationDate, tpexValuationDate),
      },
      institutional: {
        twse: twseInstitutionalDate,
        tpex: tpexInstitutionalDate,
        latest: latestDate(twseInstitutionalDate, tpexInstitutionalDate),
      },
      margin: {
        twse: twseMarginDate,
        tpex: tpexMarginDate,
        latest: latestDate(twseMarginDate, tpexMarginDate),
      },
      company: {
        twse: twseCompanyDate,
        tpex: tpexCompanyDate,
        latest: latestDate(twseCompanyDate, tpexCompanyDate),
      },
    },
    sourceStatus: {
      price: `TWSE ${twsePriceDate || "日期未提供"} · TPEx ${tpexPriceDate || "日期未提供"}`,
      valuation: `TWSE ${twseValuationDate || "日期未提供"} · TPEx ${tpexValuationDate || "日期未提供"}`,
      company: `MOPS 上市 ${twseCompanies.length} 筆 · 上櫃 ${tpexCompanies.length} 筆`,
      institutional: `TWSE ${twseInstitutionalDate || "日期未提供"} · TPEx ${tpexInstitutionalDate || "日期未提供"}`,
      margin: `TWSE ${twseMarginDate || "日期未提供"} · TPEx ${tpexMarginDate || "日期未提供"}`,
      extended:
        edgeStocks.length >= 20 ? "Supabase Edge 備援已連線" : "官方來源模式",
      risk: riskCoverageComplete
        ? "TWSE／TPEx 處置、注意、變更與停牌名單已核對"
        : "部分風險名單暫時無法核對，正式排名會降低信心",
    },
    riskCoverage: riskSnapshot.coverage || {},
  };
}

function revenueFundamental(row) {
  const symbol = symbolOf(row);
  if (!isCompanySymbol(symbol)) return null;
  // MOPS t187ap05 amount columns are published in NT$ thousands.  FinMind
  // history and the normalized backend tables use NT$; convert at ingestion so
  // a source fallback can never create a 1,000x display/scoring mismatch.
  const amountTwd = (...keys) => {
    const value = numeric(pick(row, ...keys));
    return value == null ? null : value * 1_000;
  };
  const rev = numeric(
    pick(
      row,
      "營業收入-去年同月增減(%)",
      "去年同月增減(%)",
      "去年同月增減百分比",
      "IncreaseDecreasePercentage",
      "YoY",
    ),
  );
  const revYtd = numeric(
    pick(
      row,
      "累計營業收入-前期比較增減(%)",
      "前期比較增減(%)",
      "累計營收前期比較增減(%)",
      "CumulativeIncreaseDecreasePercentage",
      "YTD",
    ),
  );
  return {
    symbol,
    revenue: amountTwd(
        "營業收入-當月營收",
        "當月營收",
        "CurrentMonthRevenue",
        "RevenueCurrentMonth",
    ),
    revenuePreviousMonth: amountTwd(
        "營業收入-上月營收",
        "上月營收",
        "PreviousMonthRevenue",
    ),
    revenueLastYearMonth: amountTwd(
        "營業收入-去年當月營收",
        "去年當月營收",
        "SameMonthLastYearRevenue",
    ),
    revenueYtd: amountTwd(
        "累計營業收入-當月累計營收",
        "當月累計營收",
        "CumulativeRevenueCurrentMonth",
    ),
    revenueLastYearYtd: amountTwd(
        "累計營業收入-去年累計營收",
        "去年累計營收",
        "CumulativeRevenueLastYear",
    ),
    revenueUnit: "TWD",
    rev,
    revMom: numeric(
      pick(
        row,
        "營業收入-上月比較增減(%)",
        "上月比較增減(%)",
        "上月比較增減百分比",
        "PreviousMonthIncreaseDecreasePercentage",
        "MoM",
      ),
    ),
    revYtd,
    revAcceleration:
      rev == null || revYtd == null ? null : Number((rev - revYtd).toFixed(4)),
    revPeriod: periodText(row),
  };
}

function quarterText(row) {
  const year = numeric(pick(row, "年度", "Year"));
  const quarter = numeric(pick(row, "季別", "季", "Quarter", "Season"));
  if (year != null && quarter != null) {
    return `${year < 1911 ? year + 1911 : year} Q${quarter}`;
  }
  return periodText(row);
}

function ratio(amount, base) {
  return amount == null || base == null || base === 0 ? null : (amount / base) * 100;
}

function financialFundamental(row, balance, category) {
  const symbol = symbolOf(row);
  if (!/^\d{4}$/.test(symbol)) return null;
  const directRevenue = numeric(
    pick(row, "營業收入", "營業收入合計", "OperatingRevenue", "收益", "收入"),
  );
  const netInterestIncome = numeric(pick(row, "利息淨收益", "淨利息收入", "NetInterestIncome"));
  const netNonInterestIncome = numeric(pick(row, "利息以外淨收益", "非利息淨收益", "NetNonInterestIncome"));
  const operatingRevenue = directRevenue ??
    (netInterestIncome != null || netNonInterestIncome != null
      ? (netInterestIncome || 0) + (netNonInterestIncome || 0)
      : null);
  const grossProfit = numeric(
    pick(
      row,
      "營業毛利（毛損）淨額",
      "營業毛利（毛損）",
      "營業毛利(毛損)",
      "GrossProfitLoss",
    ),
  );
  const operatingIncome = numeric(
    pick(
      row,
      "營業利益（損失）",
      "營業利益(損失)",
      "營業利益",
      "OperatingIncomeLoss",
    ),
  );
  const netIncome = numeric(
    pick(
      row,
      "本期淨利（淨損）",
      "本期稅後淨利（淨損）",
      "本期稅後純益（純損）",
      "本期稅後淨利(淨損)",
      "ProfitLoss",
    ),
  );
  const assets = numeric(
    pick(balance, "資產總額", "資產總計", "Assets", "TotalAssets"),
  );
  const liabilities = numeric(
    pick(balance, "負債總額", "負債總計", "Liabilities", "TotalLiabilities"),
  );
  const equity = numeric(
    pick(balance, "權益總額", "權益總計", "Equity", "TotalEquity"),
  );
  const quarter = numeric(pick(row, "季別", "季", "Quarter", "Season"));
  const annualizer = quarter && quarter >= 1 && quarter <= 4 ? 4 / quarter : 1;
  const roe = netIncome != null && equity ? (netIncome / equity) * 100 * annualizer : null;
  return {
    symbol,
    quarterRevenue: operatingRevenue == null ? null : operatingRevenue * 1_000,
    quarterRevenueUnit: "TWD",
    quarterRevenuePeriod: quarterText(row),
    eps: numeric(
      pick(
        row,
        "基本每股盈餘（元）",
        "基本每股盈餘",
        "基本每股盈餘(元)",
        "BasicEarningsPerShare",
      ),
    ),
    roe,
    roeEstimated: roe == null ? null : true,
    grossMargin: ratio(grossProfit, operatingRevenue),
    operatingMargin: ratio(operatingIncome, operatingRevenue),
    netMargin: ratio(netIncome, operatingRevenue),
    debt: ratio(liabilities, assets),
    equityRatio: ratio(equity, assets),
    roePeriod: quarterText(row),
    financialFormat: category,
  };
}

function mergeFundamentals(official, edgeRows) {
  const merged = new Map();
  edgeRows.forEach((row) => {
    const symbol = text(row.symbol);
    if (symbol) merged.set(symbol, { ...row, symbol });
  });
  official.forEach((row) => {
    if (!row?.symbol) return;
    const available = Object.fromEntries(
      Object.entries(row).filter(
        ([, value]) => value !== null && value !== undefined && value !== "",
      ),
    );
    merged.set(row.symbol, { ...(merged.get(row.symbol) || {}), ...available });
  });
  return [...merged.values()];
}

async function buildRevenue() {
  const settled = await Promise.allSettled([
    fetchJson(`${TWSE_OPEN}/opendata/t187ap05_L`, 20_000),
    fetchJson(`${TPEX_OPEN}/mopsfin_t187ap05_O`, 20_000),
  ]);
  const listedPayload = fulfilled(settled[0], []);
  const otcPayload = fulfilled(settled[1], []);
  const listed = rows(listedPayload);
  const otc = rows(otcPayload);
  const edge = listed.length < 20 || otc.length < 20
    ? await fetchEdge("?type=revenue", 20_000).catch(() => null)
    : null;
  const edgeRows = edge && Array.isArray(edge.fundamentals) ? edge.fundamentals : [];
  const official = [...listed, ...otc].map(revenueFundamental).filter(Boolean);
  if (official.length < 20 && edgeRows.length < 20) {
    throw new Error("公開資訊觀測站月營收資料暫時無法取得");
  }
  const fundamentals =
    official.length >= 20 ? mergeFundamentals(official, edgeRows) : edgeRows;
  const period =
    fundamentals
      .map((row) => text(row.revPeriod))
      .filter(Boolean)
      .sort()
      .at(-1) || text(edge?.period);
  const listedPublished = payloadDate(listedPayload, listed);
  const otcPublished = payloadDate(otcPayload, otc);
  return {
    ...(edge || {}),
    fundamentals,
    period,
    publishedAt: latestDate(listedPublished, otcPublished),
    dates: {
      period,
      published: {
        twse: listedPublished,
        tpex: otcPublished,
        latest: latestDate(listedPublished, otcPublished),
      },
    },
    source: "MOPS / TWSE / TPEx",
    sourceStatus: {
      listed: settled[0].status === "fulfilled"
        ? `TWSE MOPS 官方 ${listed.length} 筆`
        : `TWSE 來源錯誤：${text(settled[0].reason?.message || settled[0].reason)}`,
      otc: settled[1].status === "fulfilled"
        ? `TPEx MOPS 官方 ${otc.length} 筆`
        : `TPEx 來源錯誤：${text(settled[1].reason?.message || settled[1].reason)}`,
      fallback: edge
        ? `Supabase 備援 ${edgeRows.length} 筆`
        : "官方 L/O 來源已回傳；橫截面未列個股由後端逐檔歷史補齊",
    },
    coverage: {
      listedRows: listed.length,
      otcRows: otc.length,
      fallbackRows: edgeRows.length,
      mergedRows: fundamentals.length,
      failures: settled.filter((entry) => entry.status === "rejected").length,
    },
  };
}

async function buildFinancials() {
  const requests = [];
  for (const category of FINANCIAL_CATEGORIES) {
    requests.push(
      {
        market: "listed",
        statement: "income",
        category,
        promise: fetchJson(
          `${TWSE_OPEN}/opendata/t187ap06_L_${category}`,
          24_000,
        ),
      },
      {
        market: "listed",
        statement: "balance",
        category,
        promise: fetchJson(
          `${TWSE_OPEN}/opendata/t187ap07_L_${category}`,
          24_000,
        ),
      },
      {
        market: "otc",
        statement: "income",
        category,
        promise: fetchJson(
          `${TPEX_OPEN}/mopsfin_t187ap06_O_${category}`,
          24_000,
        ),
      },
      {
        market: "otc",
        statement: "balance",
        category,
        promise: fetchJson(
          `${TPEX_OPEN}/mopsfin_t187ap07_O_${category}`,
          24_000,
        ),
      },
    );
  }
  const settled = await Promise.allSettled(requests.map((request) => request.promise));
  const incomeRows = [];
  const balanceMap = new Map();
  const publicationDates = { listed: [], otc: [] };
  const counts = { listedIncome: 0, listedBalance: 0, otcIncome: 0, otcBalance: 0 };

  requests.forEach((request, index) => {
    const payload = fulfilled(settled[index], []);
    const data = rows(payload).filter((row) => isCompanySymbol(symbolOf(row)));
    const date = payloadDate(payload, data);
    if (date) publicationDates[request.market].push(date);
    if (request.statement === "income") {
      data.forEach((row) => incomeRows.push({ row, category: request.category }));
      counts[request.market === "listed" ? "listedIncome" : "otcIncome"] += data.length;
    } else {
      data.forEach((row) => balanceMap.set(symbolOf(row), row));
      counts[request.market === "listed" ? "listedBalance" : "otcBalance"] += data.length;
    }
  });

  const official = incomeRows
    .map(({ row, category }) =>
      financialFundamental(row, balanceMap.get(symbolOf(row)), category),
    )
    .filter(Boolean);
  const needsFallback = official.length < 20 ||
    counts.listedIncome < 20 || counts.listedBalance < 20 ||
    counts.otcIncome < 20 || counts.otcBalance < 20 ||
    requests.some((_, index) => settled[index].status === "rejected");
  const edge = needsFallback
    ? await fetchEdge("?type=financials", 24_000).catch(() => null)
    : null;
  const edgeRows = edge && Array.isArray(edge.fundamentals) ? edge.fundamentals : [];
  if (official.length < 20 && edgeRows.length < 20) {
    throw new Error("公開資訊觀測站財報資料暫時無法取得");
  }
  const fundamentals =
    official.length >= 20 ? mergeFundamentals(official, edgeRows) : edgeRows;
  const period =
    fundamentals
      .map((row) => text(row.roePeriod))
      .filter(Boolean)
      .sort()
      .at(-1) || text(edge?.period);
  const listedPublished = latestDate(publicationDates.listed);
  const otcPublished = latestDate(publicationDates.otc);
  return {
    ...(edge || {}),
    fundamentals,
    period,
    publishedAt: latestDate(listedPublished, otcPublished),
    dates: {
      period,
      published: {
        twse: listedPublished,
        tpex: otcPublished,
        latest: latestDate(listedPublished, otcPublished),
      },
    },
    source: "MOPS / TWSE / TPEx",
    sourceStatus: {
      listed:
        counts.listedIncome >= 20 && counts.listedBalance >= 20
          ? `TWSE MOPS 六類財報 ${counts.listedIncome} 檔`
          : "備援",
      otc:
        counts.otcIncome >= 20 && counts.otcBalance >= 20
          ? `TPEx MOPS 六類財報 ${counts.otcIncome} 檔`
          : "備援",
      formats: "一般業、金控、銀行、證券、保險及異業",
      failedFormats: requests
        .map((request, index) => settled[index].status === "rejected"
          ? `${request.market}:${request.statement}:${request.category}` : null)
        .filter(Boolean),
      fallback: edge
        ? `Supabase 備援 ${edgeRows.length} 筆`
        : "官方來源覆蓋完整，未呼叫舊備援",
    },
    coverage: { ...counts, mergedRows: fundamentals.length },
  };
}

export function sourcesPayload() {
  return {
    version: VERSION,
    auditedAt: "2026-07-14",
    freshnessPolicy:
      "以各來源實際回傳日期為準；上市行情優先使用指定交易日的 TWSE 盤後介面，OpenAPI 僅作備援。",
    requestPolicy: {
      parallelPerSource: "1–2",
      minimumGap: "1.2–1.8 秒",
      retries: "排程 FinMind 失敗由下一批持久退避；官方全市場來源的逾時、429、5xx 最多即時重試 2 次",
      history: "全市場快照先持久化，再由上市、上櫃、ETF 獨立游標依滑動配額動態批次深度驗證",
    },
    sources: [
      {
        id: "twse",
        name: "臺灣證券交易所盤後介面／OpenAPI／T86",
        coverage: ["上市行情", "估值", "三大法人", "融資融券", "公司資料"],
      },
      {
        id: "tpex",
        name: "證券櫃檯買賣中心 OpenAPI",
        coverage: ["上櫃行情", "估值", "三大法人", "融資融券", "公司資料"],
      },
      {
        id: "mops",
        name: "公開資訊觀測站開放資料",
        coverage: ["上市櫃月營收", "六類綜合損益表", "六類資產負債表"],
      },
      {
        id: "finmind",
        name: "FinMind 台灣市場歷史公開資料",
        coverage: ["250 日價量", "36 月月營收", "12 季財報與現金流", "20 日法人與融資融券"],
      },
      {
        id: "tdcc",
        name: "臺灣集中保管結算所開放資料",
        coverage: ["每週集保戶股權分散", "400 張以上與 10 張以下持股結構"],
      },
      {
        id: "supabase",
        name: "Supabase Postgres 持久化後端",
        coverage: ["歷史日線", "月營收與財務", "法人與融資", "累積排行榜", "同步游標"],
      },
    ],
    failOpen: true,
  };
}

export function healthPayload() {
  return {
    ok: true,
    service: "台股智選",
    version: VERSION,
    integrations: [
      "TWSE 指定交易日盤後資料 / OpenAPI / T86",
      "TPEx OpenAPI",
      "MOPS 六類損益與資產負債資料",
      "FinMind 歷史公開資料",
      "TDCC 集保戶股權分散開放資料",
      "Supabase Postgres 歷史資料與排行榜",
    ],
    markets: ["上市股票", "上櫃股票", "ETF"],
    rankingGroups: {
      listed: "上市股票獨立排名",
      otc: "上櫃股票獨立排名",
      etf: "ETF 獨立排名，不使用公司月營收與 ROE",
    },
  };
}

function jsonResponse(payload, init = {}, cacheSeconds = 0) {
  const headers = new Headers(init.headers || {});
  headers.set("content-type", "application/json; charset=utf-8");
  headers.set("cache-control", "no-store, max-age=0");
  if (cacheSeconds > 0) {
    headers.set(
      "vercel-cdn-cache-control",
      `public, s-maxage=${cacheSeconds}, stale-while-revalidate=${Math.max(cacheSeconds, 600)}`,
    );
  }
  return new Response(JSON.stringify(payload), { ...init, headers });
}

export async function handleMarketData(request, url = new URL(request.url)) {
  const type = url.searchParams.get("type") || "stocks";
  const force = url.searchParams.get("refresh") === "1";
  try {
    if (type === "sources") return jsonResponse(sourcesPayload(), {}, 3_600);
    if (type === "risks") {
      return jsonResponse(await buildRiskSnapshot(), {}, force ? 0 : 600);
    }
    if (type === "benchmarks") {
      return jsonResponse(await buildBenchmarks({ allowFinmind: false }), {}, force ? 0 : 21_600);
    }
    if (type === "etf-profiles") {
      return jsonResponse(await buildEtfProfiles(), {}, force ? 0 : 21_600);
    }
    if (type === "backend-status") {
      return jsonResponse(await readBackendStatus(), {}, force ? 0 : 60);
    }
    if (type === "data-health") {
      return jsonResponse(await readDataHealth(), {}, force ? 0 : 60);
    }
    if (type === "ranking-backtest") {
      return jsonResponse(await readRankingBacktest(), {}, force ? 0 : 300);
    }
    if (type === "backend-rankings") {
      const limit = numeric(url.searchParams.get("limit")) || 100;
      return jsonResponse(await readBackendRankings(limit), {}, force ? 0 : 120);
    }
    if (type === "deep") {
      const symbol = text(url.searchParams.get("symbol"));
      const payload = await readBackendAnalysis(symbol);
      return jsonResponse(payload, {}, force ? 0 : 120);
    }
    if (type === "history") {
      const symbol = text(url.searchParams.get("symbol"));
      const market = text(url.searchParams.get("market")) || "上市";
      const months = Math.max(6, Math.min(24, numeric(url.searchParams.get("months")) || 18));
      let fallback = { ...(await readBackendHistory(symbol, 280)), market };
      let payload;
      try {
        const params = new URLSearchParams({ mode: "history", symbol, months: String(months) });
        const onDemand = await fetchJson(`${SUPABASE_HISTORY_EDGE}?${params}`, 90_000, 0);
        if (onDemand?.pending) {
          return jsonResponse({ ...onDemand, market }, { status: 202 });
        }
        payload = { ...onDemand, market };
      } catch (error) {
        // A fully accumulated database series remains usable if the repair
        // service itself has a transient problem.  Partial histories must not
        // be presented as complete technical data.
        if (fallback.history.length >= 120) payload = fallback;
        else throw error;
      }
      if (!Array.isArray(payload.history)) {
        throw Object.assign(new Error(`${market} ${symbol} 歷史日線回應格式不正確`), {
          status: 503,
          code: "HISTORY_UPSTREAM_ERROR",
        });
      }
      if (payload.history.length < 60) {
        return jsonResponse({
          ...payload,
          mode: "partial",
          code: "HISTORY_INSUFFICIENT",
          error: `${market} ${symbol} 目前只有 ${payload.history.length} 個交易日，未達完整技術面所需 60 日`,
          market,
          symbol,
          count: payload.history.length,
        }, {}, force ? 0 : 3_600);
      }
      return jsonResponse(payload, {}, force ? 0 : 3_600);
    }
    if (type === "revenue") {
      if (!force && revenueCache?.expires > Date.now()) {
        return jsonResponse(revenueCache.payload, {}, 21_600);
      }
      const payload = await buildRevenue();
      revenueCache = { payload, expires: Date.now() + 21_600_000 };
      return jsonResponse(payload, {}, force ? 0 : 21_600);
    }
    if (type === "financials") {
      if (!force && financialCache?.expires > Date.now()) {
        return jsonResponse(financialCache.payload, {}, 21_600);
      }
      const payload = await buildFinancials();
      financialCache = { payload, expires: Date.now() + 21_600_000 };
      return jsonResponse(payload, {}, force ? 0 : 21_600);
    }
    if (type !== "stocks") {
      return jsonResponse({ error: `不支援的資料類型：${type}` }, { status: 400 });
    }
    if (!force && stockCache?.expires > Date.now()) {
      return jsonResponse(stockCache.payload, {}, 120);
    }
    const payload = await buildStocks();
    stockCache = { payload, expires: Date.now() + 120_000 };
    return jsonResponse(payload, {}, force ? 0 : 120);
  } catch (error) {
    console.error("[market-data] request failed", {
      type,
      symbol: text(url.searchParams.get("symbol")) || null,
      error: error instanceof Error ? error.message : String(error),
    });
    const isHistory = type === "history";
    const status = isHistory && [400, 404, 429, 503].includes(Number(error?.status))
      ? Number(error.status)
      : 502;
    return jsonResponse({
      error: error instanceof Error ? error.message : "資料取得失敗",
      ...(error?.code ? { code: error.code } : {}),
      ...(error?.retryAfterAt ? { retryAfterAt: error.retryAfterAt } : {}),
    }, { status });
  }
}
