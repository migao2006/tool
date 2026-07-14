import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import {
  AI_SCHEMA_VERSION,
  QUANT_ANALYSIS_VERSION,
  allocateGroupQuotas,
  buildAiFacts,
  buildAiPrompt,
  canonicalStringify,
  normalizeAiAnalysis,
  selectAiCandidates,
  sha256Hex,
} from "../supabase/functions/_shared/ai-research.js";

const candidate = (symbol, group, score = 80, overrides = {}) => ({
  symbol,
  group_name: group,
  data_date: "2026-07-14",
  analysis_version: QUANT_ANALYSIS_VERSION,
  score,
  confidence: 90,
  official: true,
  tier: "正式候選",
  status: "ready",
  stock: { symbol, name: `測試${symbol}`, market: group === "otc" ? "上櫃" : "上市", close: 100, change: 1.2, rev: 18 },
  analysis: { revenue: { avg3Yoy: 15 }, price: { return20: 8, volumeRatio: 1.4 } },
  result: { score, confidence: 90, official: true, categories: [{ key: "growth", label: "營收與獲利成長", score: 82, weight: 30, coverage: 95 }] },
  inputHash: symbol.padEnd(64, "0").slice(0, 64),
  ...overrides,
});

assert.deepEqual(allocateGroupQuotas(12), { listed: 5, otc: 5, etf: 2 });
assert.equal(Object.values(allocateGroupQuotas(6)).reduce((sum, value) => sum + value, 0), 6);

const rows = [
  ...Array.from({ length: 8 }, (_, index) => candidate(String(1101 + index), "listed", 95 - index)),
  ...Array.from({ length: 8 }, (_, index) => candidate(String(4101 + index), "otc", 94 - index)),
  ...Array.from({ length: 4 }, (_, index) => candidate(`00${50 + index}`, "etf", 90 - index)),
  candidate("9999", "listed", 99, { official: false }),
  candidate("9998", "listed", 99, { confidence: 69 }),
  candidate("9997", "listed", 64),
];
const selected = selectAiCandidates(rows, new Map(), { limit: 12, model: "gemini-2.5-flash" });
assert.equal(selected.length, 12);
assert.deepEqual(Object.fromEntries(["listed", "otc", "etf"].map((group) => [
  group, selected.filter((row) => row.group_name === group).length,
])), { listed: 5, otc: 5, etf: 2 });
assert.equal(selected.some((row) => ["9999", "9998", "9997"].includes(row.symbol)), false);

const previous = new Map([[selected[0].symbol, {
  input_hash: selected[0].inputHash,
  model: "gemini-2.5-flash",
  schema_version: AI_SCHEMA_VERSION,
}]]);
const withoutUnchanged = selectAiCandidates(rows, previous, { limit: 12, model: "gemini-2.5-flash" });
assert.equal(withoutUnchanged.some((row) => row.symbol === selected[0].symbol), false, "unchanged model input must cost zero calls");

const expiredPrevious = new Map([[selected[0].symbol, {
  input_hash: selected[0].inputHash,
  model: "gemini-2.5-flash",
  schema_version: AI_SCHEMA_VERSION,
  expires_at: "2026-07-01T00:00:00Z",
}]]);
const withExpired = selectAiCandidates(rows, expiredPrevious, {
  limit: 12,
  model: "gemini-2.5-flash",
  now: "2026-07-14T00:00:00Z",
});
assert.equal(withExpired.some((row) => row.symbol === selected[0].symbol), true, "expired reports must be regenerated even when input is unchanged");

const facts = buildAiFacts(rows[0]);
assert.equal(facts.quantitativeResultReadOnly.score, rows[0].score);
assert.equal(facts.identity.group, "listed");
assert.equal(await sha256Hex(facts), await sha256Hex(JSON.parse(canonicalStringify(facts))));
const prompt = buildAiPrompt(facts);
assert.match(prompt, /不得覆寫、重算/);
assert.match(prompt, /不得給出買進、賣出/);
assert.match(buildAiPrompt(buildAiFacts(rows.find((row) => row.group_name === "etf"))), /這是 ETF/);

const mappedFacts = buildAiFacts(candidate("6488", "otc", 80, {
  stock: { symbol: "6488", name: "測試", pe: 18, pb: 2.1, yield: 3.2 },
  analysis: {
    revenue: { new12MonthHigh: true, sameMonthRecord: false, seasonalGrowth: 12.5 },
    financial: { inventoryYoy: 8, receivablesYoy: 6, ttmOperatingCashFlow: 123 },
    institutional: { dealer5: 9, inst20: 30, intensity5: 2.5 },
    margin: { shortChange20: -4 },
    lending: { latest: 12, total20: 240 },
    holdings: { date: "2026-07-10", large400Ratio: 62, retail10Ratio: 18, holders: 12000 },
    price: { ma20Slope5: 1.2, ma60Slope5: 0.8, relative20: 5, jumpAnomaly: false },
    valuation: { pePercentile: 40 },
  },
}));
assert.equal(mappedFacts.growth.new12MonthHigh, true);
assert.equal(mappedFacts.financialQuality.inventoryYoy, 8);
assert.equal(mappedFacts.capitalFlow.lending.total20, 240);
assert.equal(mappedFacts.capitalFlow.holdings.large400Ratio, 62);
assert.equal(mappedFacts.technicalAndRelativeStrength.ma20Slope5, 1.2);
assert.equal(mappedFacts.valuation.pe, 18, "snapshot valuation must survive when analysis only has percentiles");
assert.equal(mappedFacts.valuation.pePercentile, 40);

const normalized = normalizeAiAnalysis({
  verdict: "偏多觀察",
  horizon: "1–8週",
  summary: "營收與價量互相印證，但仍須留意短線過熱。",
  positives: [{ title: "營運轉強", evidence: "近三月營收年增維持正值。" }],
  risks: [{ title: "追價風險", evidence: "股價可能偏離短期均線。" }],
  scenarios: {
    bullish: { condition: "量價續強", observation: "觀察突破能否站穩" },
    neutral: { condition: "量縮整理", observation: "觀察支撐區" },
    bearish: { condition: "跌破支撐", observation: "風險升高" },
  },
  watchItems: ["下月營收"],
  dataWarnings: ["未提供外部新聞"],
  aiConfidence: 76.4,
});
assert.equal(normalized.aiConfidence, 76);
assert.throws(() => normalizeAiAnalysis({ verdict: "強力買進" }), /觀察結論/);

const [edge, migration, vaultMigration, opportunityEngine, deepData] = await Promise.all([
  readFile(new URL("../supabase/functions/twss-ai-research/index.ts", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260714213000_add_independent_ai_research.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260715060000_add_vault_gemini_secret_reader.sql", import.meta.url), "utf8"),
  readFile(new URL("../src/opportunity-engine.js", import.meta.url)),
  readFile(new URL("../src/deep-data.js", import.meta.url)),
]);
assert.match(edge, /GEMINI_API_KEY/);
assert.match(edge, /GEMINI_MODEL.*gemini-3\.5-flash/);
assert.match(edge, /rpc\/twss_get_gemini_api_key/);
assert.match(edge, /safeErrorMessage\(error, geminiApiKey\)/);
assert.match(edge, /\[REDACTED\]/);
assert.match(edge, /x-goog-api-key/);
assert.match(edge, /body\.mode === "models"/);
assert.match(edge, /twss_reserve_ai_calls/);
assert.match(edge, /Math\.min\(2, selected\.length\)/, "provider concurrency must remain bounded");
assert.match(edge, /selectAiCandidates/);
assert.match(edge, /CANDIDATE_GROUPS\.map/, "candidate queries must be balanced before applying group quotas");
assert.match(edge, /group_name=eq\.\$\{group\}/);
assert.doesNotMatch(edge, /opportunity_score_history/);
assert.doesNotMatch(edge, /stock_analysis_cache\?on_conflict/);
assert.match(vaultMigration, /security invoker/);
assert.match(vaultMigration, /revoke all on function public\.twss_get_gemini_api_key\(\) from public, anon, authenticated/);
assert.match(vaultMigration, /grant execute on function public\.twss_get_gemini_api_key\(\) to service_role/);
assert.doesNotMatch(vaultMigration, /AQ\.|AIza/, "provider credentials must never be committed to migrations");
assert.match(migration, /AI.*never used as input|Never used as input/i);
assert.match(migration, /p_daily_limit integer default 12/);
assert.match(migration, /least\(20/);
assert.match(migration, /using \(status = 'ready'\)/);
assert.doesNotMatch(migration, /grant (insert|update|delete|all).*to anon/i);
assert.equal(createHash("sha256").update(opportunityEngine).digest("hex"), "fa661f98c196904eb9123c1d900fa67a59fe4f044d504b93d11c7001775e58dd", "AI release must not modify opportunity scoring");
assert.equal(createHash("sha256").update(deepData).digest("hex"), "fb4ab0a840a89ce87ccd07c7808950c7d0d33489c541ad3da374ddb1f2c7c2c5", "AI release must not modify deep quantitative analysis");

console.log("AI research tests passed: independent scoring, quota-balanced selection, deduplication, schema validation, and no-key isolation");
