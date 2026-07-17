function rows(value) {
  if (Array.isArray(value)) return value;
  if (Array.isArray(value?.data)) return value.data;
  return [];
}

function number(value) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(String(value).replace(/[%+,]/g, "").trim());
  return Number.isFinite(parsed) ? parsed : null;
}

function isoDate(value) {
  const digits = String(value || "").replace(/\D/g, "");
  if (digits.length === 7) {
    const year = Number(digits.slice(0, 3)) + 1911;
    return `${year}-${digits.slice(3, 5)}-${digits.slice(5, 7)}`;
  }
  if (digits.length === 8) return `${digits.slice(0, 4)}-${digits.slice(4, 6)}-${digits.slice(6, 8)}`;
  return /^\d{4}-\d{2}-\d{2}$/.test(String(value || "")) ? String(value) : null;
}

function round(value, digits = 4) {
  if (!Number.isFinite(Number(value))) return null;
  const scale = 10 ** digits;
  return Math.round(Number(value) * scale) / scale;
}

function indexSnapshot(payload, dataDate, fields, source, code, name) {
  const normalized = rows(payload)
    .map((row) => ({ row, date: isoDate(row?.Date ?? row?.date) }))
    .filter((entry) => entry.date)
    .sort((left, right) => left.date.localeCompare(right.date));
  const index = normalized.findIndex((entry) => entry.date === dataDate);
  if (index < 0) return null;
  const current = normalized[index].row;
  const value = number(current?.[fields.close]);
  if (value === null) return null;
  const priorValue = index > 0 ? number(normalized[index - 1].row?.[fields.close]) : null;
  const explicitChange = fields.change ? number(current?.[fields.change]) : null;
  const change = explicitChange ?? (priorValue === null ? null : round(value - priorValue, 4));
  const changePercent = priorValue && change !== null ? round(change / priorValue * 100, 4) : null;
  return {
    code,
    name,
    dataDate,
    value,
    close: value,
    open: number(current?.[fields.open]),
    high: number(current?.[fields.high]),
    low: number(current?.[fields.low]),
    change,
    changePercent,
    source,
  };
}

function tradingSession(row) {
  const raw = String(
    row?.TradingSession ?? row?.tradingSession ?? row?.Session ?? row?.session ?? "",
  ).trim();
  const normalized = raw.toLowerCase().replace(/[\s_-]+/g, "");
  if (
    normalized.includes("一般") || normalized.includes("日盤") ||
    normalized.includes("regular") || normalized.includes("daysession") || normalized === "day"
  ) return "regular";
  if (
    normalized.includes("盤後") || normalized.includes("夜盤") ||
    normalized.includes("afterhours") || normalized.includes("aftersession") || normalized === "night"
  ) return "after_hours";
  return raw ? `unknown:${raw}` : "unknown";
}

function txSnapshot(payload, dataDate) {
  const candidates = rows(payload)
    .filter((row) => isoDate(row?.Date) === dataDate)
    .filter((row) => String(row?.Contract || "").trim() === "TX")
    .filter((row) => /^\d{6}$/.test(String(row?.["ContractMonth(Week)"] || "").trim()))
    .filter((row) => number(row?.Last) !== null)
    .map((row) => ({ row, session: tradingSession(row) }));
  const preferredSession = candidates.some((entry) => entry.session === "regular")
    ? "regular"
    : candidates.some((entry) => entry.session === "after_hours")
    ? "after_hours"
    : candidates[0]?.session;
  const row = candidates
    .filter((entry) => entry.session === preferredSession)
    .sort((left, right) => (number(right.row?.Volume) || 0) - (number(left.row?.Volume) || 0))[0]?.row;
  if (!row) return null;
  const value = number(row.Last);
  return {
    code: "tx",
    name: "臺股期貨",
    dataDate,
    value,
    close: value,
    settlement: number(row.SettlementPrice),
    settlementPrice: number(row.SettlementPrice),
    open: number(row.Open),
    high: number(row.High),
    low: number(row.Low),
    change: number(row.Change),
    changePercent: number(row["%"]),
    contractMonth: String(row["ContractMonth(Week)"] || "").trim(),
    volume: number(row.Volume),
    openInterest: number(row.OpenInterest),
    session: preferredSession,
    source: "TAIFEX OpenAPI",
  };
}

export function normalizeOfficialMarketPayloads(payloads = {}, dataDate = "") {
  return {
    taiex: indexSnapshot(payloads.twse, dataDate, {
      close: "ClosingIndex",
      open: "OpeningIndex",
      high: "HighestIndex",
      low: "LowestIndex",
    }, "TWSE OpenAPI", "taiex", "加權指數"),
    tpex: indexSnapshot(payloads.tpex, dataDate, {
      close: "Close",
      open: "Open",
      high: "High",
      low: "Low",
      change: "Change",
    }, "TPEx OpenAPI", "tpex", "櫃買指數"),
    txFutures: txSnapshot(payloads.taifex, dataDate),
  };
}

export function enrichMarketContextWithOfficial(context = {}, official = {}) {
  const degraded = new Set(Array.isArray(context.degraded_sources) ? context.degraded_sources : []);
  if (official.taiex) degraded.delete("taiex_official_index");
  if (official.tpex) degraded.delete("tpex_official_index");
  if (official.txFutures) degraded.delete("tx_futures");
  const remaining = [...degraded];
  const sourceDates = { ...(context.source_dates || {}) };
  if (official.taiex) sourceDates.taiex = official.taiex.dataDate;
  if (official.tpex) sourceDates.tpex = official.tpex.dataDate;
  if (official.txFutures) sourceDates.txFutures = official.txFutures.dataDate;
  const completeness = round(Math.max(0, 100 - remaining.length * 12.5), 2);
  const confidence = round(Math.min(90, completeness), 2);
  const status = context.status === "error" ? "error" : remaining.length ? "partial" : "complete";
  return {
    ...context,
    taiex: official.taiex || context.taiex || {},
    tpex: official.tpex || context.tpex || {},
    tx_futures: official.txFutures || context.tx_futures || {},
    completeness,
    confidence,
    status,
    source_dates: sourceDates,
    degraded_sources: remaining,
  };
}
