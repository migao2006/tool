const API_CONTRACT_VERSION = "prediction-snapshot.v1";
const UNUSABLE_VERSIONS = new Set([
  "", "-", "—", "NONE", "NOT-TRAINED", "NOT_TRAINED", "RESEARCH_ONLY", "UNCALIBRATED",
]);
const DECISION_GATE_ORDER = Object.freeze([
  "data_quality_hard_gate",
  "tradability_gate",
  "liquidity_capacity_gate",
  "market_exposure_cap",
  "calibrated_direction_probabilities",
  "net_quantile_thresholds",
  "rank_eligibility",
  "position_capacity_limits",
]);

function hasUsableVersion(value) {
  return typeof value === "string" && !UNUSABLE_VERSIONS.has(value.trim().toUpperCase());
}

function isCalibratedInterval(value) {
  if (typeof value !== "string") return false;
  const [status, version, ...remainder] = value.trim().split(":");
  return status?.toUpperCase() === "CALIBRATED"
    && hasUsableVersion(version)
    && remainder.length === 0;
}

function dateOnly(value, label) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/u.test(value)
    || Number.isNaN(Date.parse(`${value}T00:00:00Z`))
    || new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) !== value) {
    throw new TypeError(`${label} 不是有效日期。`);
  }
  return value;
}

function awareTimestamp(value, label) {
  if (typeof value !== "string" || !/(?:Z|[+-]\d{2}:\d{2})$/u.test(value)) {
    throw new TypeError(`${label} 必須包含時區。`);
  }
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) throw new TypeError(`${label} 不是有效時間。`);
  return timestamp;
}

function assertProbabilityVector(values, label) {
  if (!values.every((value) => Number.isFinite(value) && value >= 0 && value <= 1)) {
    throw new TypeError(`${label} 機率欄位不完整。`);
  }
  const total = values.reduce((sum, value) => sum + value, 0);
  if (Math.abs(total - 1) > 0.01) throw new RangeError(`${label} 機率總和不等於 1。`);
}

function isFiniteInRange(value, minimum, maximum = Number.POSITIVE_INFINITY) {
  return Number.isFinite(value) && value >= minimum && value <= maximum;
}

function validateDecisionGateSet(record, snapshot, requireSourceDates = false) {
  if (record.gates.length === 0) {
    if (requireSourceDates) {
      throw new TypeError(`${record.symbol} 的決策 gate 缺漏。`);
    }
    return;
  }
  if (
    record.gates.map((gate) => gate.key).join("|") !==
    DECISION_GATE_ORDER.join("|")
  ) {
    throw new TypeError(`${record.symbol} 的決策 gate 缺漏或順序錯誤。`);
  }
  record.gates.forEach((gate) => {
    if (typeof gate.passed !== "boolean" || !gate.reason_code) {
      throw new TypeError(`${record.symbol} 的決策 gate 結果不完整。`);
    }
    if (
      gate.actual === null ||
      gate.actual === undefined ||
      gate.threshold === null ||
      gate.threshold === undefined
    ) {
      throw new TypeError(`${record.symbol} 的決策 gate 實際值或門檻缺漏。`);
    }
    if (gate.source_date === null) {
      if (requireSourceDates) {
        throw new TypeError(`${record.symbol} 的決策 gate 缺少來源日期。`);
      }
      return;
    }
    if (
      dateOnly(gate.source_date, `${record.symbol} gate source_date`) >
      snapshot.asOfDate
    ) {
      throw new RangeError(
        `${record.symbol} 的決策 gate 來源日期晚於資料日期。`,
      );
    }
  });
  const allGatesPassed = record.gates.every((gate) => gate.passed);
  if (
    ["CANDIDATE", "WATCH"].includes(record.decision) &&
    !allGatesPassed
  ) {
    throw new TypeError(`${record.symbol} 的決策與 gate 結果不一致。`);
  }
  if (
    record.decision === "WATCH" &&
    !record.reason_codes.includes("OUTSIDE_TOP_K")
  ) {
    throw new TypeError(`${record.symbol} 的 WATCH 缺少 Top-K 排除證據。`);
  }
  if (record.decision === "NO_TRADE" && allGatesPassed) {
    throw new TypeError(`${record.symbol} 的 NO_TRADE 缺少未通過的政策 gate。`);
  }
}

function validateFormalRecord(record, snapshot, decisionTimestamp) {
  validateDecisionGateSet(record, snapshot, true);
  if (!record.symbol || !record.name || !["TWSE", "TPEX"].includes(record.market)
    || record.asset_type !== "STOCK" || record.data_quality_status !== "PASS") {
    throw new TypeError("正式普通股預測含有不支援的標的或市場。");
  }
  if (record.as_of_date !== snapshot.asOfDate || record.horizon !== snapshot.horizon
    || awareTimestamp(record.decision_at, `${record.symbol} decision_at`) !== decisionTimestamp) {
    throw new RangeError(`${record.symbol} 的日期或 horizon 與快照不一致。`);
  }
  if (record.model_version !== snapshot.modelVersion
    || record.cost_profile_version !== snapshot.costProfileVersion
    || record.training_end_date !== snapshot.trainingEndDate) {
    throw new TypeError(`${record.symbol} 的模型或成本版本與快照不一致。`);
  }
  if (
    record.decision_policy_status !== "EVALUATED" ||
    !record.decision ||
    !hasUsableVersion(record.feature_schema_hash)
  ) {
    throw new TypeError(`${record.symbol} 的決策或特徵版本無效。`);
  }
  if (record.market_regime !== snapshot.market.regime
    || Math.abs(record.market_exposure_cap - snapshot.market.exposure_cap) > 1e-9) {
    throw new TypeError(`${record.symbol} 的市場狀態或曝險與快照不一致。`);
  }
  if (!Number.isFinite(record.rank_score) || record.rank_score < 0 || record.rank_score > 100) {
    throw new RangeError(`${record.symbol} 的 Rank Score 不在 0～100。`);
  }
  if (!Number.isInteger(record.global_rank) || record.global_rank < 1
    || !isFiniteInRange(record.global_rank_percentile, 0, 1)
    || (record.industry_rank !== null && (!Number.isInteger(record.industry_rank) || record.industry_rank < 1))
    || (record.industry_rank_percentile !== null
      && !isFiniteInRange(record.industry_rank_percentile, 0, 1))) {
    throw new RangeError(`${record.symbol} 的市場或產業排名欄位無效。`);
  }
  assertProbabilityVector(
    [record.calibrated_p_up, record.calibrated_p_neutral, record.calibrated_p_down],
    `${record.symbol} 方向`,
  );
  if (!hasUsableVersion(record.calibration_version) || !isCalibratedInterval(record.calibration_status)) {
    throw new TypeError(`${record.symbol} 的校準版本無效。`);
  }
  if (![record.net_q10, record.net_q50, record.net_q90].every(Number.isFinite)
    || record.net_q10 > record.net_q50 || record.net_q50 > record.net_q90) {
    throw new RangeError(`${record.symbol} 的淨報酬分位數不完整或不單調。`);
  }
  if (![record.gross_q10, record.gross_q50, record.gross_q90].every(Number.isFinite)
    || record.gross_q10 > record.gross_q50 || record.gross_q50 > record.gross_q90) {
    throw new RangeError(`${record.symbol} 的毛報酬分位數不完整或不單調。`);
  }
  if (!Number.isFinite(record.interval_width)
    || Math.abs(record.interval_width - (record.net_q90 - record.net_q10)) > 1e-8) {
    throw new RangeError(`${record.symbol} 的報酬區間寬度不一致。`);
  }
  const details = [
    record.industry, record.liquidity_bucket, record.cost_profile, record.feature_schema_hash,
    record.source_dates, record.latest_available_at, record.forecast_volatility,
    record.downside_risk, record.adv20, record.max_order_notional_ntd,
    record.max_single_position, record.max_industry_position, record.market_exposure_cap,
    record.estimated_round_trip_cost,
  ];
  if (details.some((value) => value === null || value === undefined || value === "")) {
    throw new TypeError(`${record.symbol} 的風險、容量或稽核欄位不完整。`);
  }
  if (!isFiniteInRange(record.forecast_volatility, 0)
    || !isFiniteInRange(record.downside_risk, 0)
    || !isFiniteInRange(record.adv20, 0)
    || !isFiniteInRange(record.max_order_notional_ntd, 0)
    || !isFiniteInRange(record.max_single_position, 0, 1)
    || !isFiniteInRange(record.max_industry_position, 0, 1)
    || !isFiniteInRange(record.market_exposure_cap, 0, 1)
    || !isFiniteInRange(record.estimated_round_trip_cost, 0)) {
    throw new RangeError(`${record.symbol} 的風險、容量或成本數值超出範圍。`);
  }
  if (!record.source_dates || typeof record.source_dates !== "object"
    || Array.isArray(record.source_dates) || Object.keys(record.source_dates).length === 0) {
    throw new TypeError(`${record.symbol} 的來源日期不完整。`);
  }
  Object.values(record.source_dates).forEach((value) => {
    if (dateOnly(value, `${record.symbol} source_date`) > snapshot.asOfDate) {
      throw new RangeError(`${record.symbol} 的來源日期晚於資料日期。`);
    }
  });
  if (awareTimestamp(record.latest_available_at, `${record.symbol} latest_available_at`) > decisionTimestamp) {
    throw new RangeError(`${record.symbol} 使用了決策時間之後的資料。`);
  }
}

export function validateFormalSnapshot(snapshot) {
  [...snapshot.predictions, ...snapshot.watchlist, ...snapshot.excluded]
    .forEach((record) => {
      validateDecisionGateSet(
        record,
        snapshot,
        record.decision_policy_status === "EVALUATED",
      );
    });
  if (snapshot.systemStatus !== "PASS") return;
  if (snapshot.stale || snapshot.dataQualityHardFail) {
    throw new TypeError("PASS 快照不得為 stale 或 data quality hard fail。");
  }
  if (snapshot.predictions.length === 0) {
    throw new TypeError("PASS 快照必須包含至少一筆正式政策列。");
  }
  if (snapshot.apiContractVersion !== API_CONTRACT_VERSION) {
    throw new TypeError("PASS 快照缺少或使用不支援的 API 契約版本。");
  }
  const asOfDate = dateOnly(snapshot.asOfDate, "as_of_date");
  const decisionTimestamp = awareTimestamp(snapshot.decisionAt, "decision_at");
  const trainingEndDate = dateOnly(snapshot.trainingEndDate, "training_end_date");
  if (trainingEndDate >= asOfDate || !hasUsableVersion(snapshot.modelVersion)
    || !hasUsableVersion(snapshot.costProfileVersion)) {
    throw new TypeError("PASS 快照缺少有效日期或模型版本稽核欄位。");
  }
  assertProbabilityVector(
    [snapshot.market.p_up, snapshot.market.p_neutral, snapshot.market.p_down],
    "市場方向",
  );
  if (!snapshot.market.regime || !isFiniteInRange(snapshot.market.forecast_volatility, 0)
    || !isFiniteInRange(snapshot.market.exposure_cap, 0, 1)) {
    throw new TypeError("PASS 快照的市場狀態、波動或曝險欄位不完整。");
  }
  if (snapshot.market.as_of_date !== asOfDate
    || snapshot.market.horizon !== snapshot.horizon
    || awareTimestamp(snapshot.market.decision_at, "market decision_at") !== decisionTimestamp
    || !hasUsableVersion(snapshot.market.model_version)
    || dateOnly(snapshot.market.training_end_date, "market training_end_date") >= asOfDate) {
    throw new TypeError("PASS 快照的市場模型日期或版本不一致。");
  }
  [...snapshot.predictions, ...snapshot.watchlist]
    .filter((record) => !record.data_quality_hard_fail)
    .forEach((record) => {
      validateFormalRecord(record, snapshot, decisionTimestamp);
    });
}
