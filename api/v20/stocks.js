import { readV20Stock, V20PublicError } from "../../src/v20-backend.js";
import { handleV20 } from "./_shared.js";

export default {
  fetch(request) {
    return handleV20(request, (url) => {
      const pathSymbol = url.pathname.match(/\/api\/v20\/stocks\/([^/]+)$/)?.[1];
      const symbol = url.searchParams.get("symbol") || pathSymbol;
      if (!symbol) throw new V20PublicError("invalid_symbol");
      return readV20Stock(decodeURIComponent(symbol));
    });
  },
};
