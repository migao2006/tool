import { healthPayload } from "../src/market-data.js";

export default {
  fetch() {
    return Response.json(healthPayload(), {
      headers: { "cache-control": "no-store, max-age=0" },
    });
  },
};
