create table if not exists market_data.feature_definitions (
  feature_definition_id bigint generated always as identity primary key,
  feature_name text not null,
  feature_version text not null,
  formula text not null,
  source_rules jsonb not null,
  available_at_rule text not null,
  missing_value_policy text not null,
  is_critical boolean not null default false,
  created_at timestamptz not null default now(),
  unique (feature_name, feature_version),
  constraint feature_definitions_source_rules_object_check
    check (jsonb_typeof(source_rules) = 'object')
);

create table if not exists market_data.feature_snapshots (
  feature_snapshot_id bigint generated always as identity primary key,
  security_id bigint not null references market_data.securities(security_id),
  decision_date date not null,
  decision_at timestamptz not null,
  feature_schema_hash text not null,
  feature_values jsonb not null,
  missing_indicators jsonb not null default '{}'::jsonb,
  source_dates jsonb not null,
  latest_available_at timestamptz not null,
  point_in_time_audit_pass boolean not null,
  created_at timestamptz not null default now(),
  unique (security_id, decision_at, feature_schema_hash),
  check (latest_available_at <= decision_at),
  constraint feature_snapshots_feature_values_object_check
    check (jsonb_typeof(feature_values) = 'object'),
  constraint feature_snapshots_missing_indicators_object_check
    check (jsonb_typeof(missing_indicators) = 'object'),
  constraint feature_snapshots_source_dates_object_check
    check (jsonb_typeof(source_dates) = 'object')
);

create table if not exists market_data.cost_profiles (
  cost_profile_id bigint generated always as identity primary key,
  cost_profile_version text not null unique,
  asset_type text not null,
  commission_rate numeric(12,10) not null,
  commission_discount numeric(12,10) not null,
  minimum_fee numeric(16,4) not null,
  sell_tax_rate numeric(12,10) not null,
  estimated_order_notional_ntd numeric(20,4) not null,
  spread_model text not null,
  slippage_scenario text not null,
  market_impact_parameter numeric(16,10) not null,
  max_adv_participation numeric(12,10) not null,
  parameters jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  constraint cost_profiles_asset_type_check
    check (asset_type in ('COMMON_STOCK', 'ETF')),
  constraint cost_profiles_fee_parameters_check check (
    commission_rate >= 0 and commission_rate <= 1
    and commission_discount > 0 and commission_discount <= 1
    and minimum_fee >= 0
    and sell_tax_rate >= 0 and sell_tax_rate <= 1
  ),
  constraint cost_profiles_execution_parameters_check check (
    btrim(cost_profile_version) <> ''
    and estimated_order_notional_ntd > 0
    and btrim(spread_model) <> ''
    and upper(slippage_scenario) in ('LOW', 'BASE', 'STRESSED', 'EXTREME')
    and market_impact_parameter >= 0
    and max_adv_participation > 0 and max_adv_participation <= 1
  ),
  constraint cost_profiles_parameters_object_check
    check (jsonb_typeof(parameters) = 'object')
);

create table if not exists market_data.model_registry (
  model_id bigint generated always as identity primary key,
  model_family text not null check (
    model_family in ('RANK', 'DIRECTION', 'QUANTILE', 'MARKET_DIRECTION', 'MARKET_REGIME', 'VOLATILITY')
  ),
  horizon smallint not null check (horizon in (2, 3, 5, 10)),
  model_version text not null,
  feature_schema_hash text not null,
  benchmark_version text,
  cost_profile_version text references market_data.cost_profiles(cost_profile_version),
  training_end_date date not null,
  artifact_uri text not null,
  validation_status text not null check (validation_status in ('PASS', 'RESEARCH_ONLY', 'FAIL')),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (model_family, horizon, model_version),
  constraint model_registry_metadata_object_check
    check (jsonb_typeof(metadata) = 'object')
);

create table if not exists market_data.prediction_runs (
  prediction_run_id bigint generated always as identity primary key,
  as_of_date date not null,
  decision_at timestamptz not null,
  horizon smallint not null check (horizon in (2, 3, 5, 10)),
  model_bundle_version text not null,
  feature_schema_hash text not null,
  benchmark_versions jsonb not null,
  cost_profile_version text not null references market_data.cost_profiles(cost_profile_version),
  training_end_date date not null,
  system_validation_status text not null check (
    system_validation_status in ('PASS', 'RESEARCH_ONLY', 'FAIL')
  ),
  source_dates jsonb not null,
  latest_available_at timestamptz not null,
  candidate_count integer not null default 0,
  watch_count integer not null default 0,
  no_trade_count integer not null default 0,
  hard_fail_count integer not null default 0,
  created_at timestamptz not null default now(),
  unique (decision_at, horizon, model_bundle_version),
  check (latest_available_at <= decision_at),
  check (training_end_date < as_of_date),
  constraint prediction_runs_nonnegative_counts_check check (
    candidate_count >= 0
    and watch_count >= 0
    and no_trade_count >= 0
    and hard_fail_count >= 0
  ),
  constraint prediction_runs_benchmark_versions_object_check
    check (jsonb_typeof(benchmark_versions) = 'object'),
  constraint prediction_runs_source_dates_object_check
    check (jsonb_typeof(source_dates) = 'object')
);

create table if not exists market_data.data_quality_audits (
  data_quality_audit_id bigint generated always as identity primary key,
  prediction_run_id bigint not null references market_data.prediction_runs(prediction_run_id) on delete cascade,
  security_id bigint not null references market_data.securities(security_id),
  quality_pass boolean not null,
  quality_status text not null check (quality_status in ('PASS', 'FAIL')),
  hard_fail boolean not null,
  completeness_score numeric(8,6) not null,
  freshness text not null check (freshness in ('FRESH', 'STALE', 'MISSING')),
  reason_codes text[] not null default '{}',
  source_dates jsonb not null,
  latest_available_at timestamptz,
  created_at timestamptz not null default now(),
  unique (prediction_run_id, security_id),
  check (completeness_score >= 0 and completeness_score <= 1),
  constraint data_quality_audits_status_consistency_check check (
    quality_pass = (quality_status = 'PASS')
    and (not hard_fail or not quality_pass)
    and (not quality_pass or freshness = 'FRESH')
  ),
  constraint data_quality_audits_freshness_timestamp_check check (
    (freshness = 'MISSING' and latest_available_at is null)
    or (freshness <> 'MISSING' and latest_available_at is not null)
  ),
  constraint data_quality_audits_source_dates_object_check
    check (jsonb_typeof(source_dates) = 'object')
);

create table if not exists market_data.stock_predictions (
  stock_prediction_id bigint generated always as identity primary key,
  prediction_run_id bigint not null references market_data.prediction_runs(prediction_run_id) on delete cascade,
  security_id bigint not null references market_data.securities(security_id),
  market text not null check (market in ('TWSE', 'TPEX')),
  industry text,
  model_raw_score numeric(24,12) not null,
  rank_score numeric(10,6) not null,
  global_rank integer not null,
  global_rank_percentile numeric(10,8) not null,
  industry_rank integer,
  industry_rank_percentile numeric(10,8),
  calibrated_p_up numeric(10,8) not null,
  calibrated_p_neutral numeric(10,8) not null,
  calibrated_p_down numeric(10,8) not null,
  calibration_version text not null,
  gross_q10 numeric(16,10) not null,
  gross_q50 numeric(16,10) not null,
  gross_q90 numeric(16,10) not null,
  net_q10 numeric(16,10) not null,
  net_q50 numeric(16,10) not null,
  net_q90 numeric(16,10) not null,
  interval_width numeric(16,10) not null,
  quantile_crossing_before_calibration boolean not null,
  calibration_status text not null,
  forecast_volatility numeric(16,10),
  downside_risk numeric(16,10),
  adv20_ntd numeric(24,4),
  maximum_order_notional_ntd numeric(24,4),
  market_regime text,
  market_exposure_cap numeric(10,8),
  estimated_round_trip_cost numeric(16,10) not null,
  data_quality_status text not null check (data_quality_status in ('PASS', 'FAIL')),
  decision text not null check (decision in ('CANDIDATE', 'WATCH', 'NO_TRADE')),
  reason_codes text[] not null default '{}',
  created_at timestamptz not null default now(),
  unique (prediction_run_id, security_id),
  check (rank_score >= 0 and rank_score <= 100),
  check (global_rank > 0),
  check (global_rank_percentile >= 0 and global_rank_percentile <= 1),
  check (calibrated_p_up between 0 and 1),
  check (calibrated_p_neutral between 0 and 1),
  check (calibrated_p_down between 0 and 1),
  check (abs(calibrated_p_up + calibrated_p_neutral + calibrated_p_down - 1) <= 0.000001),
  check (gross_q10 <= gross_q50 and gross_q50 <= gross_q90),
  check (net_q10 <= net_q50 and net_q50 <= net_q90),
  check (market_exposure_cap is null or market_exposure_cap between 0 and 1),
  constraint stock_predictions_rank_contract_check check (
    (industry_rank is null or industry_rank > 0)
    and (industry_rank_percentile is null or industry_rank_percentile between 0 and 1)
    and abs(rank_score - (100 * global_rank_percentile)) <= 0.0001
  ),
  constraint stock_predictions_interval_width_check check (
    interval_width >= 0
    and abs(interval_width - (net_q90 - net_q10)) <= 0.00000001
  ),
  constraint stock_predictions_nonnegative_risk_capacity_check check (
    (forecast_volatility is null or forecast_volatility >= 0)
    and (downside_risk is null or downside_risk >= 0)
    and (adv20_ntd is null or adv20_ntd >= 0)
    and (maximum_order_notional_ntd is null or maximum_order_notional_ntd >= 0)
    and estimated_round_trip_cost >= 0
  ),
  constraint stock_predictions_decision_quality_check check (
    decision <> 'CANDIDATE' or data_quality_status = 'PASS'
  )
);

comment on column market_data.stock_predictions.estimated_round_trip_cost is
  'Round-trip cost rate as a decimal fraction of entry notional, not a currency amount.';

create table if not exists market_data.market_predictions (
  market_prediction_id bigint generated always as identity primary key,
  prediction_run_id bigint not null
    references market_data.prediction_runs(prediction_run_id) on delete cascade,
  market text not null check (market in ('TWSE', 'TPEX')),
  calibrated_p_up numeric(10,8) not null,
  calibrated_p_neutral numeric(10,8) not null,
  calibrated_p_down numeric(10,8) not null,
  market_regime text not null,
  forecast_market_volatility numeric(16,10) not null,
  market_exposure_cap numeric(10,8) not null,
  model_version text not null,
  training_end_date date not null,
  created_at timestamptz not null default now(),
  unique (prediction_run_id, market),
  check (calibrated_p_up between 0 and 1),
  check (calibrated_p_neutral between 0 and 1),
  check (calibrated_p_down between 0 and 1),
  check (
    abs(calibrated_p_up + calibrated_p_neutral + calibrated_p_down - 1)
      <= 0.000001
  ),
  check (forecast_market_volatility >= 0),
  check (market_exposure_cap between 0 and 1)
);

create table if not exists market_data.decision_gate_results (
  decision_gate_result_id bigint generated always as identity primary key,
  stock_prediction_id bigint not null references market_data.stock_predictions(stock_prediction_id) on delete cascade,
  gate_order smallint not null check (gate_order between 1 and 8),
  gate_name text not null,
  passed boolean not null,
  actual_value jsonb not null,
  threshold_value jsonb not null,
  reason_code text not null,
  unique (stock_prediction_id, gate_order)
);
