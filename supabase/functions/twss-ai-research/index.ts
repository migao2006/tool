// Independent Gemini research layer. It reads the fixed quantitative output
// but never writes to the scoring cache, score history, or ranking engine.
import { GoogleGenAI } from "npm:@google/genai@2.11.0";
// @ts-ignore Shared source is plain ESM so Node tests and Deno use identical rules.
import {
  AI_RESPONSE_JSON_SCHEMA,
  AI_SCHEMA_VERSION,
  DEFAULT_AI_DAILY_LIMIT,
  MAX_AI_DAILY_LIMIT,
  QUANT_ANALYSIS_VERSION,
  buildAiFacts,
  buildAiPrompt,
  normalizeAiAnalysis,
  selectAiCandidates,
  sha256Hex,
} from "../_shared/ai-research.js";

const PROJECT_URL = Deno.env.get("SUPABASE_URL") || "";
const ENV_GEMINI_API_KEY = Deno.env.get("GEMINI_API_KEY") || "";
const GEMINI_MODEL = Deno.env.get("GEMINI_MODEL") || "gemini-3.5-flash";
const CANDIDATE_GROUPS = ["listed", "otc", "etf"] as const;
const configuredLimit = Math.max(1, Math.min(
  MAX_AI_DAILY_LIMIT,
  Number(Deno.env.get("AI_DAILY_LIMIT")) || DEFAULT_AI_DAILY_LIMIT,
));

function adminKey() {
  try {
    const keys = JSON.parse(Deno.env.get("SUPABASE_SECRET_KEYS") || "{}");
    if (keys.default) return String(keys.default);
  } catch {}
  return Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
}

const ADMIN_KEY = adminKey();
const now = () => new Date().toISOString();
const json = (payload: unknown, status = 200) => new Response(JSON.stringify(payload), {
  status,
  headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
});

function safeErrorMessage(error: unknown, secret = "") {
  let message = error instanceof Error ? error.message : String(error);
  if (secret) message = message.split(secret).join("[REDACTED]");
  return message.replace(/([?&](?:key|api_key)=)[^&\s]+/gi, "$1[REDACTED]");
}

async function rest(path: string, options: { method?: string; body?: unknown; prefer?: string } = {}) {
  if (!PROJECT_URL || !ADMIN_KEY) throw new Error("Supabase backend environment is incomplete");
  const headers: Record<string, string> = {
    accept: "application/json",
    "content-type": "application/json",
    apikey: ADMIN_KEY,
  };
  if (!ADMIN_KEY.startsWith("sb_secret_")) headers.authorization = `Bearer ${ADMIN_KEY}`;
  if (options.prefer) headers.prefer = options.prefer;
  const response = await fetch(`${PROJECT_URL}/rest/v1/${path}`, {
    method: options.method || "GET",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  if (!response.ok) throw new Error(`Database ${response.status}: ${(await response.text()).slice(0, 400)}`);
  if (response.status === 204) return { data: null, response };
  const text = await response.text();
  return { data: text ? JSON.parse(text) : null, response };
}

async function verifyRequest(request: Request) {
  const token = request.headers.get("x-twss-sync-token") || "";
  if (!token) return false;
  const { data } = await rest("rpc/twss_verify_sync_token", { method: "POST", body: { p_token: token } });
  return data === true;
}

async function patchState(values: Record<string, unknown>) {
  await rest("stock_sync_state?job_key=eq.ai_research", {
    method: "PATCH",
    body: { ...values, updated_at: now() },
    prefer: "return=minimal",
  });
}

async function claimLease(owner: string) {
  const { data } = await rest("rpc/twss_claim_sync_lease", {
    method: "POST",
    body: { p_job_key: "ai_research", p_owner: owner, p_seconds: 300 },
  });
  return data === true;
}

async function releaseLease(owner: string) {
  await rest("rpc/twss_release_sync_lease", {
    method: "POST",
    body: { p_job_key: "ai_research", p_owner: owner },
  });
}

async function reserveCalls(requested: number) {
  const { data } = await rest("rpc/twss_reserve_ai_calls", {
    method: "POST",
    body: { p_requested: requested, p_daily_limit: configuredLimit },
  });
  return Math.max(0, Math.min(requested, Number(data) || 0));
}

async function finishCalls(completed: number, failed: number) {
  await rest("rpc/twss_finish_ai_calls", {
    method: "POST",
    body: { p_completed: completed, p_failed: failed },
  });
}

async function loadGeminiApiKey() {
  if (ENV_GEMINI_API_KEY.trim()) return ENV_GEMINI_API_KEY.trim();
  const { data } = await rest("rpc/twss_get_gemini_api_key", {
    method: "POST",
    body: {},
  });
  return typeof data === "string" ? data.trim() : "";
}

async function listGeminiModels() {
  const apiKey = await loadGeminiApiKey();
  if (!apiKey) return { configured: false, models: [] as string[] };
  const response = await fetch("https://generativelanguage.googleapis.com/v1beta/models?pageSize=100", {
    headers: { "x-goog-api-key": apiKey, accept: "application/json" },
  });
  if (!response.ok) throw new Error(`Gemini model catalog ${response.status}`);
  const payload = await response.json();
  const models = (Array.isArray(payload?.models) ? payload.models : [])
    .filter((model: Record<string, unknown>) => Array.isArray(model.supportedGenerationMethods) &&
      model.supportedGenerationMethods.includes("generateContent"))
    .map((model: Record<string, unknown>) => String(model.name || "").replace(/^models\//, ""))
    .filter(Boolean)
    .sort();
  return { configured: true, models };
}

async function loadCandidates() {
  const select = encodeURIComponent(
    "symbol,group_name,data_date,analysis_version,score,confidence,official,tier,stock,analysis,result,status",
  );
  const groups = await Promise.all(CANDIDATE_GROUPS.map(async (group) => {
    const params = [
      `select=${select}`,
      `group_name=eq.${group}`,
      "status=eq.ready",
      "official=eq.true",
      `analysis_version=eq.${encodeURIComponent(QUANT_ANALYSIS_VERSION)}`,
      "confidence=gte.70",
      "score=gte.65",
      "order=score.desc,confidence.desc",
      // Eighty candidates per group is ample for a 5/5/2 daily batch while
      // keeping payloads small and preventing one market from starving another.
      "limit=80",
    ].join("&");
    const { data } = await rest(`stock_analysis_cache?${params}`);
    return Array.isArray(data) ? data : [];
  }));
  return groups.flat();
}

async function loadPrevious() {
  const select = encodeURIComponent("symbol,input_hash,model,schema_version,generated_at,expires_at");
  const { data } = await rest(`ai_stock_research?select=${select}&order=generated_at.desc&limit=2000`);
  const previous = new Map<string, Record<string, unknown>>();
  for (const row of Array.isArray(data) ? data : []) {
    if (!previous.has(String(row.symbol))) previous.set(String(row.symbol), row);
  }
  return previous;
}

async function createRun(selectedCount: number) {
  const { data } = await rest("ai_research_runs", {
    method: "POST",
    body: {
      status: "running",
      provider: "google-gemini",
      model: GEMINI_MODEL,
      schema_version: AI_SCHEMA_VERSION,
      selected_count: selectedCount,
      started_at: now(),
    },
    prefer: "return=representation",
  });
  return Array.isArray(data) ? data[0]?.id : null;
}

async function patchRun(id: string | null, values: Record<string, unknown>) {
  if (!id) return;
  await rest(`ai_research_runs?id=eq.${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: values,
    prefer: "return=minimal",
  });
}

async function generateOne(ai: GoogleGenAI, candidate: Record<string, any>) {
  const response = await ai.models.generateContent({
    model: GEMINI_MODEL,
    contents: buildAiPrompt(candidate.facts),
    config: {
      temperature: 0.15,
      maxOutputTokens: 1_500,
      responseMimeType: "application/json",
      responseJsonSchema: AI_RESPONSE_JSON_SCHEMA,
    },
  });
  const raw = String(response.text || "").trim();
  const analysis = normalizeAiAnalysis(JSON.parse(raw.replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "")));
  const selectedReason = "正式候選、資料信心達標且分組排名前段；僅建立獨立 AI 研究摘要";
  await rest("ai_stock_research?on_conflict=symbol,input_hash,model,schema_version", {
    method: "POST",
    body: {
      symbol: candidate.symbol,
      group_name: candidate.group_name,
      data_date: candidate.data_date,
      input_hash: candidate.inputHash,
      provider: "google-gemini",
      model: GEMINI_MODEL,
      schema_version: AI_SCHEMA_VERSION,
      status: "ready",
      selected_reason: selectedReason,
      verdict: analysis.verdict,
      ai_confidence: analysis.aiConfidence,
      analysis,
      input_snapshot: candidate.facts,
      generated_at: now(),
      expires_at: new Date(Date.now() + 14 * 86_400_000).toISOString(),
    },
    prefer: "resolution=merge-duplicates,return=minimal",
  });
  return { symbol: candidate.symbol, verdict: analysis.verdict, confidence: analysis.aiConfidence };
}

async function runBatch(limit: number) {
  const geminiApiKey = await loadGeminiApiKey();
  if (!geminiApiKey) {
    await patchState({
      status: "partial",
      last_error: null,
      details: { version: "16.4-ai2", configured: false, reason: "GEMINI_API_KEY is not configured" },
    });
    return { ok: true, configured: false, generated: 0, message: "Gemini 金鑰尚未設定；原量化系統不受影響" };
  }
  const [rawCandidates, previous] = await Promise.all([loadCandidates(), loadPrevious()]);
  const candidates = await Promise.all(rawCandidates.map(async (row) => {
    const facts = buildAiFacts(row);
    return { ...row, facts, inputHash: await sha256Hex(facts) };
  }));
  const changed = selectAiCandidates(candidates, previous, {
    limit: Math.max(1, Math.min(configuredLimit, limit)),
    model: GEMINI_MODEL,
    schemaVersion: AI_SCHEMA_VERSION,
  });
  if (!changed.length) {
    await patchState({
      status: "success", last_error: null, last_success_at: now(),
      details: { version: "16.4-ai2", configured: true, selected: 0, reason: "no-changed-candidates" },
    });
    return { ok: true, configured: true, selected: 0, generated: 0, skippedUnchanged: true };
  }
  const reserved = await reserveCalls(changed.length);
  const selected = changed.slice(0, reserved);
  if (!selected.length) {
    return { ok: true, configured: true, selected: 0, generated: 0, dailyLimitReached: true };
  }
  const runId = await createRun(selected.length);
  await patchState({
    status: "running", started_at: now(), last_error: null,
    details: { version: "16.4-ai2", configured: true, selected: selected.length, model: GEMINI_MODEL },
  });
  const ai = new GoogleGenAI({ apiKey: geminiApiKey });
  const generated: Record<string, unknown>[] = [];
  const errors: { symbol: string; error: string }[] = [];
  let cursor = 0;
  const workers = Array.from({ length: Math.min(2, selected.length) }, async () => {
    while (cursor < selected.length) {
      const index = cursor++;
      const candidate = selected[index];
      try {
        generated.push(await generateOne(ai, candidate));
      } catch (error) {
        errors.push({
          symbol: String(candidate.symbol),
          error: safeErrorMessage(error, geminiApiKey).slice(0, 300),
        });
      }
    }
  });
  await Promise.all(workers);
  await finishCalls(generated.length, errors.length).catch(() => undefined);
  const status = errors.length ? (generated.length ? "partial" : "error") : "success";
  const finishedAt = now();
  await patchRun(runId, {
    status,
    generated_count: generated.length,
    failed_count: errors.length,
    attempted_count: selected.length,
    details: { symbols: generated.map((item) => item.symbol), failedSymbols: errors.map((item) => item.symbol) },
    last_error: errors.length ? errors.map((item) => `${item.symbol}: ${item.error}`).join(" | ").slice(0, 2000) : null,
    finished_at: finishedAt,
  });
  await patchState({
    status,
    processed_count: generated.length,
    total_items: selected.length,
    last_symbol: String(selected.at(-1)?.symbol || ""),
    last_error: errors.length ? `${errors.length} 檔 AI 摘要失敗，等待下次資料變更後重試` : null,
    last_success_at: generated.length ? finishedAt : null,
    details: {
      version: "16.4-ai2", configured: true, model: GEMINI_MODEL, schemaVersion: AI_SCHEMA_VERSION,
      selected: selected.length, generated: generated.length, failed: errors.length, dailyLimit: configuredLimit,
    },
  });
  return { ok: errors.length === 0, configured: true, selected: selected.length, generated, failed: errors.map((item) => item.symbol) };
}

Deno.serve(async (request) => {
  if (request.method !== "POST") return json({ error: "Method not allowed" }, 405);
  try {
    if (!await verifyRequest(request)) return json({ error: "Unauthorized" }, 401);
    let body: Record<string, unknown> = {};
    try { body = await request.json(); } catch {}
    if (body.mode === "models") return json(await listGeminiModels());
    const requested = Math.max(1, Math.min(configuredLimit, Number(body.limit) || configuredLimit));
    const owner = crypto.randomUUID();
    if (!await claimLease(owner)) return json({ ok: true, skipped: true, reason: "active-lease" });
    try {
      return json(await runBatch(requested));
    } finally {
      await releaseLease(owner).catch(() => undefined);
    }
  } catch (error) {
    const message = safeErrorMessage(error, ENV_GEMINI_API_KEY);
    console.error("[twss-ai-research] batch failed", { error: message });
    await patchState({ status: "error", last_error: message.slice(0, 1000) }).catch(() => undefined);
    return json({ error: "AI 研究批次暫時失敗；原量化結果未受影響" }, 500);
  }
});
