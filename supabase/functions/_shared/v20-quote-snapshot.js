function number(value) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function quoteSnapshotForCacheRow(row = {}) {
  const stock = row?.stock || {};
  const tradeDate = String(stock.priceDate || "").slice(0, 10);
  const dataDate = String(row.data_date || "").slice(0, 10);
  const close = number(stock.close);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(tradeDate) || tradeDate !== dataDate || close === null || close <= 0) {
    throw new Error("v20_verified_quote_required");
  }
  const open = number(stock.open);
  const high = number(stock.high);
  const low = number(stock.low);
  if (
    high !== null && (high < close || (open !== null && high < open))
    || low !== null && (low > close || (open !== null && low > open))
    || high !== null && low !== null && high < low
  ) {
    throw new Error("v20_verified_quote_ohlc_invalid");
  }
  const source = String(stock.quoteSource || "stock_analysis_cache").trim();
  if (!source) throw new Error("v20_verified_quote_source_required");
  return {
    tradeDate,
    close,
    change: number(stock.change),
    open,
    high,
    low,
    volume: number(stock.volume),
    value: number(stock.value),
    source,
  };
}

export function attachQuoteSnapshot(signals = [], row = {}) {
  const quoteSnapshot = quoteSnapshotForCacheRow(row);
  return signals.map((signal) => {
    if (String(signal?.signal_date || "").slice(0, 10) !== quoteSnapshot.tradeDate) {
      throw new Error("v20_signal_quote_date_mismatch");
    }
    return {
      ...signal,
      gate_results: {
        ...(signal?.gate_results || {}),
        quoteSnapshot: { ...quoteSnapshot },
      },
    };
  });
}
