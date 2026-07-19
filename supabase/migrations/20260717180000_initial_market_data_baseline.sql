-- Fresh-database baseline only. Existing remote databases must mark this version

-- as applied after schema-equivalence verification; never re-run it remotely.

-- Fail closed before the first DDL when market_data already exists.

do $baseline_guard$
begin
  if exists (
    select 1
    from pg_catalog.pg_namespace
    where nspname = 'market_data'
  ) then
    raise exception using
      message = 'initial_market_data_baseline is only valid for an empty database',
      hint = 'Verify schema equivalence, then mark the baseline version as applied.';
  end if;
end
$baseline_guard$;

-- Source: f72decf:supabase/schema/001_market_facts.sql

create schema if not exists market_data;

create table if not exists market_data.data_sources (
  source_id bigint generated always as identity primary key,
  source_code text not null unique,
  display_name text not null,
  source_timezone text not null,
  revision_policy text not null,
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists market_data.trading_calendar (
  market text not null check (market in ('TWSE', 'TPEX', 'US')),
  trading_date date not null,
  is_trading_day boolean not null,
  opens_at timestamptz,
  closes_at timestamptz,
  decision_data_cutoff_at timestamptz,
  source_id bigint not null references market_data.data_sources(source_id),
  available_at timestamptz not null,
  ingested_at timestamptz not null default now(),
  primary key (market, trading_date)
);

create table if not exists market_data.securities (
  security_id bigint generated always as identity primary key,
  symbol text not null,
  display_name text not null,
  market text not null check (market in ('TWSE', 'TPEX', 'ETF')),
  asset_type text not null check (asset_type in ('COMMON_STOCK', 'ETF')),
  currency text not null default 'TWD',
  listing_date date,
  delisting_date date,
  isin text,
  source_id bigint not null references market_data.data_sources(source_id),
  created_at timestamptz not null default now(),
  unique (market, symbol),
  check (delisting_date is null or listing_date is null or delisting_date >= listing_date)
);

create table if not exists market_data.security_history (
  security_history_id bigint generated always as identity primary key,
  security_id bigint not null references market_data.securities(security_id),
  effective_from date not null,
  effective_to date,
  industry_code text,
  industry_name text,
  trading_status text not null,
  attention_flag boolean not null default false,
  disposal_flag boolean not null default false,
  altered_trading_method_flag boolean not null default false,
  full_cash_delivery_flag boolean not null default false,
  periodic_auction_flag boolean not null default false,
  suspended_flag boolean not null default false,
  source_id bigint not null references market_data.data_sources(source_id),
  source_version text not null,
  available_at timestamptz not null,
  ingested_at timestamptz not null default now(),
  unique (security_id, effective_from, source_id, source_version),
  check (effective_to is null or effective_to >= effective_from)
);

create table if not exists market_data.benchmark_definitions (
  benchmark_id bigint generated always as identity primary key,
  benchmark_code text not null,
  benchmark_version text not null,
  market text not null check (market in ('TWSE', 'TPEX', 'ETF')),
  index_symbol text not null,
  effective_from date not null,
  effective_to date,
  available_at timestamptz not null,
  metadata jsonb not null default '{}'::jsonb,
  unique (benchmark_code, benchmark_version),
  check (effective_to is null or effective_to >= effective_from)
);

create table if not exists market_data.daily_bars (
  daily_bar_id bigint generated always as identity primary key,
  security_id bigint not null references market_data.securities(security_id),
  trade_date date not null,
  raw_open numeric(20,6),
  raw_high numeric(20,6),
  raw_low numeric(20,6),
  raw_close numeric(20,6),
  volume_shares numeric(24,4),
  turnover_ntd numeric(24,4),
  trade_count bigint,
  adjustment_factor numeric(24,12),
  cash_dividend_per_share numeric(20,8) not null default 0,
  company_action_complete boolean not null default false,
  opening_trade_available boolean not null default false,
  closing_trade_available boolean not null default false,
  limit_up_price numeric(20,6),
  limit_down_price numeric(20,6),
  best_bid numeric(20,6),
  best_ask numeric(20,6),
  source_id bigint not null references market_data.data_sources(source_id),
  source_version text not null,
  available_at timestamptz not null,
  ingested_at timestamptz not null default now(),
  unique (security_id, trade_date, source_id, source_version),
  check (raw_high is null or raw_low is null or raw_high >= raw_low),
  check (volume_shares is null or volume_shares >= 0),
  check (turnover_ntd is null or turnover_ntd >= 0)
);

create table if not exists market_data.corporate_actions (
  corporate_action_id bigint generated always as identity primary key,
  security_id bigint not null references market_data.securities(security_id),
  action_type text not null check (
    action_type in ('CASH_DIVIDEND', 'STOCK_DIVIDEND', 'SPLIT', 'CAPITAL_REDUCTION', 'RIGHTS', 'OTHER')
  ),
  ex_date date not null,
  payable_date date,
  cash_amount_per_share numeric(20,8),
  share_ratio numeric(20,10),
  reference_price_adjustment numeric(20,8),
  announced_at timestamptz not null,
  available_at timestamptz not null,
  source_id bigint not null references market_data.data_sources(source_id),
  source_version text not null,
  ingested_at timestamptz not null default now(),
  unique (security_id, action_type, ex_date, source_id, source_version),
  check (available_at >= announced_at)
);

create table if not exists market_data.institutional_flows (
  institutional_flow_id bigint generated always as identity primary key,
  security_id bigint not null references market_data.securities(security_id),
  trade_date date not null,
  foreign_net_shares numeric(24,4),
  investment_trust_net_shares numeric(24,4),
  dealer_net_shares numeric(24,4),
  foreign_holding_ratio numeric(12,8),
  source_id bigint not null references market_data.data_sources(source_id),
  source_version text not null,
  available_at timestamptz not null,
  ingested_at timestamptz not null default now(),
  unique (security_id, trade_date, source_id, source_version)
);

create table if not exists market_data.financing_short_facts (
  financing_short_id bigint generated always as identity primary key,
  security_id bigint not null references market_data.securities(security_id),
  trade_date date not null,
  margin_balance_shares numeric(24,4),
  margin_change_shares numeric(24,4),
  short_balance_shares numeric(24,4),
  short_change_shares numeric(24,4),
  borrowed_sell_shares numeric(24,4),
  source_id bigint not null references market_data.data_sources(source_id),
  source_version text not null,
  available_at timestamptz not null,
  ingested_at timestamptz not null default now(),
  unique (security_id, trade_date, source_id, source_version)
);

create table if not exists market_data.market_observations (
  market_observation_id bigint generated always as identity primary key,
  series_code text not null,
  observation_at timestamptz not null,
  numeric_value numeric(24,10),
  text_value text,
  source_id bigint not null references market_data.data_sources(source_id),
  source_version text not null,
  available_at timestamptz not null,
  ingested_at timestamptz not null default now(),
  unique (series_code, observation_at, source_id, source_version),
  check (numeric_value is not null or text_value is not null)
);

-- Source: f72decf:supabase/schema/002_research_outputs.sql

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
  unique (feature_name, feature_version)
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
  check (latest_available_at <= decision_at)
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
  check (commission_rate >= 0 and commission_discount >= 0),
  check (minimum_fee >= 0 and sell_tax_rate >= 0),
  check (max_adv_participation > 0 and max_adv_participation <= 1)
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
  unique (model_family, horizon, model_version)
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
  check (training_end_date < as_of_date)
);

create table if not exists market_data.data_quality_audits (
  data_quality_audit_id bigint generated always as identity primary key,
  prediction_run_id bigint not null references market_data.prediction_runs(prediction_run_id) on delete cascade,
  security_id bigint not null references market_data.securities(security_id),
  quality_pass boolean not null,
  completeness_score numeric(8,6) not null,
  freshness text not null,
  reason_codes text[] not null default '{}',
  source_dates jsonb not null,
  latest_available_at timestamptz not null,
  created_at timestamptz not null default now(),
  unique (prediction_run_id, security_id),
  check (completeness_score >= 0 and completeness_score <= 1)
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
  quantile_crossing_before_calibration boolean not null,
  calibration_status text not null,
  forecast_volatility numeric(16,10),
  downside_risk numeric(16,10),
  adv20_ntd numeric(24,4),
  maximum_order_notional_ntd numeric(24,4),
  market_regime text,
  market_exposure_cap numeric(10,8),
  estimated_round_trip_cost numeric(16,10) not null,
  data_quality_status text not null,
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
  check (market_exposure_cap is null or market_exposure_cap between 0 and 1)
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

-- Source: f72decf:supabase/schema/003_validation_and_security.sql,
-- adapted to the actual pre-migration remote column order.

create table if not exists market_data.validation_runs (
  validation_run_id bigint generated always as identity primary key,
  model_bundle_version text not null,
  horizon smallint not null check (horizon in (2, 3, 5, 10)),
  validation_status text not null check (validation_status in ('PASS', 'RESEARCH_ONLY', 'FAIL')),
  locked_holdout boolean not null default false,
  frozen_config_hash text not null,
  started_at timestamptz not null,
  completed_at timestamptz,
  limitations text[] not null default '{}',
  created_at timestamptz not null default now()
);

create table if not exists market_data.validation_fold_metrics (
  validation_fold_metric_id bigint generated always as identity primary key,
  validation_run_id bigint not null references market_data.validation_runs(validation_run_id) on delete cascade,
  fold_number integer not null,
  train_start date not null,
  train_end date not null,
  calibration_start date not null,
  calibration_end date not null,
  test_start date not null,
  test_end date not null,
  metric_name text not null,
  metric_value numeric(24,12),
  metric_payload jsonb not null default '{}'::jsonb,
  unique (validation_run_id, fold_number, metric_name),
  check (train_start <= train_end),
  check (train_end < calibration_start),
  check (calibration_start <= calibration_end),
  check (calibration_end < test_start),
  check (test_start <= test_end)
);

create table if not exists market_data.backtest_runs (
  backtest_run_id bigint generated always as identity primary key,
  validation_run_id bigint references market_data.validation_runs(validation_run_id),
  horizon smallint not null check (horizon in (2, 3, 5, 10)),
  cost_profile_version text not null references market_data.cost_profiles(cost_profile_version),
  cost_multiplier numeric(8,4) not null,
  started_at timestamptz not null,
  completed_at timestamptz,
  status text not null check (status in ('PASS', 'RESEARCH_ONLY', 'FAIL')),
  summary_metrics jsonb not null default '{}'::jsonb,
  check (cost_multiplier in (0.75, 1.0, 1.5, 2.0))
);

-- This column existed before the recorded remote migration history but was
-- added after the original table definition, so it must remain attnum 10.
alter table market_data.backtest_runs
  add column cost_scenario text not null
  check (cost_scenario in ('LOW', 'BASE', 'STRESSED', 'EXTREME'));

create table if not exists market_data.backtest_daily_results (
  backtest_daily_result_id bigint generated always as identity primary key,
  backtest_run_id bigint not null references market_data.backtest_runs(backtest_run_id) on delete cascade,
  trading_date date not null,
  gross_return numeric(16,10) not null,
  net_return numeric(16,10) not null,
  equity numeric(24,10) not null,
  cash numeric(24,4) not null,
  turnover numeric(16,10) not null,
  transaction_cost numeric(24,8) not null,
  market_exposure numeric(12,10) not null,
  market_regime text,
  holdings_count integer not null,
  unique (backtest_run_id, trading_date)
);

create index if not exists trading_calendar_available_idx
  on market_data.trading_calendar (market, available_at);
create index if not exists trading_calendar_source_idx
  on market_data.trading_calendar (source_id);
create index if not exists securities_source_idx
  on market_data.securities (source_id);
create index if not exists security_history_point_in_time_idx
  on market_data.security_history (security_id, effective_from, effective_to, available_at desc);
create index if not exists security_history_source_idx
  on market_data.security_history (source_id);
create index if not exists daily_bars_security_date_idx
  on market_data.daily_bars (security_id, trade_date desc, available_at desc);
create index if not exists daily_bars_cross_section_idx
  on market_data.daily_bars (trade_date, available_at);
create index if not exists daily_bars_source_idx
  on market_data.daily_bars (source_id);
create index if not exists corporate_actions_security_date_idx
  on market_data.corporate_actions (security_id, ex_date, available_at);
create index if not exists corporate_actions_source_idx
  on market_data.corporate_actions (source_id);
create index if not exists institutional_flows_security_date_idx
  on market_data.institutional_flows (security_id, trade_date desc, available_at desc);
create index if not exists institutional_flows_source_idx
  on market_data.institutional_flows (source_id);
create index if not exists financing_short_security_date_idx
  on market_data.financing_short_facts (security_id, trade_date desc, available_at desc);
create index if not exists financing_short_source_idx
  on market_data.financing_short_facts (source_id);
create index if not exists market_observations_point_in_time_idx
  on market_data.market_observations (series_code, observation_at desc, available_at desc);
create index if not exists market_observations_source_idx
  on market_data.market_observations (source_id);
create index if not exists feature_snapshots_decision_idx
  on market_data.feature_snapshots (decision_date, decision_at, security_id);
create index if not exists feature_snapshots_security_idx
  on market_data.feature_snapshots (security_id, decision_at desc);
create index if not exists model_registry_lookup_idx
  on market_data.model_registry (model_family, horizon, validation_status, training_end_date desc);
create index if not exists model_registry_cost_profile_idx
  on market_data.model_registry (cost_profile_version);
create index if not exists prediction_runs_lookup_idx
  on market_data.prediction_runs (horizon, as_of_date desc, system_validation_status);
create index if not exists prediction_runs_cost_profile_idx
  on market_data.prediction_runs (cost_profile_version);
create index if not exists data_quality_security_idx
  on market_data.data_quality_audits (security_id, prediction_run_id);
create index if not exists stock_predictions_rank_idx
  on market_data.stock_predictions (prediction_run_id, global_rank);
create index if not exists stock_predictions_security_idx
  on market_data.stock_predictions (security_id, prediction_run_id desc);
create index if not exists stock_predictions_candidates_idx
  on market_data.stock_predictions (prediction_run_id, global_rank)
  where decision = 'CANDIDATE' and data_quality_status = 'PASS';
create index if not exists decision_gate_prediction_idx
  on market_data.decision_gate_results (stock_prediction_id, gate_order);
create index if not exists validation_fold_run_idx
  on market_data.validation_fold_metrics (validation_run_id, fold_number);
create index if not exists backtest_daily_run_idx
  on market_data.backtest_daily_results (backtest_run_id, trading_date);
create index if not exists backtest_runs_validation_idx
  on market_data.backtest_runs (validation_run_id);
create index if not exists backtest_runs_cost_profile_idx
  on market_data.backtest_runs (cost_profile_version);

alter table market_data.data_sources enable row level security;
alter table market_data.trading_calendar enable row level security;
alter table market_data.securities enable row level security;
alter table market_data.security_history enable row level security;
alter table market_data.benchmark_definitions enable row level security;
alter table market_data.daily_bars enable row level security;
alter table market_data.corporate_actions enable row level security;
alter table market_data.institutional_flows enable row level security;
alter table market_data.financing_short_facts enable row level security;
alter table market_data.market_observations enable row level security;
alter table market_data.feature_definitions enable row level security;
alter table market_data.feature_snapshots enable row level security;
alter table market_data.cost_profiles enable row level security;
alter table market_data.model_registry enable row level security;
alter table market_data.prediction_runs enable row level security;
alter table market_data.data_quality_audits enable row level security;
alter table market_data.stock_predictions enable row level security;
alter table market_data.decision_gate_results enable row level security;
alter table market_data.validation_runs enable row level security;
alter table market_data.validation_fold_metrics enable row level security;
alter table market_data.backtest_runs enable row level security;
alter table market_data.backtest_daily_results enable row level security;

revoke all on schema market_data from public, anon, authenticated;
revoke all on all tables in schema market_data from public, anon, authenticated;
revoke all on all sequences in schema market_data from public, anon, authenticated;
grant usage on schema market_data to service_role;
grant select, insert, update, delete on all tables in schema market_data to service_role;
grant usage, select on all sequences in schema market_data to service_role;

-- Source: supabase/schema/005_data_api_service_role.sql

begin;

-- Register the research schema with PostgREST while keeping browser roles blocked.
alter role authenticator
  set pgrst.db_schemas = 'public, graphql_public, market_data';

revoke all on schema market_data from public, anon, authenticated;
revoke all on all tables in schema market_data from public, anon, authenticated;
revoke all on all sequences in schema market_data from public, anon, authenticated;

grant usage on schema market_data to service_role;
grant select, insert, update, delete on all tables in schema market_data to service_role;
grant usage, select on all sequences in schema market_data to service_role;

commit;

notify pgrst, 'reload config';
notify pgrst, 'reload schema';
