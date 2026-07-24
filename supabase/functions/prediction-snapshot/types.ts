export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

export type JsonRecord = Record<string, JsonValue>;
export type MarketScope = "TWSE" | "TPEX";
export type Decision = "CANDIDATE" | "WATCH" | "NO_TRADE";
export type DecisionPolicyStatus =
  | "EVALUATED"
  | "MISSING_REQUIRED_DATA"
  | "VALIDATION_FAILED"
  | "HARD_FAIL";

export interface PredictionRunRow extends JsonRecord {
  prediction_run_id: number;
  as_of_date: string;
  decision_at: string;
  horizon: number;
  market_scope: MarketScope | null;
  model_bundle_version: string;
  feature_schema_hash: string;
  cost_profile_version: string;
  training_end_date: string;
  system_validation_status: "PASS" | "RESEARCH_ONLY" | "FAIL";
  source_dates: JsonRecord;
  latest_available_at: string;
  candidate_count: number;
  watch_count: number;
  no_trade_count: number;
  policy_input_missing_count: number | null;
  policy_validation_failed_count: number | null;
  policy_hard_fail_count: number | null;
  hard_fail_count: number;
  created_at: string;
}

export interface StockPredictionRow extends JsonRecord {
  stock_prediction_id: number;
  prediction_run_id: number;
  security_id: number;
  market: "TWSE" | "TPEX";
  industry: string | null;
  rank_score: number | string;
  global_rank: number;
  global_rank_percentile: number | string;
  industry_rank: number | null;
  industry_rank_percentile: number | string | null;
  calibrated_p_up: number | string;
  calibrated_p_neutral: number | string;
  calibrated_p_down: number | string;
  calibration_version: string;
  gross_q10: number | string;
  gross_q50: number | string;
  gross_q90: number | string;
  net_q10: number | string;
  net_q50: number | string;
  net_q90: number | string;
  interval_width: number | string;
  calibration_status: string;
  forecast_volatility: number | string | null;
  downside_risk: number | string | null;
  adv20_ntd: number | string | null;
  maximum_order_notional_ntd: number | string | null;
  market_regime: string | null;
  market_exposure_cap: number | string | null;
  estimated_round_trip_cost: number | string;
  data_quality_status: "PASS" | "WARN" | "FAIL" | "HARD_FAIL";
  decision: Decision | null;
  decision_policy_status: DecisionPolicyStatus | null;
  reason_codes: string[];
}

export interface SecurityRow extends JsonRecord {
  security_id: number;
  symbol: string;
  display_name: string;
  market: "TWSE" | "TPEX";
  asset_type: "COMMON_STOCK" | "ETF";
}

export interface SecurityHistoryRow extends JsonRecord {
  security_id: number;
  effective_from: string;
  effective_to: string | null;
  industry_code: string | null;
  industry_name: string | null;
  source_version: string;
  available_at: string;
}

export interface DataQualityAuditRow extends JsonRecord {
  security_id: number;
  quality_status: "PASS" | "FAIL";
  hard_fail: boolean;
  reason_codes: string[];
  source_dates: JsonRecord;
  latest_available_at: string | null;
}

export interface DecisionGateRow extends JsonRecord {
  stock_prediction_id: number;
  gate_order: number;
  gate_name: string;
  passed: boolean;
  actual_value: JsonValue;
  threshold_value: JsonValue;
  reason_code: string;
}

export interface MarketPredictionRow extends JsonRecord {
  market: "TWSE" | "TPEX";
  calibrated_p_up: number | string;
  calibrated_p_neutral: number | string;
  calibrated_p_down: number | string;
  market_regime: string;
  forecast_market_volatility: number | string;
  market_exposure_cap: number | string;
  model_version: string;
  training_end_date: string;
}

export interface ValidationRunRow extends JsonRecord {
  validation_run_id: number;
  validation_status: "PASS" | "RESEARCH_ONLY" | "FAIL";
  locked_holdout: boolean;
  frozen_config_hash: string;
  started_at: string;
  completed_at: string | null;
  limitations: string[];
}

export interface ValidationMetricRow extends JsonRecord {
  fold_number: number;
  metric_name: string;
  metric_value: number | string | null;
  metric_payload: JsonRecord;
}

export interface BacktestRunRow extends JsonRecord {
  cost_scenario: string;
  cost_multiplier: number | string;
  status: "PASS" | "RESEARCH_ONLY" | "FAIL";
  summary_metrics: JsonRecord;
  completed_at: string | null;
}

export interface TradingCalendarObservationRow extends JsonRecord {
  market: MarketScope;
  trading_date: string;
  is_trading_day: boolean;
  decision_data_cutoff_at: string | null;
  calendar_verification_status: "VERIFIED";
  market_basis: "SOURCE_ASSERTED";
  available_at: string;
  usage_scope: "POINT_IN_TIME_CALENDAR";
  system_status: "PASS";
}

export interface SnapshotRows {
  run: PredictionRunRow;
  predictions: StockPredictionRow[];
  securities: SecurityRow[];
  currentSecurityHistory: SecurityHistoryRow[];
  audits: DataQualityAuditRow[];
  gates: DecisionGateRow[];
  markets: MarketPredictionRow[];
  validationRun: ValidationRunRow | null;
  validationMetrics: ValidationMetricRow[];
  backtests: BacktestRunRow[];
  validationLinkStatus: "LINKED" | "MISSING" | "AMBIGUOUS";
  calendarObservations: TradingCalendarObservationRow[];
}

export interface SnapshotRepositoryContract {
  loadLatest(
    horizon: number,
    marketScope: MarketScope,
    signal?: AbortSignal,
    observedAt?: Date,
  ): Promise<SnapshotRows | null>;
}
