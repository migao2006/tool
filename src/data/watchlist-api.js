import { publicConfig } from "../core/public-config.js?v=api-3";
import { normalizeMarketScope } from "../core/market-scope.js";
import { PredictionApiError, requestPredictionApi } from "./api-client.js?v=api-4";
import { readSupabaseAccessToken } from "./session-token.js?v=api-4";

export async function setWatchlistMembership({
  symbol,
  market,
  selected,
  signal,
  config = publicConfig,
}) {
  const normalizedSymbol = String(symbol ?? "").trim().toUpperCase();
  if (!/^[0-9A-Z.-]{1,20}$/u.test(normalizedSymbol)) {
    throw new PredictionApiError("WATCHLIST_SYMBOL_INVALID", "自選股代號格式不正確。");
  }
  const normalizedMarket = normalizeMarketScope(market);
  let token;
  try {
    token = await readSupabaseAccessToken(config);
  } catch (error) {
    throw new PredictionApiError(
      "WATCHLIST_AUTH_UNAVAILABLE",
      "目前無法確認登入狀態，請稍後再試。",
      { cause: error },
    );
  }
  if (!token) {
    throw new PredictionApiError("WATCHLIST_AUTH_REQUIRED", "請先登入後再修改自選股。");
  }
  return requestPredictionApi(
    `watchlist/${normalizedMarket}/${encodeURIComponent(normalizedSymbol)}`,
    {
      method: selected ? "PUT" : "DELETE",
      body: selected
        ? { market: normalizedMarket, symbol: normalizedSymbol }
        : undefined,
      accessToken: token,
      signal,
      config,
    },
  );
}
