begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

alter table market_data.prediction_runs
add column market_scope text;

-- Existing runs predate market_scope. Fail closed unless every run can be
-- proven to be TWSE from its persisted stock children. A run without stock
-- children is not evidence and must be resolved manually before migration.
do $backfill$
begin
  if exists (
    select 1
    from market_data.prediction_runs as run
    where not exists (
      select 1
      from market_data.stock_predictions as prediction
      where prediction.prediction_run_id = run.prediction_run_id
    )
  ) then
    raise exception using
      errcode = '23514',
      message = 'UNPROVEN_LEGACY_PREDICTION_RUN_MARKET_SCOPE';
  end if;

  if exists (
    select 1
    from market_data.stock_predictions as prediction
    where prediction.market is distinct from 'TWSE'
  ) or exists (
    select 1
    from market_data.market_predictions as prediction
    where prediction.market is distinct from 'TWSE'
  ) then
    raise exception using
      errcode = '23514',
      message = 'LEGACY_PREDICTION_CHILD_MARKET_IS_NOT_TWSE';
  end if;

  update market_data.prediction_runs
  set market_scope = 'TWSE'
  where market_scope is null;
end
$backfill$;

alter table market_data.prediction_runs
alter column market_scope set not null;

alter table market_data.prediction_runs
add constraint prediction_runs_market_scope_check
check (market_scope in ('TWSE', 'TPEX'));

alter table market_data.prediction_runs
drop constraint
if exists prediction_runs_decision_at_horizon_model_bundle_version_key;

alter table market_data.prediction_runs
add constraint prediction_runs_market_identity_key unique (
    market_scope,
    decision_at,
    horizon,
    model_bundle_version
);

-- A transaction-scoped migration cannot create an index concurrently.
-- noqa: disable=PG01
create index prediction_runs_market_stale_lookup_idx
on market_data.prediction_runs (
    market_scope,
    horizon,
    decision_at desc
);
-- noqa: enable=PG01

comment on column market_data.prediction_runs.market_scope is
'Exact ordinary-stock prediction universe: TWSE or TPEX. ETF is excluded.';

create or replace function market_data.enforce_prediction_child_market_scope()
returns trigger
language plpgsql
security invoker
set search_path = pg_catalog, market_data
as $function$
declare
  v_market_scope text;
begin
  select run.market_scope
    into v_market_scope
  from market_data.prediction_runs as run
  where run.prediction_run_id = new.prediction_run_id;

  if not found then
    raise exception using
      errcode = '23503',
      message = 'PREDICTION_CHILD_REFERENCES_UNKNOWN_RUN';
  end if;

  if new.market is distinct from v_market_scope then
    raise exception using
      errcode = '23514',
      message = 'PREDICTION_CHILD_MARKET_SCOPE_MISMATCH';
  end if;

  return new;
end
$function$;

revoke all on function market_data.enforce_prediction_child_market_scope()
from public, anon, authenticated;
grant execute on function market_data.enforce_prediction_child_market_scope()
to service_role;

drop trigger if exists stock_predictions_market_scope_guard
on market_data.stock_predictions;
create trigger stock_predictions_market_scope_guard
before insert or update of prediction_run_id, market
on market_data.stock_predictions
for each row
execute function market_data.enforce_prediction_child_market_scope();

drop trigger if exists market_predictions_market_scope_guard
on market_data.market_predictions;
create trigger market_predictions_market_scope_guard
before insert or update of prediction_run_id, market
on market_data.market_predictions
for each row
execute function market_data.enforce_prediction_child_market_scope();

create or replace function
market_data.enforce_prediction_run_market_scope_immutable()
returns trigger
language plpgsql
security invoker
set search_path = pg_catalog, market_data
as $function$
begin
  if new.market_scope is distinct from old.market_scope then
    raise exception using
      errcode = '23514',
      message = 'PREDICTION_RUN_MARKET_SCOPE_IS_IMMUTABLE';
  end if;
  return new;
end
$function$;

revoke all on function
market_data.enforce_prediction_run_market_scope_immutable()
from public, anon, authenticated;
grant execute on function
market_data.enforce_prediction_run_market_scope_immutable()
to service_role;

create trigger prediction_runs_market_scope_immutable_guard
before update of market_scope
on market_data.prediction_runs
for each row
execute function market_data.enforce_prediction_run_market_scope_immutable();

-- Keep the exact pre-migration implementation available for an audited
-- rollback, but make it unreachable while the market-scoped RPC is active.
alter function market_data.publish_research_prediction_snapshot(jsonb, jsonb)
rename to publish_research_prediction_snapshot_twse_v1;
revoke all on function
market_data.publish_research_prediction_snapshot_twse_v1(jsonb, jsonb)
from public, anon, authenticated, service_role;

create or replace function market_data.publish_research_prediction_snapshot(
    p_run jsonb,
    p_stock_predictions jsonb
)
returns jsonb
language plpgsql
security invoker
set search_path = pg_catalog, market_data
as $function$
declare
  v_as_of_date date;
  v_decision_at timestamptz;
  v_horizon smallint;
  v_market_scope text;
  v_model_bundle_version text;
  v_feature_schema_hash text;
  v_benchmark_versions jsonb;
  v_cost_profile_version text;
  v_training_end_date date;
  v_source_dates jsonb;
  v_latest_available_at timestamptz;
  v_expected_count integer;
  v_distinct_security_count integer;
  v_distinct_rank_count integer;
  v_actual_count integer;
  v_latest_decision_at timestamptz;
  v_prediction_run_id bigint;
  v_existing_source_dates jsonb;
  v_existing_run boolean := false;
begin
  if jsonb_typeof(p_run) is distinct from 'object' then
    raise exception using
      errcode = '22023',
      message = 'RESEARCH_PREDICTION_RUN_MUST_BE_OBJECT';
  end if;
  if jsonb_typeof(p_stock_predictions) is distinct from 'array'
     or jsonb_array_length(p_stock_predictions) = 0 then
    raise exception using
      errcode = '22023',
      message = 'RESEARCH_PREDICTION_ROWS_MUST_BE_NONEMPTY_ARRAY';
  end if;
  if exists (
    select 1
    from jsonb_array_elements(p_stock_predictions) as item(value)
    where jsonb_typeof(item.value) is distinct from 'object'
  ) then
    raise exception using
      errcode = '22023',
      message = 'RESEARCH_PREDICTION_ROW_MUST_BE_OBJECT';
  end if;

  v_as_of_date := nullif(p_run ->> 'as_of_date', '')::date;
  v_decision_at := nullif(p_run ->> 'decision_at', '')::timestamptz;
  v_horizon := nullif(p_run ->> 'horizon', '')::smallint;
  -- Omitted scope remains TWSE for the already deployed publisher payload.
  -- TPEX never defaults: it must be supplied explicitly as market_scope=TPEX.
  v_market_scope := coalesce(nullif(p_run ->> 'market_scope', ''), 'TWSE');
  v_model_bundle_version := nullif(p_run ->> 'model_bundle_version', '');
  v_feature_schema_hash := nullif(p_run ->> 'feature_schema_hash', '');
  v_benchmark_versions := p_run -> 'benchmark_versions';
  v_cost_profile_version := nullif(p_run ->> 'cost_profile_version', '');
  v_training_end_date := nullif(p_run ->> 'training_end_date', '')::date;
  v_source_dates := p_run -> 'source_dates';
  v_latest_available_at := nullif(
    p_run ->> 'latest_available_at',
    ''
  )::timestamptz;
  v_expected_count := jsonb_array_length(p_stock_predictions);

  if v_as_of_date is null
     or v_decision_at is null
     or v_horizon is distinct from 5
     or v_market_scope not in ('TWSE', 'TPEX')
     or v_model_bundle_version is null
     or v_feature_schema_hash is null
     or v_cost_profile_version is null
     or v_training_end_date is null
     or v_latest_available_at is null
     or p_run ->> 'system_validation_status' is distinct from 'RESEARCH_ONLY'
     or jsonb_typeof(v_benchmark_versions) is distinct from 'object'
     or jsonb_typeof(v_source_dates) is distinct from 'object'
     or nullif(v_source_dates ->> 'prediction_scope', '') is null
     or nullif(v_source_dates ->> 'feature_snapshot', '') is null
     or nullif(v_source_dates ->> 'snapshot_sha256', '') is null then
    raise exception using
      errcode = '22023',
      message = 'INVALID_RESEARCH_PREDICTION_RUN_CONTRACT';
  end if;
  if v_source_dates ->> 'prediction_scope' not in (
    'OUT_OF_SAMPLE_TEST',
    'DAILY_RESEARCH_INFERENCE',
    'RETROSPECTIVE_RESEARCH_INFERENCE'
  ) then
    raise exception using
      errcode = '22023',
      message = 'UNSUPPORTED_RESEARCH_PREDICTION_SCOPE';
  end if;
  if v_latest_available_at > v_decision_at
     or v_training_end_date >= v_as_of_date then
    raise exception using
      errcode = '22023',
      message = 'INVALID_RESEARCH_PREDICTION_TIME_CONTRACT';
  end if;
  if coalesce((p_run ->> 'candidate_count')::integer, -1) <> 0
     or coalesce((p_run ->> 'watch_count')::integer, -1) <> 0
     or coalesce((p_run ->> 'hard_fail_count')::integer, -1) <> 0
     or coalesce((p_run ->> 'no_trade_count')::integer, -1) <> v_expected_count then
    raise exception using
      errcode = '22023',
      message = 'RESEARCH_PREDICTION_COUNTS_DO_NOT_MATCH_ROWS';
  end if;
  if exists (
    select 1
    from jsonb_array_elements(p_stock_predictions) as item(value)
    where not (item.value ?& array[
      'security_id',
      'market',
      'global_rank',
      'decision',
      'data_quality_status',
      'reason_codes'
    ])
      or item.value ->> 'market' is distinct from v_market_scope
      or item.value ->> 'decision' <> 'NO_TRADE'
      or item.value ->> 'data_quality_status' not in ('PASS', 'FAIL')
      or jsonb_typeof(item.value -> 'reason_codes') is distinct from 'array'
  ) then
    raise exception using
      errcode = '22023',
      message = 'INVALID_RESEARCH_STOCK_PREDICTION_CONTRACT';
  end if;

  select
    count(*)::integer,
    count(distinct nullif(item.value ->> 'security_id', '')::bigint)::integer,
    count(distinct nullif(item.value ->> 'global_rank', '')::integer)::integer
  into
    v_actual_count,
    v_distinct_security_count,
    v_distinct_rank_count
  from jsonb_array_elements(p_stock_predictions) as item(value);
  if v_actual_count <> v_expected_count
     or v_distinct_security_count <> v_expected_count
     or v_distinct_rank_count <> v_expected_count then
    raise exception using
      errcode = '22023',
      message = 'RESEARCH_PREDICTION_IDENTITIES_MUST_BE_UNIQUE';
  end if;

  -- Serialize only one market+horizon stream. TWSE and TPEX can progress
  -- independently without allowing an older snapshot inside either stream.
  perform pg_advisory_xact_lock(
    hashtextextended(
      'market_data.publish_research_prediction_snapshot:'
        || v_market_scope || ':' || v_horizon::text,
      0
    )
  );

  select max(run.decision_at)
    into v_latest_decision_at
  from market_data.prediction_runs as run
  where run.market_scope = v_market_scope
    and run.horizon = v_horizon;
  if v_latest_decision_at is not null
     and v_decision_at < v_latest_decision_at then
    raise exception using
      errcode = '22023',
      message = 'STALE_RESEARCH_PREDICTION_SNAPSHOT';
  end if;

  select
    run.prediction_run_id,
    run.source_dates
  into
    v_prediction_run_id,
    v_existing_source_dates
  from market_data.prediction_runs as run
  where run.market_scope = v_market_scope
    and run.decision_at = v_decision_at
    and run.horizon = v_horizon
    and run.model_bundle_version = v_model_bundle_version
  for update;
  v_existing_run := found;
  if v_existing_run
     and v_existing_source_dates ->> 'snapshot_sha256'
       is distinct from v_source_dates ->> 'snapshot_sha256' then
    raise exception using
      errcode = '22023',
      message = 'RESEARCH_PREDICTION_RUN_IDENTITY_IS_IMMUTABLE';
  end if;

  insert into market_data.prediction_runs (
    as_of_date,
    decision_at,
    horizon,
    market_scope,
    model_bundle_version,
    feature_schema_hash,
    benchmark_versions,
    cost_profile_version,
    training_end_date,
    system_validation_status,
    source_dates,
    latest_available_at,
    candidate_count,
    watch_count,
    no_trade_count,
    hard_fail_count
  )
  values (
    v_as_of_date,
    v_decision_at,
    v_horizon,
    v_market_scope,
    v_model_bundle_version,
    v_feature_schema_hash,
    v_benchmark_versions,
    v_cost_profile_version,
    v_training_end_date,
    'RESEARCH_ONLY',
    v_source_dates,
    v_latest_available_at,
    0,
    0,
    v_expected_count,
    0
  )
  on conflict (
    market_scope,
    decision_at,
    horizon,
    model_bundle_version
  ) do update set
    as_of_date = excluded.as_of_date,
    feature_schema_hash = excluded.feature_schema_hash,
    benchmark_versions = excluded.benchmark_versions,
    cost_profile_version = excluded.cost_profile_version,
    training_end_date = excluded.training_end_date,
    system_validation_status = excluded.system_validation_status,
    source_dates = excluded.source_dates,
    latest_available_at = excluded.latest_available_at,
    candidate_count = excluded.candidate_count,
    watch_count = excluded.watch_count,
    no_trade_count = excluded.no_trade_count,
    hard_fail_count = excluded.hard_fail_count
  returning prediction_run_id into v_prediction_run_id;

  delete from market_data.stock_predictions as existing
  where existing.prediction_run_id = v_prediction_run_id
    and not exists (
      select 1
      from jsonb_array_elements(p_stock_predictions) as item(value)
      where nullif(item.value ->> 'security_id', '')::bigint = existing.security_id
    );

  insert into market_data.stock_predictions (
    prediction_run_id,
    security_id,
    market,
    industry,
    model_raw_score,
    rank_score,
    global_rank,
    global_rank_percentile,
    industry_rank,
    industry_rank_percentile,
    calibrated_p_up,
    calibrated_p_neutral,
    calibrated_p_down,
    calibration_version,
    gross_q10,
    gross_q50,
    gross_q90,
    net_q10,
    net_q50,
    net_q90,
    interval_width,
    quantile_crossing_before_calibration,
    calibration_status,
    forecast_volatility,
    downside_risk,
    adv20_ntd,
    maximum_order_notional_ntd,
    market_regime,
    market_exposure_cap,
    estimated_round_trip_cost,
    data_quality_status,
    decision,
    reason_codes
  )
  select
    v_prediction_run_id,
    prediction.security_id,
    prediction.market,
    prediction.industry,
    prediction.model_raw_score,
    prediction.rank_score,
    prediction.global_rank,
    prediction.global_rank_percentile,
    prediction.industry_rank,
    prediction.industry_rank_percentile,
    prediction.calibrated_p_up,
    prediction.calibrated_p_neutral,
    prediction.calibrated_p_down,
    prediction.calibration_version,
    prediction.gross_q10,
    prediction.gross_q50,
    prediction.gross_q90,
    prediction.net_q10,
    prediction.net_q50,
    prediction.net_q90,
    prediction.interval_width,
    prediction.quantile_crossing_before_calibration,
    prediction.calibration_status,
    prediction.forecast_volatility,
    prediction.downside_risk,
    prediction.adv20_ntd,
    prediction.maximum_order_notional_ntd,
    prediction.market_regime,
    prediction.market_exposure_cap,
    prediction.estimated_round_trip_cost,
    prediction.data_quality_status,
    prediction.decision,
    prediction.reason_codes
  from jsonb_to_recordset(p_stock_predictions) as prediction(
    security_id bigint,
    market text,
    industry text,
    model_raw_score numeric,
    rank_score numeric,
    global_rank integer,
    global_rank_percentile numeric,
    industry_rank integer,
    industry_rank_percentile numeric,
    calibrated_p_up numeric,
    calibrated_p_neutral numeric,
    calibrated_p_down numeric,
    calibration_version text,
    gross_q10 numeric,
    gross_q50 numeric,
    gross_q90 numeric,
    net_q10 numeric,
    net_q50 numeric,
    net_q90 numeric,
    interval_width numeric,
    quantile_crossing_before_calibration boolean,
    calibration_status text,
    forecast_volatility numeric,
    downside_risk numeric,
    adv20_ntd numeric,
    maximum_order_notional_ntd numeric,
    market_regime text,
    market_exposure_cap numeric,
    estimated_round_trip_cost numeric,
    data_quality_status text,
    decision text,
    reason_codes text[]
  )
  on conflict (prediction_run_id, security_id) do update set
    market = excluded.market,
    industry = excluded.industry,
    model_raw_score = excluded.model_raw_score,
    rank_score = excluded.rank_score,
    global_rank = excluded.global_rank,
    global_rank_percentile = excluded.global_rank_percentile,
    industry_rank = excluded.industry_rank,
    industry_rank_percentile = excluded.industry_rank_percentile,
    calibrated_p_up = excluded.calibrated_p_up,
    calibrated_p_neutral = excluded.calibrated_p_neutral,
    calibrated_p_down = excluded.calibrated_p_down,
    calibration_version = excluded.calibration_version,
    gross_q10 = excluded.gross_q10,
    gross_q50 = excluded.gross_q50,
    gross_q90 = excluded.gross_q90,
    net_q10 = excluded.net_q10,
    net_q50 = excluded.net_q50,
    net_q90 = excluded.net_q90,
    interval_width = excluded.interval_width,
    quantile_crossing_before_calibration = excluded.quantile_crossing_before_calibration,
    calibration_status = excluded.calibration_status,
    forecast_volatility = excluded.forecast_volatility,
    downside_risk = excluded.downside_risk,
    adv20_ntd = excluded.adv20_ntd,
    maximum_order_notional_ntd = excluded.maximum_order_notional_ntd,
    market_regime = excluded.market_regime,
    market_exposure_cap = excluded.market_exposure_cap,
    estimated_round_trip_cost = excluded.estimated_round_trip_cost,
    data_quality_status = excluded.data_quality_status,
    decision = excluded.decision,
    reason_codes = excluded.reason_codes;

  select count(*)::integer
    into v_actual_count
  from market_data.stock_predictions as prediction
  where prediction.prediction_run_id = v_prediction_run_id;
  if v_actual_count <> v_expected_count then
    raise exception using
      errcode = '23514',
      message = 'RESEARCH_PREDICTION_ATOMIC_ROW_COUNT_MISMATCH';
  end if;

  return jsonb_build_object(
    'prediction_run_id', v_prediction_run_id,
    'prediction_count', v_actual_count,
    'market_scope', v_market_scope
  );
end
$function$;

comment on function market_data.publish_research_prediction_snapshot(
    jsonb, jsonb
) is
'Atomic market-scoped RESEARCH_ONLY publisher; service_role only.';

revoke all on function market_data.publish_research_prediction_snapshot(
    jsonb, jsonb
)
from public, anon, authenticated;
grant execute on function market_data.publish_research_prediction_snapshot(
    jsonb, jsonb
)
to service_role;

commit;

notify pgrst, 'reload schema';
