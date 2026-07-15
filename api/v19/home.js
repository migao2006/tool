import { readV19Home } from "../../src/v19-backend.js";
import { handleV19 } from "./_shared.js";

export default {
  fetch(request) {
    return handleV19(request, () => readV19Home());
  },
};
