import { readV20Backtest } from "../../src/v20-backend.js";
import { handleV20 } from "./_shared.js";

export default {
  fetch(request) {
    return handleV20(request, (url) => readV20Backtest(url));
  },
};
