const STOCK_MARKETS = new Set(["TWSE", "TPEX"]);

export function isOrdinaryStock(record) {
  return STOCK_MARKETS.has(record?.market) && record.asset_type !== "ETF";
}

export function compareRankOnly(left, right) {
  if (Number.isFinite(left.global_rank) && Number.isFinite(right.global_rank)) {
    return left.global_rank - right.global_rank;
  }
  if (Number.isFinite(left.global_rank)) return -1;
  if (Number.isFinite(right.global_rank)) return 1;
  if (Number.isFinite(left.rank_score) && Number.isFinite(right.rank_score)) {
    return right.rank_score - left.rank_score;
  }
  if (Number.isFinite(left.rank_score)) return -1;
  if (Number.isFinite(right.rank_score)) return 1;
  return String(left.symbol ?? "").localeCompare(String(right.symbol ?? ""), "zh-Hant");
}

export function eligibleStockRecords(snapshot) {
  return (snapshot?.predictions ?? [])
    .filter((record) => isOrdinaryStock(record) && !record.data_quality_hard_fail)
    .sort(compareRankOnly);
}

export function formalCandidateRecords(snapshot) {
  if (snapshot?.systemStatus !== "PASS" || snapshot.stale || snapshot.dataQualityHardFail) return [];
  return eligibleStockRecords(snapshot).filter((record) => record.decision === "CANDIDATE");
}
