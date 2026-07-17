const finitePositive = (value) => Number.isFinite(Number(value)) && Number(value) > 0;

export const V20_TURNOVER_BASELINE_MINIMUM_SESSIONS = 5;
export const V20_TURNOVER_HISTORY_PAGE_SIZE = 1_000;
export const V20_TURNOVER_HISTORY_MAX_ROWS = 12_000;
export const V20_TURNOVER_HISTORY_MINIMUM_SYMBOLS = 500;
export const V20_TURNOVER_HISTORY_RELATIVE_COVERAGE = 0.65;

export function historicalTurnoverContexts(rows, {
  sourceExhausted = false,
  minimumSymbols = V20_TURNOVER_HISTORY_MINIMUM_SYMBOLS,
  relativeCoverage = V20_TURNOVER_HISTORY_RELATIVE_COVERAGE,
  maximumSessions = 20,
} = {}) {
  const daily = new Map();
  for (const row of Array.isArray(rows) ? rows : []) {
    const dataDate = String(row?.trade_date || "").slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(dataDate) || !finitePositive(row?.trade_value)) continue;
    const current = daily.get(dataDate) || { turnover: 0, symbols: 0 };
    current.turnover += Number(row.trade_value);
    current.symbols += 1;
    daily.set(dataDate, current);
  }

  const dates = [...daily.keys()].sort((left, right) => right.localeCompare(left));
  // A Range page can end in the middle of the oldest observed date. Unless
  // PostgREST confirmed exhaustion, discard that boundary date.
  const completeDates = sourceExhausted ? dates : dates.slice(0, -1);
  const maximumCoverage = completeDates.reduce(
    (maximum, dataDate) => Math.max(maximum, daily.get(dataDate)?.symbols || 0),
    0,
  );
  const coverageFloor = Math.max(
    Math.max(1, Number(minimumSymbols) || V20_TURNOVER_HISTORY_MINIMUM_SYMBOLS),
    Math.floor(maximumCoverage * Math.max(0, Math.min(1, Number(relativeCoverage) || 0))),
  );

  return completeDates
    .filter((dataDate) => {
      const value = daily.get(dataDate);
      return value?.symbols >= coverageFloor && finitePositive(value?.turnover);
    })
    .slice(0, Math.max(1, Math.min(20, Number(maximumSessions) || 20)))
    .map((dataDate) => {
      const value = daily.get(dataDate);
      return {
        data_date: dataDate,
        model_version: "stock-price-history-turnover-v1",
        breadth: {
          all: {
            turnover: Math.round(value.turnover),
            turnoverSymbolCount: value.symbols,
            turnoverScope: "twse_tpex_stocks_excluding_etf",
            turnoverSource: "stock_price_history",
          },
        },
      };
    });
}
