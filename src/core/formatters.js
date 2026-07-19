export function formatPercent(value, digits = 1) {
  return Number.isFinite(value) ? `${(value * 100).toFixed(digits)}%` : "—";
}

export function formatRank(value) {
  return Number.isFinite(value) ? `第 ${Math.trunc(value)} 名` : "—";
}

export function formatRankScore(value) {
  return Number.isFinite(value) ? Number(value).toFixed(1) : "—";
}

export function formatCurrency(value) {
  return Number.isFinite(value)
    ? new Intl.NumberFormat("zh-TW", { style: "currency", currency: "TWD", maximumFractionDigits: 0 }).format(value)
    : "—";
}

export function formatValue(value, digits = 4) {
  return Number.isFinite(value) ? Number(value).toFixed(digits) : "—";
}

export function formatDateTime(value) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return new Intl.DateTimeFormat("zh-TW", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(parsed);
}

export function formatReasonCodeSummary(reasonCodes, limit = 2) {
  const codes = Array.isArray(reasonCodes)
    ? reasonCodes.filter((code) => typeof code === "string" && code.length > 0)
    : [];
  if (!codes.length) return "—";

  const visibleCodes = codes.slice(0, Math.max(1, limit));
  const hiddenCount = codes.length - visibleCodes.length;
  const summary = visibleCodes.join(" · ");
  return hiddenCount > 0 ? `${summary} · 另 ${hiddenCount} 項稽核資訊` : summary;
}
