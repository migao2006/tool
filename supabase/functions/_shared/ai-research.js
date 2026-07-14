export const AI_SCHEMA_VERSION = "1.0";
export const QUANT_ANALYSIS_VERSION = "16.3-ultimate-data-audit";
export const DEFAULT_AI_DAILY_LIMIT = 12;
export const MAX_AI_DAILY_LIMIT = 20;
export const DEFAULT_GROUP_QUOTAS = Object.freeze({ listed: 5, otc: 5, etf: 2 });

const GROUPS = ["listed", "otc", "etf"];
const VERDICTS = new Set(["偏多觀察", "中性觀察", "風險升高"]);

const finite = (value) => value != null && Number.isFinite(Number(value));
const numberOrNull = (value) => finite(value) ? Number(value) : null;

function compact(value) {
  if (value == null) return null;
  if (Array.isArray(value)) return value.map(compact);
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (["string", "boolean"].includes(typeof value)) return value;
  if (typeof value !== "object") return null;
  return Object.fromEntries(Object.entries(value)
    .filter(([, item]) => item !== undefined)
    .map(([key, item]) => [key, compact(item)]));
}

function ordered(value) {
  if (Array.isArray(value)) return value.map(ordered);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, ordered(value[key])]));
  }
  return value;
}

export function canonicalStringify(value) {
  return JSON.stringify(ordered(compact(value)));
}

export async function sha256Hex(value) {
  const bytes = new TextEncoder().encode(typeof value === "string" ? value : canonicalStringify(value));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function pick(source, keys) {
  return Object.fromEntries(keys.map((key) => [key, source?.[key] ?? null]));
}

export function buildAiFacts(row) {
  const stock = row?.stock || {};
  const analysis = row?.analysis || {};
  const result = row?.result || {};
  const group = GROUPS.includes(row?.group_name) ? row.group_name : result.group;
  return compact({
    schemaVersion: AI_SCHEMA_VERSION,
    identity: {
      symbol: String(row?.symbol || stock.symbol || ""),
      name: stock.name || result.name || "",
      group,
      market: stock.market || null,
      instrumentType: stock.instrumentType || (group === "etf" ? "ETF" : "股票"),
      industry: stock.industry || null,
      dataDate: row?.data_date || null,
    },
    quantitativeResultReadOnly: {
      analysisVersion: row?.analysis_version || analysis.analysisVersion || null,
      score: numberOrNull(row?.score ?? result.score),
      confidence: numberOrNull(row?.confidence ?? result.confidence),
      tier: row?.tier || result.tier || null,
      official: Boolean(row?.official ?? result.official),
      archetypes: Array.isArray(result.archetypes) ? result.archetypes.slice(0, 5) : [],
      reasons: Array.isArray(result.reasons) ? result.reasons.slice(0, 8) : [],
      categories: Array.isArray(result.categories) ? result.categories.slice(0, 8).map((item) => pick(item, [
        "key", "label", "score", "weight", "coverage",
      ])) : [],
      risk: result.risk || {},
      missing: Array.isArray(result.missing) ? result.missing.slice(0, 12) : [],
    },
    marketSnapshot: pick(stock, [
      "close", "change", "open", "high", "low", "volume", "value", "pe", "pb", "yield",
    ]),
    growth: {
      ...pick(stock, ["rev", "revMom", "revYtd", "revAcceleration", "revPeriod", "revenue"]),
      ...pick(analysis.revenue, [
        "period", "yoy", "mom", "ytdYoy", "avg3Yoy", "acceleration", "acceleration3",
        "consecutiveAcceleration", "new12MonthHigh", "sameMonthRecord", "seasonalGrowth",
        "postRelease5", "postReleaseStatus", "postReleaseObservedDays",
      ]),
    },
    financialQuality: pick(analysis.financial, [
      "period", "eps", "epsYoy", "grossMargin", "operatingMargin", "operatingMarginYoyChange",
      "netMargin", "roe", "operatingCashFlow", "freeCashFlow", "ttmNetIncome", "ttmOperatingCashFlow",
      "ttmFreeCashFlow", "cashConversion", "cashConversionBasis", "inventoryYoy", "receivablesYoy",
      "debtRatio", "currentRatio", "interestCoverage", "nonOperatingRatio", "revenue", "revenueYoy",
      "revenueStatus",
    ]),
    capitalFlow: {
      latest: pick(stock, [
        "foreign", "trust", "dealer", "inst", "marginBalance", "marginChange", "shortBalance", "shortChange",
      ]),
      institutional: pick(analysis.institutional, [
        "foreign5", "foreign10", "foreign20", "trust5", "trust10", "trust20", "dealer5",
        "inst5", "inst10", "inst20", "foreignStreak", "trustStreak", "instStreak", "intensity5",
      ]),
      margin: pick(analysis.margin, [
        "applicable", "marginEligible", "financingEligible", "marginBalance", "marginChange5",
        "marginChange20", "marginUsage", "shortBalance", "shortChange5", "shortChange20",
      ]),
      lending: pick(analysis.lending, ["rows", "date", "latest", "total20"]),
      holdings: pick(analysis.holdings, ["date", "large400Ratio", "retail10Ratio", "holders"]),
    },
    technicalAndRelativeStrength: pick(analysis.price, [
      "lastDate", "return5", "return20", "return60", "relative20", "relative60", "marketReturn20",
      "volume5", "volume20", "volumeRatio", "upDownVolumeRatio", "ma5", "ma10", "ma20", "ma60",
      "ma120", "ma240", "ma20Slope5", "ma60Slope5", "breakout20", "atr14", "atrPct", "rsi14",
      "macd", "macdSignal", "macdHistogram", "kdK", "kdD", "distanceMa20", "distanceMa60",
      "distanceHigh20", "distanceHigh60", "limitUpStreak", "jumpAnomaly",
    ]),
    valuation: {
      ...pick(stock, ["pe", "pb", "yield"]),
      ...pick(analysis.valuation, [
        "pePercentile", "pbPercentile", "industryPePercentile", "growthValuationGap",
      ]),
    },
    marketAndIndustry: compact(analysis.market || analysis.environment || {}),
    etf: group === "etf" ? compact(analysis.etf || {}) : null,
    sourceDiagnostics: compact(analysis.sourceDiagnostics || {}),
  });
}

export function isEligibleAiCandidate(row) {
  const group = row?.group_name;
  return GROUPS.includes(group) && row?.status === "ready" && row?.official === true &&
    (row?.analysis_version || row?.analysis?.analysisVersion) === QUANT_ANALYSIS_VERSION &&
    numberOrNull(row?.confidence ?? row?.result?.confidence) >= 70 &&
    numberOrNull(row?.score ?? row?.result?.score) >= 65 &&
    /^\d{4,6}[A-Z]?$/i.test(String(row?.symbol || ""));
}

export function allocateGroupQuotas(limit, weights = DEFAULT_GROUP_QUOTAS) {
  const safeLimit = Math.max(1, Math.min(MAX_AI_DAILY_LIMIT, Number(limit) || DEFAULT_AI_DAILY_LIMIT));
  const totalWeight = GROUPS.reduce((sum, group) => sum + Math.max(0, Number(weights[group]) || 0), 0) || 1;
  const exact = Object.fromEntries(GROUPS.map((group) => [group, safeLimit * (Math.max(0, Number(weights[group]) || 0) / totalWeight)]));
  const quotas = Object.fromEntries(GROUPS.map((group) => [group, Math.floor(exact[group])]));
  let remaining = safeLimit - GROUPS.reduce((sum, group) => sum + quotas[group], 0);
  for (const group of [...GROUPS].sort((a, b) => (exact[b] - quotas[b]) - (exact[a] - quotas[a]) || GROUPS.indexOf(a) - GROUPS.indexOf(b))) {
    if (remaining <= 0) break;
    quotas[group] += 1;
    remaining -= 1;
  }
  return quotas;
}

function previousFor(previousBySymbol, symbol) {
  return previousBySymbol instanceof Map ? previousBySymbol.get(symbol) : previousBySymbol?.[symbol];
}

function candidateSort(a, b) {
  const score = numberOrNull(b.score ?? b.result?.score) - numberOrNull(a.score ?? a.result?.score);
  if (score) return score;
  const confidence = numberOrNull(b.confidence ?? b.result?.confidence) - numberOrNull(a.confidence ?? a.result?.confidence);
  if (confidence) return confidence;
  return String(a.symbol).localeCompare(String(b.symbol), "en");
}

export function selectAiCandidates(rows, previousBySymbol = new Map(), options = {}) {
  const model = String(options.model || "gemini-3.5-flash");
  const schemaVersion = String(options.schemaVersion || AI_SCHEMA_VERSION);
  const nowMs = Number.isFinite(Date.parse(options.now || "")) ? Date.parse(options.now) : Date.now();
  const limit = Math.max(1, Math.min(MAX_AI_DAILY_LIMIT, Number(options.limit) || DEFAULT_AI_DAILY_LIMIT));
  const changed = rows.filter(isEligibleAiCandidate).filter((row) => {
    if (!row.inputHash) return false;
    const previous = previousFor(previousBySymbol, String(row.symbol));
    const expiresAt = Date.parse(previous?.expires_at || "");
    const expired = Number.isFinite(expiresAt) && expiresAt <= nowMs;
    return !previous || expired || previous.input_hash !== row.inputHash || previous.model !== model || previous.schema_version !== schemaVersion;
  }).sort(candidateSort);
  const quotas = allocateGroupQuotas(limit, options.quotas || DEFAULT_GROUP_QUOTAS);
  const selected = [];
  const selectedSymbols = new Set();
  for (const group of GROUPS) {
    for (const row of changed.filter((item) => item.group_name === group).slice(0, quotas[group])) {
      selected.push(row);
      selectedSymbols.add(String(row.symbol));
    }
  }
  for (const row of changed) {
    if (selected.length >= limit) break;
    if (!selectedSymbols.has(String(row.symbol))) {
      selected.push(row);
      selectedSymbols.add(String(row.symbol));
    }
  }
  return selected.slice(0, limit).sort(candidateSort);
}

export const AI_RESPONSE_JSON_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["verdict", "horizon", "summary", "positives", "risks", "scenarios", "watchItems", "dataWarnings", "aiConfidence"],
  properties: {
    verdict: { type: "string", enum: ["偏多觀察", "中性觀察", "風險升高"] },
    horizon: { type: "string", enum: ["1–8週"] },
    summary: { type: "string", maxLength: 180 },
    positives: {
      type: "array", maxItems: 3,
      items: { type: "object", additionalProperties: false, required: ["title", "evidence"], properties: { title: { type: "string", maxLength: 36 }, evidence: { type: "string", maxLength: 120 } } },
    },
    risks: {
      type: "array", maxItems: 3,
      items: { type: "object", additionalProperties: false, required: ["title", "evidence"], properties: { title: { type: "string", maxLength: 36 }, evidence: { type: "string", maxLength: 120 } } },
    },
    scenarios: {
      type: "object", additionalProperties: false, required: ["bullish", "neutral", "bearish"],
      properties: Object.fromEntries(["bullish", "neutral", "bearish"].map((key) => [key, {
        type: "object", additionalProperties: false, required: ["condition", "observation"],
        properties: { condition: { type: "string", maxLength: 100 }, observation: { type: "string", maxLength: 120 } },
      }])),
    },
    watchItems: { type: "array", maxItems: 4, items: { type: "string", maxLength: 80 } },
    dataWarnings: { type: "array", maxItems: 4, items: { type: "string", maxLength: 80 } },
    aiConfidence: { type: "integer", minimum: 0, maximum: 100 },
  },
};

function cleanText(value, max, label) {
  if (typeof value !== "string" || !value.trim()) throw new Error(`AI 回應缺少 ${label}`);
  return value.replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim().slice(0, max);
}

function evidenceItems(value, label) {
  if (!Array.isArray(value)) throw new Error(`AI 回應的 ${label} 格式不正確`);
  return value.slice(0, 3).map((item, index) => ({
    title: cleanText(item?.title, 36, `${label}[${index}].title`),
    evidence: cleanText(item?.evidence, 120, `${label}[${index}].evidence`),
  }));
}

function textItems(value, label) {
  if (!Array.isArray(value)) throw new Error(`AI 回應的 ${label} 格式不正確`);
  return value.slice(0, 4).map((item, index) => cleanText(item, 80, `${label}[${index}]`));
}

export function normalizeAiAnalysis(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("AI 回應不是 JSON 物件");
  if (!VERDICTS.has(value.verdict)) throw new Error("AI 回應的觀察結論不在允許範圍");
  const scenarios = Object.fromEntries(["bullish", "neutral", "bearish"].map((key) => [key, {
    condition: cleanText(value.scenarios?.[key]?.condition, 100, `scenarios.${key}.condition`),
    observation: cleanText(value.scenarios?.[key]?.observation, 120, `scenarios.${key}.observation`),
  }]));
  if (!finite(value.aiConfidence)) throw new Error("AI 回應缺少 aiConfidence");
  return {
    verdict: value.verdict,
    horizon: "1–8週",
    summary: cleanText(value.summary, 180, "summary"),
    positives: evidenceItems(value.positives, "positives"),
    risks: evidenceItems(value.risks, "risks"),
    scenarios,
    watchItems: textItems(value.watchItems, "watchItems"),
    dataWarnings: textItems(value.dataWarnings, "dataWarnings"),
    aiConfidence: Math.round(Math.max(0, Math.min(100, Number(value.aiConfidence)))),
  };
}

export function parseAiResponse(text) {
  const raw = String(text || "").trim().replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "");
  return normalizeAiAnalysis(JSON.parse(raw));
}

export function buildAiPrompt(facts) {
  const isEtf = facts?.identity?.group === "etf";
  return [
    "你是台灣證券市場的研究摘要員。請只分析下方系統已提供的公開資料，不得自行杜撰新聞、財報、目標價或未提供的數字。",
    "任務是補充 1–8 週觀察重點，不是重新選股，也不是重新計分。quantitativeResultReadOnly 的分數、排名、信心與分類均為唯讀；不得覆寫、重算或暗示 AI 分數取代它。",
    "請明確區分資料事實與推論；資料缺漏要列入 dataWarnings，不得把缺漏當成零或負面事實。",
    "不得給出買進、賣出、保證獲利、精確目標價或個人化投資建議。文字使用繁體中文，簡潔、可核對。",
    isEtf
      ? "這是 ETF：不得使用公司月營收、EPS、ROE 或個股本益比邏輯；只可依 ETF、價量、相對強弱、流動性、折溢價及風險欄位判讀。"
      : "這是公司股票：檢查營運成長、財務品質、法人籌碼、價量位置、估值與過熱風險是否互相印證。",
    "輸出必須完全符合指定 JSON Schema，不要加 Markdown 或其他說明。",
    `輸入資料：${canonicalStringify(facts)}`,
  ].join("\n");
}
