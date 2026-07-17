import { constantTimeSecretEqual } from "../../src/internal-auth.js";
import { readV20Market, V20PublicError } from "../../src/v20-backend.js";
import { handleV20 } from "./_shared.js";

export default {
  fetch(request) {
    const requestUrl = new URL(request.url);
    const refreshRequested = requestUrl.searchParams.get("refresh") === "global";
    if (!refreshRequested) return handleV20(request, () => readV20Market());

    return handleV20(request, async () => {
      const internalKey = String(globalThis.process?.env?.TWSS_V20_INTERNAL_KEY || "").trim();
      const suppliedKey = request.headers.get("x-twss-internal-key") || "";
      if (!await constantTimeSecretEqual(suppliedKey, internalKey)) {
        throw new V20PublicError("refresh_forbidden", 403);
      }
      return readV20Market({
        refreshGlobal: true,
        persistenceToken: internalKey,
      });
    }, { methods: ["POST"], allowHeaders: ["content-type", "x-twss-internal-key"] });
  },
};
