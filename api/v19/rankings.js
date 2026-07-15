import { readV19Rankings } from "../../src/v19-backend.js";
import { handleV19 } from "./_shared.js";

export default {
  fetch(request) {
    return handleV19(request, (url) => readV19Rankings(url));
  },
};
