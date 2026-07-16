import { readV20Market } from "../../src/v20-backend.js";
import { handleV20 } from "./_shared.js";

export default {
  fetch(request) {
    const internalKey = String(globalThis.process?.env?.TWSS_V20_INTERNAL_KEY || "");
    const authorizedRefresh = Boolean(internalKey) &&
      request.headers.get("x-twss-internal-key") === internalKey;
    return handleV20(request, (url) => readV20Market({
      refreshGlobal: authorizedRefresh && url.searchParams.get("refresh") === "global",
    }));
  },
};
