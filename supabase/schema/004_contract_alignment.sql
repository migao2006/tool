begin;

-- Required for a concurrency-safe exclusion constraint over effective-dated
-- security-master rows. Supabase installs extensions in the extensions schema.
create extension if not exists btree_gist with schema extensions;
set local search_path = pg_catalog, public, extensions;

-- MARKET CONTRACT ---------------------------------------------------------
-- Exchange venue and asset type are separate concepts. Existing ETF rows
-- must first be assigned their real TWSE/TPEX venue; guessing is forbidden.
do $migration$
begin
  if exists (select 1 from market_data.securities where market = 'ETF') then
    raise exception using
      errcode = '23514',
      message = 'Cannot align securities.market: resolve existing ETF rows to TWSE or TPEX first';
  end if;
  if exists (select 1 from market_data.benchmark_definitions where market = 'ETF') then
    raise exception using
      errcode = '23514',
      message = 'Cannot align benchmark_definitions.market: resolve existing ETF rows first';
  end if;
end
$migration$;

alter table market_data.securities
  drop constraint if exists securities_market_check;
alter table market_data.securities
  add constraint securities_market_check check (market in ('TWSE', 'TPEX'));

alter table market_data.benchmark_definitions
  drop constraint if exists benchmark_definitions_market_check;
alter table market_data.benchmark_definitions
  add constraint benchmark_definitions_market_check check (market in ('TWSE', 'TPEX'));

-- POINT-IN-TIME SECURITY MASTER ------------------------------------------
-- effective_to is exclusive, matching the Python SecurityMaster contract.
alter table market_data.security_history
  drop constraint if exists security_history_check;
alter table market_data.security_history
  drop constraint if exists security_history_effective_range_check;
alter table market_data.security_history
  add constraint security_history_effective_range_check
    check (effective_to is null or effective_to > effective_from);

alter table market_data.security_history
  drop constraint if exists security_history_no_overlapping_ranges;
alter table market_data.security_history
  add constraint security_history_no_overlapping_ranges
  exclude using gist (
    security_id with =,
    source_id with =,
    source_version with =,
    daterange(effective_from, effective_to, '[)') with &&
  );

comment on column market_data.security_history.effective_to is
  'Exclusive upper bound. Null means the version remains effective indefinitely.';

-- JSON MAP CONTRACTS ------------------------------------------------------
-- These columns are consumed as mappings by Python and must not contain a
-- scalar or array. decision_gate actual/threshold values intentionally remain
-- unrestricted JSON because individual gates may emit scalars.
alter table market_data.benchmark_definitions
  drop constraint if exists benchmark_definitions_metadata_object_check;
alter table market_data.benchmark_definitions
  add constraint benchmark_definitions_metadata_object_check
    check (jsonb_typeof(metadata) = 'object');

alter table market_data.feature_definitions
  drop constraint if exists feature_definitions_source_rules_object_check;
alter table market_data.feature_definitions
  add constraint feature_definitions_source_rules_object_check
    check (jsonb_typeof(source_rules) = 'object');

alter table market_data.feature_snapshots
  drop constraint if exists feature_snapshots_feature_values_object_check;
alter table market_data.feature_snapshots
  add constraint feature_snapshots_feature_values_object_check
    check (jsonb_typeof(feature_values) = 'object');
alter table market_data.feature_snapshots
  drop constraint if exists feature_snapshots_missing_indicators_object_check;
alter table market_data.feature_snapshots
  add constraint feature_snapshots_missing_indicators_object_check
    check (jsonb_typeof(missing_indicators) = 'object');
alter table market_data.feature_snapshots
  drop constraint if exists feature_snapshots_source_dates_object_check;
alter table market_data.feature_snapshots
  add constraint feature_snapshots_source_dates_object_check
    check (jsonb_typeof(source_dates) = 'object');

alter table market_data.model_registry
  drop constraint if exists model_registry_metadata_object_check;
alter table market_data.model_registry
  add constraint model_registry_metadata_object_check
    check (jsonb_typeof(metadata) = 'object');

alter table market_data.prediction_runs
  drop constraint if exists prediction_runs_benchmark_versions_object_check;
alter table market_data.prediction_runs
  add constraint prediction_runs_benchmark_versions_object_check
    check (jsonb_typeof(benchmark_versions) = 'object');
alter table market_data.prediction_runs
  drop constraint if exists prediction_runs_source_dates_object_check;
alter table market_data.prediction_runs
  add constraint prediction_runs_source_dates_object_check
    check (jsonb_typeof(source_dates) = 'object');
alter table market_data.prediction_runs
  drop constraint if exists prediction_runs_nonnegative_counts_check;
alter table market_data.prediction_runs
  add constraint prediction_runs_nonnegative_counts_check check (
    candidate_count >= 0
    and watch_count >= 0
    and no_trade_count >= 0
    and hard_fail_count >= 0
  );

-- COST PROFILE CONTRACT ---------------------------------------------------
alter table market_data.cost_profiles
  drop constraint if exists cost_profiles_asset_type_check;
alter table market_data.cost_profiles
  drop constraint if exists cost_profiles_fee_parameters_check;
alter table market_data.cost_profiles
  drop constraint if exists cost_profiles_execution_parameters_check;
alter table market_data.cost_profiles
  drop constraint if exists cost_profiles_parameters_object_check;
alter table market_data.cost_profiles
  add constraint cost_profiles_asset_type_check
    check (asset_type in ('COMMON_STOCK', 'ETF'));
alter table market_data.cost_profiles
  add constraint cost_profiles_fee_parameters_check check (
    commission_rate >= 0 and commission_rate <= 1
    and commission_discount > 0 and commission_discount <= 1
    and minimum_fee >= 0
    and sell_tax_rate >= 0 and sell_tax_rate <= 1
  );
alter table market_data.cost_profiles
  add constraint cost_profiles_execution_parameters_check check (
    btrim(cost_profile_version) <> ''
    and estimated_order_notional_ntd > 0
    and btrim(spread_model) <> ''
    and upper(slippage_scenario) in ('LOW', 'BASE', 'STRESSED', 'EXTREME')
    and market_impact_parameter >= 0
    and max_adv_participation > 0 and max_adv_participation <= 1
  );
alter table market_data.cost_profiles
  add constraint cost_profiles_parameters_object_check
    check (jsonb_typeof(parameters) = 'object');

-- DATA QUALITY CONTRACT ---------------------------------------------------
alter table market_data.data_quality_audits
  add column if not exists quality_status text;
alter table market_data.data_quality_audits
  add column if not exists hard_fail boolean;

update market_data.data_quality_audits
set quality_status = case when quality_pass then 'PASS' else 'FAIL' end
where quality_status is null;

update market_data.data_quality_audits
set hard_fail = not quality_pass
where hard_fail is null;

alter table market_data.data_quality_audits
  alter column quality_status set not null,
  alter column hard_fail set not null,
  alter column latest_available_at drop not null;

alter table market_data.data_quality_audits
  drop constraint if exists data_quality_audits_quality_status_check;
alter table market_data.data_quality_audits
  drop constraint if exists data_quality_audits_freshness_check;
alter table market_data.data_quality_audits
  drop constraint if exists data_quality_audits_status_consistency_check;
alter table market_data.data_quality_audits
  drop constraint if exists data_quality_audits_freshness_timestamp_check;
alter table market_data.data_quality_audits
  drop constraint if exists data_quality_audits_source_dates_object_check;
alter table market_data.data_quality_audits
  add constraint data_quality_audits_quality_status_check
    check (quality_status in ('PASS', 'FAIL'));
alter table market_data.data_quality_audits
  add constraint data_quality_audits_freshness_check
    check (freshness in ('FRESH', 'STALE', 'MISSING'));
alter table market_data.data_quality_audits
  add constraint data_quality_audits_status_consistency_check check (
    quality_pass = (quality_status = 'PASS')
    and (not hard_fail or not quality_pass)
    and (not quality_pass or freshness = 'FRESH')
  );
alter table market_data.data_quality_audits
  add constraint data_quality_audits_freshness_timestamp_check check (
    (freshness = 'MISSING' and latest_available_at is null)
    or (freshness <> 'MISSING' and latest_available_at is not null)
  );
alter table market_data.data_quality_audits
  add constraint data_quality_audits_source_dates_object_check
    check (jsonb_typeof(source_dates) = 'object');

do $migration$
begin
  if exists (
    select 1
    from market_data.data_quality_audits as audit
    join market_data.prediction_runs as run
      on run.prediction_run_id = audit.prediction_run_id
    where audit.latest_available_at > run.decision_at
  ) then
    raise exception using
      errcode = '23514',
      message = 'Existing data-quality audit exceeds its prediction decision_at';
  end if;
end
$migration$;

create or replace function market_data.enforce_data_quality_audit_time()
returns trigger
language plpgsql
set search_path = pg_catalog, market_data
as $function$
declare
  run_decision_at timestamptz;
begin
  select prediction_runs.decision_at
    into run_decision_at
  from market_data.prediction_runs
  where prediction_runs.prediction_run_id = new.prediction_run_id;

  if not found then
    raise exception using
      errcode = '23503',
      message = 'data_quality_audits references an unknown prediction_run_id';
  end if;

  if new.latest_available_at is not null
     and new.latest_available_at > run_decision_at then
    raise exception using
      errcode = '23514',
      message = 'data quality latest_available_at exceeds prediction decision_at';
  end if;
  return new;
end
$function$;

revoke all on function market_data.enforce_data_quality_audit_time()
  from public, anon, authenticated;
grant execute on function market_data.enforce_data_quality_audit_time()
  to service_role;

drop trigger if exists data_quality_audits_time_guard
  on market_data.data_quality_audits;
create trigger data_quality_audits_time_guard
before insert or update of prediction_run_id, latest_available_at
on market_data.data_quality_audits
for each row execute function market_data.enforce_data_quality_audit_time();

create or replace function market_data.enforce_prediction_run_audit_time()
returns trigger
language plpgsql
set search_path = pg_catalog, market_data
as $function$
begin
  if exists (
    select 1
    from market_data.data_quality_audits
    where data_quality_audits.prediction_run_id = new.prediction_run_id
      and data_quality_audits.latest_available_at > new.decision_at
  ) then
    raise exception using
      errcode = '23514',
      message = 'prediction decision_at would precede an attached data-quality audit';
  end if;
  return new;
end
$function$;

revoke all on function market_data.enforce_prediction_run_audit_time()
  from public, anon, authenticated;
grant execute on function market_data.enforce_prediction_run_audit_time()
  to service_role;

drop trigger if exists prediction_runs_audit_time_guard
  on market_data.prediction_runs;
create trigger prediction_runs_audit_time_guard
before update of decision_at
on market_data.prediction_runs
for each row execute function market_data.enforce_prediction_run_audit_time();

-- STOCK OUTPUT CONTRACT ---------------------------------------------------
alter table market_data.stock_predictions
  add column if not exists interval_width numeric(16,10);
update market_data.stock_predictions
set interval_width = net_q90 - net_q10
where interval_width is null;
alter table market_data.stock_predictions
  alter column interval_width set not null;

alter table market_data.stock_predictions
  drop constraint if exists stock_predictions_rank_contract_check;
alter table market_data.stock_predictions
  drop constraint if exists stock_predictions_interval_width_check;
alter table market_data.stock_predictions
  drop constraint if exists stock_predictions_nonnegative_risk_capacity_check;
alter table market_data.stock_predictions
  drop constraint if exists stock_predictions_data_quality_status_check;
alter table market_data.stock_predictions
  drop constraint if exists stock_predictions_decision_quality_check;
alter table market_data.stock_predictions
  add constraint stock_predictions_rank_contract_check check (
    (industry_rank is null or industry_rank > 0)
    and (industry_rank_percentile is null or industry_rank_percentile between 0 and 1)
    and abs(rank_score - (100 * global_rank_percentile)) <= 0.0001
  );
alter table market_data.stock_predictions
  add constraint stock_predictions_interval_width_check check (
    interval_width >= 0
    and abs(interval_width - (net_q90 - net_q10)) <= 0.00000001
  );
alter table market_data.stock_predictions
  add constraint stock_predictions_nonnegative_risk_capacity_check check (
    (forecast_volatility is null or forecast_volatility >= 0)
    and (downside_risk is null or downside_risk >= 0)
    and (adv20_ntd is null or adv20_ntd >= 0)
    and (maximum_order_notional_ntd is null or maximum_order_notional_ntd >= 0)
    and estimated_round_trip_cost >= 0
  );
alter table market_data.stock_predictions
  add constraint stock_predictions_data_quality_status_check
    check (data_quality_status in ('PASS', 'FAIL'));
alter table market_data.stock_predictions
  add constraint stock_predictions_decision_quality_check
    check (decision <> 'CANDIDATE' or data_quality_status = 'PASS');

comment on column market_data.stock_predictions.estimated_round_trip_cost is
  'Round-trip cost rate as a decimal fraction of entry notional, not a currency amount.';

create unique index if not exists stock_predictions_run_global_rank_uidx
  on market_data.stock_predictions (prediction_run_id, global_rank);
create unique index if not exists stock_predictions_run_industry_rank_uidx
  on market_data.stock_predictions (prediction_run_id, industry, industry_rank)
  where industry is not null and industry_rank is not null;

-- MARKET OUTPUT CONTRACT --------------------------------------------------
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

create index if not exists market_predictions_market_run_idx
  on market_data.market_predictions (market, prediction_run_id desc);
alter table market_data.market_predictions enable row level security;

-- VALIDATION AND BACKTEST CONTRACTS --------------------------------------
alter table market_data.validation_runs
  drop constraint if exists validation_runs_completed_at_check;
alter table market_data.validation_runs
  add constraint validation_runs_completed_at_check
    check (completed_at is null or completed_at >= started_at);

alter table market_data.validation_fold_metrics
  drop constraint if exists validation_fold_metrics_payload_object_check;
alter table market_data.validation_fold_metrics
  add constraint validation_fold_metrics_payload_object_check
    check (jsonb_typeof(metric_payload) = 'object');

alter table market_data.backtest_runs
  drop constraint if exists backtest_runs_cost_multiplier_check;
alter table market_data.backtest_runs
  drop constraint if exists backtest_runs_cost_scenario_multiplier_check;
alter table market_data.backtest_runs
  drop constraint if exists backtest_runs_summary_metrics_object_check;
alter table market_data.backtest_runs
  drop constraint if exists backtest_runs_completed_at_check;
alter table market_data.backtest_runs
  add constraint backtest_runs_cost_scenario_multiplier_check check (
    (cost_scenario = 'LOW' and cost_multiplier = 0.75)
    or (cost_scenario = 'BASE' and cost_multiplier = 1.0)
    or (cost_scenario = 'STRESSED' and cost_multiplier = 1.5)
    or (cost_scenario = 'EXTREME' and cost_multiplier = 2.0)
  );
alter table market_data.backtest_runs
  add constraint backtest_runs_summary_metrics_object_check
    check (jsonb_typeof(summary_metrics) = 'object');
alter table market_data.backtest_runs
  add constraint backtest_runs_completed_at_check
    check (completed_at is null or completed_at >= started_at);

alter table market_data.backtest_daily_results
  drop constraint if exists backtest_daily_results_numeric_ranges_check;
alter table market_data.backtest_daily_results
  add constraint backtest_daily_results_numeric_ranges_check check (
    equity >= 0
    and cash >= 0
    and turnover >= 0
    and transaction_cost >= 0
    and market_exposure between 0 and 1
    and holdings_count >= 0
  );

-- PRIVATE-SCHEMA SECURITY AND FUTURE OBJECT DEFAULTS ---------------------
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

commit;
