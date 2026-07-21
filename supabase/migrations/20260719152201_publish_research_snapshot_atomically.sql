begin;

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
      or item.value ->> 'market' <> 'TWSE'
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

  -- One lock protects the monotonic-date check and the complete run replacement.
  -- The RPC call itself is one PostgreSQL transaction, so readers see either the
  -- previous complete snapshot or the new complete snapshot, never a partial run.
  perform pg_advisory_xact_lock(
    hashtextextended('market_data.publish_research_prediction_snapshot', 0)
  );

  select max(prediction_runs.decision_at)
    into v_latest_decision_at
  from market_data.prediction_runs
  where prediction_runs.horizon = v_horizon;
  if v_latest_decision_at is not null
     and v_decision_at < v_latest_decision_at then
    raise exception using
      errcode = '22023',
      message = 'STALE_RESEARCH_PREDICTION_SNAPSHOT';
  end if;

  select
    prediction_runs.prediction_run_id,
    prediction_runs.source_dates
  into
    v_prediction_run_id,
    v_existing_source_dates
  from market_data.prediction_runs
  where prediction_runs.decision_at = v_decision_at
    and prediction_runs.horizon = v_horizon
    and prediction_runs.model_bundle_version = v_model_bundle_version
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
  on conflict (decision_at, horizon, model_bundle_version) do update set
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

  -- Remove only rows that no longer belong to this immutable run payload. This
  -- also repairs a legacy half-written run before the final count is checked.
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
  from market_data.stock_predictions
  where stock_predictions.prediction_run_id = v_prediction_run_id;
  if v_actual_count <> v_expected_count then
    raise exception using
      errcode = '23514',
      message = 'RESEARCH_PREDICTION_ATOMIC_ROW_COUNT_MISMATCH';
  end if;

  return jsonb_build_object(
    'prediction_run_id', v_prediction_run_id,
    'prediction_count', v_actual_count
  );
end
$function$;

comment on function market_data.publish_research_prediction_snapshot(
    jsonb, jsonb
) is
'Atomic RESEARCH_ONLY snapshot publisher restricted to service_role.';

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
