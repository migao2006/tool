import { createHmac } from "node:crypto";

const scope = String(process.argv[2] || "verify").trim().toLowerCase();
const secret = String(process.env.MAINTENANCE_BYPASS_SECRET || "");
if (secret.length < 32) throw new Error("MAINTENANCE_BYPASS_SECRET must contain at least 32 characters");

const timestamp = String(Date.now());
let message;
let headers;

if (scope === "verify") {
  message = `${timestamp}\nVERIFY\nGET`;
  headers = { "x-maintenance-scope": "verify-get" };
} else if (scope === "health" || scope === "version") {
  const path = scope === "health" ? "/api/health" : "/api/version";
  message = `${timestamp}\nGET\n${path}`;
  headers = {};
} else {
  throw new Error("usage: maintenance-signature.mjs verify|health|version");
}

const signature = createHmac("sha256", secret).update(message).digest("hex");
console.log(JSON.stringify({
  expiresInSeconds: 120,
  headers: {
    ...headers,
    "x-maintenance-timestamp": timestamp,
    "x-maintenance-signature": signature,
  },
}, null, 2));
