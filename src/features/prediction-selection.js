const STOCK_MARKETS = new Set(["TWSE", "TPEX"]);

export function isOrdinaryStock(record) {
  return Boolean(record?.symbol) && STOCK_MARKETS.has(record.market) && record.asset_type !== "ETF";
}

export function canDisplaySnapshotRecords(snapshot) {
  if (!["PASS", "RESEARCH_ONLY"].includes(snapshot?.systemStatus)
    || snapshot.dataQualityHardFail) return false;
  // OOS research rows require their future label before evaluation, so they are
  // historical by design. Formal PASS snapshots remain fail-closed when stale.
  return snapshot.systemStatus === "RESEARCH_ONLY" || !snapshot.stale;
}

export function isHistoricalResearchSnapshot(snapshot) {
  return snapshot?.systemStatus === "RESEARCH_ONLY" && snapshot.stale === true;
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

export function displayableStockRecords(snapshot) {
  return canDisplaySnapshotRecords(snapshot) ? eligibleStockRecords(snapshot) : [];
}

export function overviewStockRecords(snapshot) {
  if (snapshot?.systemStatus === "PASS") return formalCandidateRecords(snapshot);
  const records = displayableStockRecords(snapshot);
  const researchCandidates = records.filter((record) => record.decision === "CANDIDATE");
  return researchCandidates.length ? researchCandidates : records;
}
