export const OFFICIAL_NEWS_SOURCES = [
  {
    id: "twse-mops",
    market: "listed",
    url: "https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
    symbolKeys: ["公司代號"],
    companyKeys: ["公司名稱"],
    outputDateKeys: ["出表日期"],
  },
  {
    id: "tpex-mops",
    market: "otc",
    url: "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O",
    symbolKeys: ["SecuritiesCompanyCode"],
    companyKeys: ["CompanyName"],
    outputDateKeys: ["Date"],
  },
];

const POSITIVE_TERMS = [
  "獲利", "成長", "創新高", "得標", "股利", "買回", "合作", "核准",
  "增產", "擴產", "處分利益", "營收增加", "轉盈", "上修",
];
const NEGATIVE_TERMS = [
  "虧損", "損失", "裁罰", "停工", "違約", "下修", "訴訟", "火災",
  "事故", "減產", "撤銷", "終止", "延遲", "資安事件", "停止交易",
];

function clean(value, limit = 4_000) {
  return String(value ?? "")
    .replace(/\u0000/g, "")
    .replace(/\r\n?/g, "\n")
    .trim()
    .slice(0, limit);
}

function pick(row, candidates) {
  const wanted = new Set(candidates.map((key) => key.trim()));
  const entry = Object.entries(row || {}).find(([key]) => wanted.has(String(key).trim()));
  return entry?.[1] ?? "";
}

export function rocDate(value) {
  const digits = clean(value, 16).replace(/\D/g, "");
  if (digits.length < 7) return null;
  const year = Number(digits.slice(0, digits.length - 4)) + 1911;
  const month = Number(digits.slice(-4, -2));
  const day = Number(digits.slice(-2));
  if (year < 1912 || month < 1 || month > 12 || day < 1 || day > 31) return null;
  const calendarProbe = new Date(Date.UTC(year, month - 1, day));
  if (calendarProbe.getUTCFullYear() !== year ||
      calendarProbe.getUTCMonth() !== month - 1 ||
      calendarProbe.getUTCDate() !== day) return null;
  const date = `${String(year).padStart(4, "0")}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  const parsed = new Date(`${date}T00:00:00+08:00`);
  return Number.isNaN(parsed.valueOf()) ? null : date;
}

export function speechTimestamp(dateValue, timeValue) {
  const date = rocDate(dateValue);
  if (!date) return null;
  const time = clean(timeValue, 16).replace(/\D/g, "").padStart(6, "0").slice(-6);
  const hours = Number(time.slice(0, 2));
  const minutes = Number(time.slice(2, 4));
  const seconds = Number(time.slice(4, 6));
  if (hours > 23 || minutes > 59 || seconds > 59) return null;
  const parsed = new Date(
    `${date}T${time.slice(0, 2)}:${time.slice(2, 4)}:${time.slice(4, 6)}+08:00`,
  );
  return Number.isNaN(parsed.valueOf()) ? null : parsed.toISOString();
}

export function classifyDisclosure(text) {
  const normalized = clean(text, 8_000);
  const positive = POSITIVE_TERMS.filter((term) => normalized.includes(term));
  const negative = NEGATIVE_TERMS.filter((term) => normalized.includes(term));
  const difference = positive.length - negative.length;
  const label = difference > 0 ? "benefit" : difference < 0 ? "harm" : "neutral";
  return {
    label,
    score: Math.max(-100, Math.min(100, difference * 20)),
    basis: "official-disclosure-keyword-rule-v1",
    terms: [...new Set([...positive, ...negative])],
  };
}

export async function sha256Hex(value) {
  const bytes = new TextEncoder().encode(String(value));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function normalizeOfficialDisclosure(row, source, fetchedAt = new Date().toISOString()) {
  const symbol = clean(pick(row, source.symbolKeys), 16).toUpperCase();
  const companyName = clean(pick(row, source.companyKeys), 200);
  const speechDateRaw = clean(pick(row, ["發言日期"]), 16);
  const speechTimeRaw = clean(pick(row, ["發言時間"]), 16);
  const outputDateRaw = clean(pick(row, source.outputDateKeys), 16);
  const title = clean(pick(row, ["主旨"]), 1_000);
  const summary = clean(pick(row, ["說明"]), 4_000);
  const category = clean(pick(row, ["符合條款"]), 120) || null;
  const eventDate = rocDate(pick(row, ["事實發生日"]));
  const publishedAt = speechTimestamp(speechDateRaw || outputDateRaw, speechTimeRaw);
  if (!/^[0-9A-Z]{2,12}$/.test(symbol) || !title || !publishedAt) return null;

  const externalId = await sha256Hex([
    source.market,
    symbol,
    speechDateRaw || outputDateRaw,
    speechTimeRaw.padStart(6, "0"),
    title,
  ].join("|"));
  const contentHash = await sha256Hex([title, summary, category || "", eventDate || ""].join("|"));
  const sentiment = classifyDisclosure(`${title}\n${summary}`);
  return {
    source: source.id,
    external_id: externalId,
    market: source.market,
    symbols: [symbol],
    company_name: companyName || null,
    title,
    summary,
    category,
    event_date: eventDate,
    sentiment_label: sentiment.label,
    sentiment_score: sentiment.score,
    sentiment_basis: sentiment.basis,
    sentiment_terms: sentiment.terms,
    source_url: source.url,
    published_at: publishedAt,
    content_hash: contentHash,
    fetched_at: fetchedAt,
    updated_at: fetchedAt,
  };
}

export async function normalizeOfficialFeed(rows, source, fetchedAt = new Date().toISOString()) {
  const normalized = await Promise.all(
    (Array.isArray(rows) ? rows : []).map((row) => normalizeOfficialDisclosure(row, source, fetchedAt)),
  );
  return normalized.filter(Boolean);
}

export function filterChangedDisclosures(rows, existingRows) {
  const existing = new Map((Array.isArray(existingRows) ? existingRows : []).map((row) => [
    `${String(row.source)}:${String(row.external_id)}`,
    String(row.content_hash || ""),
  ]));
  const changed = (Array.isArray(rows) ? rows : []).filter((row) =>
    existing.get(`${String(row.source)}:${String(row.external_id)}`) !== String(row.content_hash));
  return { changed, unchanged: (Array.isArray(rows) ? rows.length : 0) - changed.length };
}

export const v19NewsInternals = { clean, pick, POSITIVE_TERMS, NEGATIVE_TERMS };
