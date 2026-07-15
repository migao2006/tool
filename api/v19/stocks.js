import { readV19Stock, V19PublicError } from "../../src/v19-backend.js";
import { handleV19 } from "./_shared.js";

export default {
  fetch(request) {
    return handleV19(request, (url) => {
      const pathSymbol = url.pathname.match(/\/api\/v19\/stocks\/([^/]+)$/)?.[1];
      const symbol = url.searchParams.get("symbol") || pathSymbol;
      if (!symbol) throw new V19PublicError("invalid_symbol");
      return readV19Stock(decodeURIComponent(symbol));
    });
  },
};
