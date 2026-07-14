import { handleMarketData } from "../src/market-data.js";

export default {
  async fetch(request) {
    return handleMarketData(request, new URL(request.url));
  },
};
