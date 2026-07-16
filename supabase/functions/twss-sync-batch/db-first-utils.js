const finite = (value) => value != null && Number.isFinite(Number(value));

const validDate = (value) => /^\d{4}-\d{2}-\d{2}$/.test(String(value || ""));

const toNumber = (value) => finite(value) ? Number(value) : null;

const toInteger = (value) => finite(value) ? Math.round(Number(value)) : null;

function marketDate(dates, dataset, group) {
  const market = group === "otc" ? "tpex" : "twse";
  const date = dates?.[dataset]?.[market];
  return validDate(date) ? String(date) : null;
}

/**
 * Convert the official daily cross-section into the normalized histories used
 * by the analysis worker.  Dates deliberately come from each upstream feed;
 * institutional/margin rows must never inherit the price date.
 */
export function officialHistoryRows(stocks, dates, updatedAt, groupForStock) {
  const priceRows = [];
  const institutionalRows = [];
  const marginRows = [];
  const sourceDatesBySymbol = {};

  for (const stock of stocks || []) {
    const symbol = String(stock?.symbol || "");
    if (!symbol) continue;
    const group = groupForStock(stock);
    const priceDate = marketDate(dates, "price", group);
    const institutionalDate = marketDate(dates, "institutional", group);
    const marginDate = marketDate(dates, "margin", group);
    sourceDatesBySymbol[symbol] = {
      price: priceDate,
      institutional: institutionalDate,
      margin: marginDate,
    };

    if (priceDate && finite(stock.close)) {
      priceRows.push({
        symbol,
        trade_date: priceDate,
        open: toNumber(stock.open) ?? Number(stock.close),
        high: toNumber(stock.high) ?? Number(stock.close),
        low: toNumber(stock.low) ?? Number(stock.close),
        close: Number(stock.close),
        volume: toNumber(stock.volume),
        trade_value: toNumber(stock.value),
        transactions: toInteger(stock.transactions),
        source: group === "otc" ? "TPEx official daily snapshot" : "TWSE official daily snapshot",
        updated_at: updatedAt,
      });
    }

    if (institutionalDate && [stock.foreign, stock.trust, stock.dealer, stock.inst].some(finite)) {
      institutionalRows.push({
        symbol,
        trade_date: institutionalDate,
        foreign_net: toNumber(stock.foreign),
        trust_net: toNumber(stock.trust),
        dealer_net: toNumber(stock.dealer),
        institutional_net: toNumber(stock.inst),
        volume_intensity: finite(stock.inst) && finite(stock.volume) && Number(stock.volume) !== 0
          ? Number(((Number(stock.inst) / Number(stock.volume)) * 100).toFixed(4))
          : null,
        source: group === "otc" ? "TPEx official institutional snapshot" : "TWSE official institutional snapshot",
        updated_at: updatedAt,
      });
    }

    if (marginDate && [stock.marginBalance, stock.shortBalance].some(finite)) {
      marginRows.push({
        symbol,
        trade_date: marginDate,
        margin_balance: toNumber(stock.marginBalance),
        short_balance: toNumber(stock.shortBalance),
        source: group === "otc" ? "TPEx official margin snapshot" : "TWSE official margin snapshot",
        updated_at: updatedAt,
      });
    }
  }

  return { priceRows, institutionalRows, marginRows, sourceDatesBySymbol };
}

function queueRow(stock, group, dataDate, datasetKey, priority, reason) {
  return {
    symbol: String(stock.symbol),
    data_date: dataDate,
    group_name: group,
    dataset_key: datasetKey,
    priority,
    status: "pending",
    attempt_count: 0,
    max_attempts: 12,
    next_retry_at: null,
    source_date: null,
    details: { reason, phase: "background-enrichment" },
    error_kind: null,
    last_error: null,
  };
}

/** Build one idempotent daily enrichment task per missing dataset/symbol. */
export function enrichmentQueueRows({
  stocks,
  groupDates,
  sourceDatesBySymbol,
  expectedRevenuePeriod,
  expectedFinancialPeriod,
  groupForStock,
  isEligible,
}) {
  const rows = [];
  for (const stock of stocks || []) {
    const group = groupForStock(stock);
    if (!isEligible(stock, group)) continue;
    const dataDate = groupDates?.[group];
    if (!validDate(dataDate)) continue;
    const dates = sourceDatesBySymbol?.[String(stock.symbol)] || {};
    const company = group !== "etf";

    // Lending has no complete official cross-section.  Refresh every eligible
    // company daily, but keep it outside the base-publication critical path.
    if (company) rows.push(queueRow(stock, group, dataDate, "lending", 20, "daily-lending-refresh"));

    if (!dates.price || !finite(stock.close)) {
      rows.push(queueRow(stock, group, dataDate, "price", 110, "official-price-gap"));
    }
    if (company && (
      !dates.institutional || dates.institutional < dataDate ||
      ![stock.foreign, stock.trust, stock.dealer, stock.inst].some(finite)
    )) {
      rows.push(queueRow(stock, group, dataDate, "institutional", 100, "official-institutional-gap"));
    }
    if (company && (
      !dates.margin || dates.margin < dataDate ||
      ![stock.marginBalance, stock.shortBalance].some(finite)
    )) {
      rows.push(queueRow(stock, group, dataDate, "margin", 95, "official-margin-gap"));
    }
    if (company && (!finite(stock.revenue) || (
      expectedRevenuePeriod && String(stock.revPeriod || "") < String(expectedRevenuePeriod)
    ))) {
      rows.push(queueRow(stock, group, dataDate, "revenue", 90, "missing-or-stale-revenue-period"));
    }
    if (company && (
      (expectedFinancialPeriod && String(stock.roePeriod || "") < String(expectedFinancialPeriod)) ||
      ![stock.roe, stock.eps, stock.quarterRevenue].some(finite)
    )) {
      rows.push(queueRow(stock, group, dataDate, "financial", 85, "missing-or-stale-financial-period"));
    }
  }
  return rows;
}

export function finmindJobCost(datasetKey) {
  return datasetKey === "financial" ? 3 : 1;
}

/** Never replace an already aligned stored trading day with an older feed. */
export function hasUniverseDateRegression(groupDates, storedAlignedDate) {
  if (!validDate(storedAlignedDate)) return false;
  return ["listed", "otc", "etf"].some((group) => {
    const fetched = groupDates?.[group];
    return !validDate(fetched) || String(fetched) < String(storedAlignedDate);
  });
}

function isoDate(value) {
  const raw = String(value || "").trim().replaceAll("/", "").replaceAll("-", "");
  if (/^\d{8}$/.test(raw)) return `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`;
  if (/^\d{7}$/.test(raw)) return `${Number(raw.slice(0, 3)) + 1911}-${raw.slice(3, 5)}-${raw.slice(5, 7)}`;
  return String(value || "").slice(0, 10);
}

export function normalizeLendingRows(symbol, rows, updatedAt) {
  const byDate = new Map();
  for (const row of rows || []) {
    const tradeDate = isoDate(row.date);
    if (!validDate(tradeDate)) continue;
    const numericKeys = Object.keys(row || {}).filter((key) => /volume|balance|quantity|shares/i.test(key));
    const lendingValue = numericKeys.reduce(
      (total, key) => total + (finite(row[key]) ? Number(row[key]) : 0),
      0,
    );
    const existing = byDate.get(tradeDate) || { value: 0, raw: [] };
    existing.value += lendingValue;
    existing.raw.push(row);
    byDate.set(tradeDate, existing);
  }
  return [...byDate.entries()].sort(([left], [right]) => left.localeCompare(right)).map(([tradeDate, value]) => ({
      symbol,
      trade_date: tradeDate,
      lending_value: value.value,
      source: "FinMind TaiwanStockSecuritiesLending",
      raw_data: value.raw.length === 1 ? value.raw[0] : { rows: value.raw },
      updated_at: updatedAt,
    }));
}

export const dbFirstInternals = { validDate, marketDate };
