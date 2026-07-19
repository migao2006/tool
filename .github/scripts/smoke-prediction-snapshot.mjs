const required = [
  "SUPABASE_PROJECT_REF",
  "SUPABASE_URL",
  "PREDICTION_ALLOWED_ORIGINS",
];

for (const name of required) {
  if (!process.env[name]?.trim()) {
    throw new Error(`${name} is required`);
  }
}

const projectRef = process.env.SUPABASE_PROJECT_REF.trim();
const configuredUrl = new URL(process.env.SUPABASE_URL.trim());
const expectedOrigin = `https://${projectRef}.supabase.co`;
if (configuredUrl.origin !== expectedOrigin || configuredUrl.pathname !== "/") {
  throw new Error("SUPABASE_URL does not match SUPABASE_PROJECT_REF");
}

const allowedOrigins = process.env.PREDICTION_ALLOWED_ORIGINS.split(",")
  .map((value) => value.trim())
  .filter(Boolean);
if (!allowedOrigins.length) {
  throw new Error("At least one UI origin is required");
}
for (const origin of allowedOrigins) {
  const parsed = new URL(origin);
  if (parsed.origin !== origin) {
    throw new Error("Every allowed UI origin must be an exact origin");
  }
}

const uiOrigin = allowedOrigins[0];
const response = await fetch(
  `${expectedOrigin}/functions/v1/prediction-snapshot?horizon=5`,
  {
    headers: {
      Accept: "application/json",
      Origin: uiOrigin,
      "X-Alpha-Lens-Contract": "prediction-snapshot.v1",
    },
  },
);
if (!response.ok) {
  throw new Error(`Prediction snapshot smoke test returned ${response.status}`);
}
if (response.headers.get("access-control-allow-origin") !== uiOrigin) {
  throw new Error("Prediction snapshot CORS allowlist did not accept the UI origin");
}
if (
  response.headers.get("x-alpha-lens-contract") !== "prediction-snapshot.v1"
) {
  throw new Error("Prediction snapshot response contract header is invalid");
}

const payload = await response.json();
const validStatus = ["PASS", "RESEARCH_ONLY", "FAIL"].includes(
  payload.system_status,
);
if (
  payload.api_contract_version !== "prediction-snapshot.v1" ||
  payload.horizon !== 5 ||
  !validStatus ||
  !Array.isArray(payload.predictions) ||
  !Array.isArray(payload.excluded)
) {
  throw new Error("Response does not satisfy prediction-snapshot.v1");
}

console.log("prediction-snapshot.v1 smoke test passed");
