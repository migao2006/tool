import type { SnapshotRows } from "../types.ts";

export const DECISION_GATE_NAMES = [
  "data_quality_hard_gate",
  "tradability_gate",
  "liquidity_capacity_gate",
  "market_exposure_cap",
  "calibrated_direction_probabilities",
  "net_quantile_thresholds",
  "rank_eligibility",
  "position_capacity_limits",
];

export function evaluatedGateRows(
  stockPredictionId: number,
  failedGate: string | null = null,
) {
  return DECISION_GATE_NAMES.map((gateName, index) => ({
    stock_prediction_id: stockPredictionId,
    gate_order: index + 1,
    gate_name: gateName,
    passed: gateName !== failedGate,
    actual_value: {
      contract_version: "research-decision-gate.v1",
      value: { verified: true },
      source_date: "2026-07-17",
      attachment_snapshot_sha256: "a".repeat(64),
    },
    threshold_value: { required: true },
    reason_code: gateName === failedGate ? "POLICY_GATE_NOT_PASSED" : "PASS",
  }));
}

export function snapshotRows(): SnapshotRows {
  return {
    run: {
      prediction_run_id: 7,
      as_of_date: "2026-07-17",
      decision_at: "2026-07-17T06:00:00+00:00",
      horizon: 5,
      market_scope: "TWSE",
      model_bundle_version: "rank-research-v1",
      feature_schema_hash: "feature-hash",
      cost_profile_version: "tw-stock-base-v1",
      training_end_date: "2026-06-30",
      system_validation_status: "RESEARCH_ONLY",
      source_dates: { daily_bars: "2026-07-17" },
      latest_available_at: "2026-07-17T05:30:00+00:00",
      candidate_count: 1,
      watch_count: 0,
      no_trade_count: 0,
      policy_input_missing_count: 0,
      policy_validation_failed_count: 0,
      policy_hard_fail_count: 1,
      hard_fail_count: 1,
      created_at: "2026-07-18T02:00:00+00:00",
    },
    predictions: [
      prediction(11, 101, "CANDIDATE", "EVALUATED", "PASS", 1),
      prediction(12, 102, null, "HARD_FAIL", "FAIL", 2),
    ],
    securities: [
      {
        security_id: 101,
        symbol: "2330",
        display_name: "台積電",
        market: "TWSE",
        asset_type: "COMMON_STOCK",
      },
      {
        security_id: 102,
        symbol: "9999",
        display_name: "排除標的",
        market: "TWSE",
        asset_type: "COMMON_STOCK",
      },
    ],
    currentSecurityHistory: [
      {
        security_id: 101,
        effective_from: "2026-07-18",
        effective_to: null,
        industry_code: "24",
        industry_name: null,
        source_version: "fixture-v1",
        available_at: "2026-07-18T08:00:00+00:00",
      },
    ],
    audits: [
      {
        security_id: 102,
        quality_status: "FAIL",
        hard_fail: true,
        reason_codes: ["DATA_QUALITY_HARD_FAIL"],
        source_dates: { daily_bars: "2026-07-17" },
        latest_available_at: "2026-07-17T05:00:00+00:00",
      },
    ],
    gates: evaluatedGateRows(11),
    markets: [{
      market: "TWSE",
      calibrated_p_up: "0.60",
      calibrated_p_neutral: "0.25",
      calibrated_p_down: "0.15",
      market_regime: "UPTREND_NORMAL_VOL",
      forecast_market_volatility: "0.18",
      market_exposure_cap: "0.60",
      model_version: "market-research-v1",
      training_end_date: "2026-06-30",
    }],
    validationRun: {
      validation_run_id: 5,
      validation_status: "RESEARCH_ONLY",
      locked_holdout: false,
      frozen_config_hash: "config-hash",
      started_at: "2026-07-18T00:00:00+00:00",
      completed_at: "2026-07-18T01:00:00+00:00",
      limitations: ["LOCKED_HOLDOUT_PENDING"],
    },
    validationMetrics: [{
      fold_number: 1,
      metric_name: "NDCG@10",
      metric_value: "0.42",
      metric_payload: {},
    }],
    backtests: [{
      cost_scenario: "BASE",
      cost_multiplier: "1.0",
      status: "RESEARCH_ONLY",
      summary_metrics: { turnover: 0.2 },
      completed_at: "2026-07-18T01:00:00+00:00",
    }],
    validationLinkStatus: "LINKED",
    calendarObservations: [],
  };
}

function prediction(
  stockPredictionId: number,
  securityId: number,
  decision: "CANDIDATE" | "NO_TRADE" | null,
  decisionPolicyStatus:
    | "EVALUATED"
    | "MISSING_REQUIRED_DATA"
    | "VALIDATION_FAILED"
    | "HARD_FAIL"
    | null,
  quality: "PASS" | "FAIL",
  rank: number,
) {
  return {
    stock_prediction_id: stockPredictionId,
    prediction_run_id: 7,
    security_id: securityId,
    market: "TWSE" as const,
    industry: "半導體業",
    rank_score: String(101 - rank),
    global_rank: rank,
    global_rank_percentile: String((101 - rank) / 100),
    industry_rank: rank,
    industry_rank_percentile: String((101 - rank) / 100),
    calibrated_p_up: "0.60",
    calibrated_p_neutral: "0.25",
    calibrated_p_down: "0.15",
    calibration_version: "research-cal-v1",
    gross_q10: "-0.02",
    gross_q50: "0.02",
    gross_q90: "0.06",
    net_q10: "-0.03",
    net_q50: "0.01",
    net_q90: "0.05",
    interval_width: "0.08",
    calibration_status: "RESEARCH_ONLY",
    forecast_volatility: "0.03",
    downside_risk: "0.02",
    adv20_ntd: "1000000000",
    maximum_order_notional_ntd: "10000000",
    market_regime: "UPTREND_NORMAL_VOL",
    market_exposure_cap: "0.60",
    estimated_round_trip_cost: "0.01",
    data_quality_status: quality,
    decision,
    decision_policy_status: decisionPolicyStatus,
    reason_codes: [],
  };
}
