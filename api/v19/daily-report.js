import { parseWatchlist, readDailyMarketReport } from "../../src/daily-market-report.js";
import { handleV19 } from "./_shared.js";

export default {
  fetch(request) {
    return handleV19(request, (url) => readDailyMarketReport({
      watchlist: parseWatchlist(url.searchParams.getAll("watchlist")),
    }));
  },
};
