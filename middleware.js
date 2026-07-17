import { next } from "@vercel/functions";
import {
  MAINTENANCE_RETRY_AFTER_SECONDS,
  maintenanceDocument,
  maintenancePayload,
} from "./src/maintenance-mode.js";

const STATUS_CACHE_MS = 2_500;
const BYPASS_WINDOW_MS = 120_000;
const encoder = new TextEncoder();
let cachedStatus = { expiresAt: 0, value: null };

function enabled(value) {
  return ["1", "true", "on", "enabled"].includes(String(value || "").trim().toLowerCase());
}

function failClosed() {
  const configured = String(process.env.MAINTENANCE_FAIL_CLOSED || "").trim();
  return !["0", "false", "no", "off", "disabled"].includes(configured.toLowerCase());
}

function supabaseHeaders(serviceKey) {
  return {
    apikey: serviceKey,
    ...(!serviceKey.startsWith("sb_secret_") ? { authorization: `Bearer ${serviceKey}` } : {}),
    accept: "application/json",
  };
}

function statusEndpoint() {
  const baseUrl = process.env.MARKET_SUPABASE_URL || process.env.SUPABASE_URL;
  const serviceKey = process.env.MARKET_SUPABASE_SERVICE_ROLE_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!baseUrl || !serviceKey) return null;
  return {
    url: `${baseUrl.replace(/\/$/, "")}/rest/v1/twss_maintenance_control?id=eq.global&select=enabled,phase,reason,generation,updated_at`,
    serviceKey,
  };
}

async function readMaintenanceStatus() {
  if (enabled(process.env.MAINTENANCE_MODE)) {
    return { enabled: true, phase: "maintenance", reason: "forced_by_environment", generation: null };
  }

  const now = Date.now();
  if (cachedStatus.value && cachedStatus.expiresAt > now) return cachedStatus.value;

  const endpoint = statusEndpoint();
  if (!endpoint) {
    return { enabled: failClosed(), phase: "configuration_missing" };
  }

  try {
    const response = await fetch(endpoint.url, {
      headers: supabaseHeaders(endpoint.serviceKey),
      cache: "no-store",
      signal: AbortSignal.timeout(1_500),
    });
    if (!response.ok) throw new Error(`maintenance status ${response.status}`);
    const [row] = await response.json();
    const value = row || { enabled: false, phase: "off" };
    cachedStatus = { value, expiresAt: now + STATUS_CACHE_MS };
    return value;
  } catch (error) {
    console.error("[maintenance-gate] status lookup failed", {
      name: error?.name || "Error",
      message: String(error?.message || error).slice(0, 180),
    });
    return {
      enabled: failClosed(),
      phase: "status_unavailable",
    };
  }
}

async function hmacHex(secret, message) {
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign("HMAC", key, encoder.encode(message));
  return [...new Uint8Array(signature)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function constantTimeTextEqual(left, right) {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) {
    difference |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }
  return difference === 0;
}

async function hasSignedBypass(request, url, state) {
  const secret = process.env.MAINTENANCE_BYPASS_SECRET;
  const timestamp = request.headers.get("x-maintenance-timestamp") || "";
  const supplied = (request.headers.get("x-maintenance-signature") || "").toLowerCase();
  if (!secret || !/^\d{13}$/.test(timestamp) || !/^[a-f0-9]{64}$/.test(supplied)) return false;
  if (Math.abs(Date.now() - Number(timestamp)) > BYPASS_WINDOW_MS) return false;
  const scope = request.headers.get("x-maintenance-scope") || "";
  let message;
  if (scope === "verify-get" && state?.phase === "verifying" && request.method.toUpperCase() === "GET") {
    message = `${timestamp}\nVERIFY\nGET`;
  } else if (["/api/health", "/api/version"].includes(url.pathname)) {
    message = `${timestamp}\n${request.method.toUpperCase()}\n${url.pathname}`;
  } else {
    return false;
  }
  const expected = await hmacHex(secret, message);
  return constantTimeTextEqual(expected, supplied);
}

function maintenanceResponse(request, state, url) {
  const wantsJson = url.pathname.startsWith("/api/")
    || (request.headers.get("accept") || "").includes("application/json");
  const headers = {
    "cache-control": "no-store, no-cache, max-age=0, must-revalidate",
    "retry-after": String(MAINTENANCE_RETRY_AFTER_SECONDS),
    "x-content-type-options": "nosniff",
    "x-maintenance-phase": state.phase || "maintenance",
    "x-robots-tag": "noindex, nofollow",
  };
  if (wantsJson) {
    headers["content-type"] = "application/json; charset=utf-8";
    return new Response(JSON.stringify(maintenancePayload(state)), { status: 503, headers });
  }
  headers["content-type"] = "text/html; charset=utf-8";
  return new Response(maintenanceDocument(state), { status: 503, headers });
}

export default async function maintenanceGate(request) {
  const url = new URL(request.url);
  const state = await readMaintenanceStatus();
  if (!state.enabled || await hasSignedBypass(request, url, state)) return next();
  return maintenanceResponse(request, state, url);
}

export function resetMaintenanceCacheForTest() {
  cachedStatus = { expiresAt: 0, value: null };
}

export const config = { runtime: "edge", matcher: "/:path*" };

export const maintenanceGateInternals = { failClosed, hasSignedBypass, supabaseHeaders };
