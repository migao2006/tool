const COMMANDS = new Set(["status", "enter", "verify", "reclose", "resume"]);
const command = String(process.argv[2] || "status").trim().toLowerCase();
const confirmed = process.argv.includes("--confirm");

if (!COMMANDS.has(command)) {
  throw new Error("usage: maintenance-control.mjs status|enter|verify|reclose|resume [--confirm]");
}
if (command !== "status" && !confirmed) {
  throw new Error(`refusing maintenance ${command} without --confirm`);
}

const baseUrl = String(process.env.MARKET_SUPABASE_URL || process.env.SUPABASE_URL || "")
  .trim()
  .replace(/\/$/, "");
const serviceKey = String(
  process.env.MARKET_SUPABASE_SERVICE_ROLE_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY || "",
).trim();
const actor = String(process.env.MAINTENANCE_ACTOR || "codex-release").trim().slice(0, 120);
const reason = String(process.env.MAINTENANCE_REASON || "planned verified release").trim().slice(0, 500);

if (!/^https:\/\/[a-z0-9-]+\.supabase\.co$/i.test(baseUrl) || !serviceKey) {
  throw new Error("MARKET Supabase URL and service-role key are required");
}

const headers = {
  apikey: serviceKey,
  ...(!serviceKey.startsWith("sb_secret_") ? { authorization: `Bearer ${serviceKey}` } : {}),
  accept: "application/json",
  "content-type": "application/json",
};

async function request(path, options = {}) {
  const response = await fetch(`${baseUrl}${path}`, {
    ...options,
    headers: { ...headers, ...(options.headers || {}) },
    cache: "no-store",
    signal: AbortSignal.timeout(10_000),
  });
  const text = await response.text();
  let payload = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = text.slice(0, 300);
  }
  if (!response.ok) {
    const message = payload?.message || payload?.error || `HTTP ${response.status}`;
    throw new Error(`maintenance ${command} failed: ${String(message).slice(0, 300)}`);
  }
  return payload;
}

async function rpc(name, body) {
  const rows = await request(`/rest/v1/rpc/${name}`, {
    method: "POST",
    body: JSON.stringify(body),
  });
  return Array.isArray(rows) ? rows[0] : rows;
}

async function readStatus() {
  const rows = await request(
    "/rest/v1/twss_maintenance_control?id=eq.global&select=enabled,phase,reason,actor,generation,enabled_at,updated_at",
    { method: "GET" },
  );
  return Array.isArray(rows) ? rows[0] || null : rows;
}

let state;
if (command === "status") {
  state = await readStatus();
} else if (command === "enter") {
  await rpc("twss_maintenance_enable_web", { p_reason: reason, p_actor: actor });
  await new Promise((resolve) => setTimeout(resolve, 3_000));
  state = await rpc("twss_maintenance_pause_jobs", { p_actor: actor });
} else if (command === "verify") {
  // Capture and pause cron jobs created or replaced by the deployment while the
  // original snapshot remains authoritative for pre-existing job IDs.
  await rpc("twss_maintenance_pause_jobs", { p_actor: actor });
  state = await rpc("twss_maintenance_open_web", { p_actor: actor });
} else if (command === "reclose") {
  state = await rpc("twss_maintenance_reclose_web", { p_reason: reason, p_actor: actor });
} else if (command === "resume") {
  state = await rpc("twss_maintenance_resume_jobs", { p_actor: actor });
}

const safeState = state && typeof state === "object"
  ? {
      enabled: state.enabled === true,
      phase: state.phase || null,
      reason: state.reason || null,
      actor: state.actor || null,
      generation: Number.isFinite(Number(state.generation)) ? Number(state.generation) : null,
      enabledAt: state.enabled_at || null,
      updatedAt: state.updated_at || null,
    }
  : null;

console.log(JSON.stringify({ command, state: safeState }, null, 2));
