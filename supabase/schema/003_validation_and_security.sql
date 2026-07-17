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
  created_at timestamptz not null default now(),
  constraint validation_runs_completed_at_check
    check (completed_at is null or completed_at >= started_at)
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
  check (test_start <= test_end),
  constraint validation_fold_metrics_payload_object_check
    check (jsonb_typeof(metric_payload) = 'object')
);

create table if not exists market_data.backtest_runs (
  backtest_run_id bigint generated always as identity primary key,
  validation_run_id bigint references market_data.validation_runs(validation_run_id),
  horizon smallint not null check (horizon in (2, 3, 5, 10)),
  cost_profile_version text not null references market_data.cost_profiles(cost_profile_version),
  cost_scenario text not null check (cost_scenario in ('LOW', 'BASE', 'STRESSED', 'EXTREME')),
  cost_multiplier numeric(8,4) not null,
  started_at timestamptz not null,
  completed_at timestamptz,
  status text not null check (status in ('PASS', 'RESEARCH_ONLY', 'FAIL')),
  summary_metrics jsonb not null default '{}'::jsonb,
  constraint backtest_runs_cost_scenario_multiplier_check check (
    (cost_scenario = 'LOW' and cost_multiplier = 0.75)
    or (cost_scenario = 'BASE' and cost_multiplier = 1.0)
    or (cost_scenario = 'STRESSED' and cost_multiplier = 1.5)
    or (cost_scenario = 'EXTREME' and cost_multiplier = 2.0)
  ),
  constraint backtest_runs_summary_metrics_object_check
    check (jsonb_typeof(summary_metrics) = 'object'),
  constraint backtest_runs_completed_at_check
    check (completed_at is null or completed_at >= started_at)
);

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
  unique (backtest_run_id, trading_date),
  constraint backtest_daily_results_numeric_ranges_check check (
    equity >= 0
    and cash >= 0
    and turnover >= 0
    and transaction_cost >= 0
    and market_exposure between 0 and 1
    and holdings_count >= 0
  )
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
create unique index if not exists stock_predictions_run_global_rank_uidx
  on market_data.stock_predictions (prediction_run_id, global_rank);
create unique index if not exists stock_predictions_run_industry_rank_uidx
  on market_data.stock_predictions (prediction_run_id, industry, industry_rank)
  where industry is not null and industry_rank is not null;
create index if not exists stock_predictions_security_idx
  on market_data.stock_predictions (security_id, prediction_run_id desc);
create index if not exists stock_predictions_candidates_idx
  on market_data.stock_predictions (prediction_run_id, global_rank)
  where decision = 'CANDIDATE' and data_quality_status = 'PASS';
create index if not exists decision_gate_prediction_idx
  on market_data.decision_gate_results (stock_prediction_id, gate_order);
create index if not exists market_predictions_market_run_idx
  on market_data.market_predictions (market, prediction_run_id desc);
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
alter table market_data.market_predictions enable row level security;
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

alter default privileges in schema market_data
  revoke all on tables from public, anon, authenticated;
alter default privileges in schema market_data
  revoke all on sequences from public, anon, authenticated;
alter default privileges in schema market_data
  revoke execute on functions from public, anon, authenticated;
alter default privileges in schema market_data
  grant select, insert, update, delete on tables to service_role;
alter default privileges in schema market_data
  grant usage, select on sequences to service_role;
alter default privileges in schema market_data
  grant execute on functions to service_role;
