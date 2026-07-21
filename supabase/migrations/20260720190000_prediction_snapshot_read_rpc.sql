begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

create index if not exists validation_runs_snapshot_lookup_idx
on market_data.validation_runs (
  model_bundle_version,
  horizon,
  completed_at desc,
  validation_run_id desc
)
where completed_at is not null;

drop function if exists market_data.get_prediction_snapshot_rows(integer, text, timestamptz);

create or replace function market_data.get_prediction_snapshot_rows(
  p_horizon integer,
  p_market_scope text,
  p_observed_at timestamptz default now()
)
returns jsonb
language plpgsql
stable
security invoker
set search_path = pg_catalog, market_data
as $function$
declare
  v_run market_data.prediction_runs%rowtype;
  v_security_ids bigint[] := '{}'::bigint[];
  v_prediction_ids bigint[] := '{}'::bigint[];
  v_validation_run_id bigint;
  v_validation_candidate_count integer := 0;
  v_validation_link_status text;
  v_observed_date date;
begin
  if p_horizon is distinct from 5 then
    raise exception using
      errcode = '22023',
      message = 'UNSUPPORTED_PREDICTION_HORIZON';
  end if;

  if p_market_scope is null or p_market_scope not in ('TWSE', 'TPEX') then
    raise exception using
      errcode = '22023',
      message = 'UNSUPPORTED_PREDICTION_MARKET_SCOPE';
  end if;

  if p_observed_at is null then
    raise exception using
      errcode = '22004',
      message = 'PREDICTION_OBSERVED_AT_REQUIRED';
  end if;

  v_observed_date := (p_observed_at at time zone 'Asia/Taipei')::date;

  select run.*
  into v_run
  from market_data.prediction_runs as run
  where run.horizon = p_horizon
    and run.market_scope = p_market_scope
    and run.decision_at <= p_observed_at
    and run.latest_available_at <= p_observed_at
    and run.created_at <= p_observed_at
  order by run.decision_at desc, run.prediction_run_id desc
  limit 1;

  if not found then
    return null;
  end if;

  select coalesce(array_agg(row.stock_prediction_id order by row.stock_prediction_id), '{}'::bigint[])
  into v_prediction_ids
  from market_data.stock_predictions as row
  where row.prediction_run_id = v_run.prediction_run_id;

  select coalesce(array_agg(relevant.security_id order by relevant.security_id), '{}'::bigint[])
  into v_security_ids
  from (
    select prediction.security_id
    from market_data.stock_predictions as prediction
    where prediction.prediction_run_id = v_run.prediction_run_id
    union
    select audit.security_id
    from market_data.data_quality_audits as audit
    where audit.prediction_run_id = v_run.prediction_run_id
  ) as relevant;

  select count(*)::integer, min(candidate.validation_run_id)
  into v_validation_candidate_count, v_validation_run_id
  from (
    select validation.validation_run_id
    from market_data.validation_runs as validation
    where validation.model_bundle_version = v_run.model_bundle_version
      and validation.horizon = p_horizon
      and validation.completed_at <= v_run.created_at
    order by
      validation.completed_at desc nulls last,
      validation.validation_run_id desc
    limit 2
  ) as candidate;

  v_validation_link_status := case v_validation_candidate_count
    when 0 then 'MISSING'
    when 1 then 'LINKED'
    else 'AMBIGUOUS'
  end;

  if v_validation_link_status <> 'LINKED' then
    v_validation_run_id := null;
  end if;

  return jsonb_build_object(
    'run', (
      select to_jsonb(run_payload)
      from (
        select
          v_run.prediction_run_id as prediction_run_id,
          v_run.as_of_date as as_of_date,
          v_run.decision_at as decision_at,
          v_run.horizon as horizon,
          v_run.market_scope as market_scope,
          v_run.model_bundle_version as model_bundle_version,
          v_run.feature_schema_hash as feature_schema_hash,
          v_run.cost_profile_version as cost_profile_version,
          v_run.training_end_date as training_end_date,
          v_run.system_validation_status as system_validation_status,
          v_run.source_dates as source_dates,
          v_run.latest_available_at as latest_available_at,
          v_run.candidate_count as candidate_count,
          v_run.watch_count as watch_count,
          v_run.no_trade_count as no_trade_count,
          v_run.hard_fail_count as hard_fail_count,
          v_run.created_at as created_at
      ) as run_payload
    ),
    'predictions', coalesce((
      select jsonb_agg(to_jsonb(prediction) order by prediction.global_rank)
      from (
        select
          row.stock_prediction_id,
          row.prediction_run_id,
          row.security_id,
          row.market,
          row.industry,
          row.rank_score,
          row.global_rank,
          row.global_rank_percentile,
          row.industry_rank,
          row.industry_rank_percentile,
          row.calibrated_p_up,
          row.calibrated_p_neutral,
          row.calibrated_p_down,
          row.calibration_version,
          row.gross_q10,
          row.gross_q50,
          row.gross_q90,
          row.net_q10,
          row.net_q50,
          row.net_q90,
          row.interval_width,
          row.calibration_status,
          row.forecast_volatility,
          row.downside_risk,
          row.adv20_ntd,
          row.maximum_order_notional_ntd,
          row.market_regime,
          row.market_exposure_cap,
          row.estimated_round_trip_cost,
          row.data_quality_status,
          row.decision,
          row.reason_codes
        from market_data.stock_predictions as row
        where row.prediction_run_id = v_run.prediction_run_id
      ) as prediction
    ), '[]'::jsonb),
    'securities', coalesce((
      select jsonb_agg(to_jsonb(security) order by security.security_id)
      from (
        select
          row.security_id,
          row.symbol,
          row.display_name,
          row.market,
          row.asset_type
        from market_data.securities as row
        where row.security_id = any(v_security_ids)
      ) as security
    ), '[]'::jsonb),
    'currentSecurityHistory', coalesce((
      select jsonb_agg(to_jsonb(history) order by history.security_id)
      from (
        select distinct on (row.security_id)
          row.security_id,
          row.effective_from,
          row.effective_to,
          row.industry_code,
          row.industry_name,
          row.source_version,
          row.available_at
        from market_data.security_history as row
        where row.security_id = any(v_security_ids)
          and row.effective_from <= v_observed_date
          and (row.effective_to is null or v_observed_date < row.effective_to)
          and row.available_at <= p_observed_at
        order by
          row.security_id,
          row.effective_from desc,
          row.available_at desc,
          row.security_history_id desc
      ) as history
    ), '[]'::jsonb),
    'audits', coalesce((
      select jsonb_agg(to_jsonb(audit) order by audit.security_id)
      from (
        select
          row.security_id,
          row.quality_status,
          row.hard_fail,
          row.reason_codes,
          row.source_dates,
          row.latest_available_at
        from market_data.data_quality_audits as row
        where row.prediction_run_id = v_run.prediction_run_id
      ) as audit
    ), '[]'::jsonb),
    'gates', coalesce((
      select jsonb_agg(
        to_jsonb(gate)
        order by gate.stock_prediction_id, gate.gate_order
      )
      from (
        select
          row.stock_prediction_id,
          row.gate_order,
          row.gate_name,
          row.passed,
          row.actual_value,
          row.threshold_value,
          row.reason_code
        from market_data.decision_gate_results as row
        where row.stock_prediction_id = any(v_prediction_ids)
      ) as gate
    ), '[]'::jsonb),
    'markets', coalesce((
      select jsonb_agg(to_jsonb(market) order by market.market)
      from (
        select
          row.market,
          row.calibrated_p_up,
          row.calibrated_p_neutral,
          row.calibrated_p_down,
          row.market_regime,
          row.forecast_market_volatility,
          row.market_exposure_cap,
          row.model_version,
          row.training_end_date
        from market_data.market_predictions as row
        where row.prediction_run_id = v_run.prediction_run_id
      ) as market
    ), '[]'::jsonb),
    'validationRun', case
      when v_validation_run_id is null then null
      else (
        select to_jsonb(validation)
        from (
          select
            row.validation_run_id,
            row.validation_status,
            row.locked_holdout,
            row.frozen_config_hash,
            row.started_at,
            row.completed_at,
            row.limitations
          from market_data.validation_runs as row
          where row.validation_run_id = v_validation_run_id
        ) as validation
      )
    end,
    'validationMetrics', case
      when v_validation_run_id is null then '[]'::jsonb
      else coalesce((
        select jsonb_agg(
          to_jsonb(metric)
          order by metric.fold_number, metric.metric_name
        )
        from (
          select
            row.fold_number,
            row.metric_name,
            row.metric_value,
            row.metric_payload
          from market_data.validation_fold_metrics as row
          where row.validation_run_id = v_validation_run_id
        ) as metric
      ), '[]'::jsonb)
    end,
    'backtests', case
      when v_validation_run_id is null then '[]'::jsonb
      else coalesce((
        select jsonb_agg(
          to_jsonb(backtest)
          order by backtest.cost_multiplier
        )
        from (
          select
            row.cost_scenario,
            row.cost_multiplier,
            row.status,
            row.summary_metrics,
            row.completed_at
          from market_data.backtest_runs as row
          where row.validation_run_id = v_validation_run_id
        ) as backtest
      ), '[]'::jsonb)
    end,
    'validationLinkStatus', v_validation_link_status
  );
end
$function$;

comment on function market_data.get_prediction_snapshot_rows(integer, text, timestamptz) is
  'Returns one complete latest prediction snapshot payload in one PostgREST RPC call. Service-role only.';

revoke all on function market_data.get_prediction_snapshot_rows(integer, text, timestamptz)
from public, anon, authenticated;
grant execute on function market_data.get_prediction_snapshot_rows(integer, text, timestamptz)
to service_role;

commit;
