export const MARKET_SCOPES = Object.freeze(["TWSE", "TPEX"]);
export const DEFAULT_MARKET_SCOPE = "TWSE";

export function normalizeMarketScope(value = DEFAULT_MARKET_SCOPE) {
  const scope = String(value ?? DEFAULT_MARKET_SCOPE).trim().toUpperCase();
  if (!MARKET_SCOPES.includes(scope)) {
    throw new RangeError(`不支援的市場：${value}`);
  }
  return scope;
}

export function marketScopeLabel(value) {
  return normalizeMarketScope(value) === "TWSE" ? "上市" : "上櫃";
}

export function createStockKey({ market, symbol }) {
  const scope = normalizeMarketScope(market);
  const normalizedSymbol = String(symbol ?? "").trim().toUpperCase();
  if (!/^[0-9A-Z.-]{1,20}$/u.test(normalizedSymbol)) {
    throw new RangeError("股票代號格式不正確。");
  }
  return `${scope}:${normalizedSymbol}`;
}

export function stockRoutePath(stockKey) {
  const [market, symbol, ...rest] = String(stockKey ?? "").split(":");
  if (rest.length || !market || !symbol) throw new RangeError("股票識別格式不正確。");
  return `stock/${normalizeMarketScope(market)}/${encodeURIComponent(symbol)}`;
}

export function stockKeyFromRoute(market, encodedSymbol) {
  return createStockKey({
    market,
    symbol: decodeURIComponent(String(encodedSymbol ?? "")),
  });
}
