begin;

set local search_path = pg_catalog, public, extensions;
set local lock_timeout = '5s';
set local statement_timeout = '60s';

insert into market_data.data_sources (
    source_code,
    display_name,
    source_timezone,
    revision_policy,
    is_active
)
values (
    'PREDICTION_SCOPE_VALIDATION',
    'Prediction scope local validation',
    'Asia/Taipei',
    'IMMUTABLE_TEST_FIXTURE',
    true
)
on conflict (source_code) do nothing;

insert into market_data.cost_profiles (
    cost_profile_version,
    asset_type,
    commission_rate,
    commission_discount,
    minimum_fee,
    sell_tax_rate,
    estimated_order_notional_ntd,
    spread_model,
    slippage_scenario,
    market_impact_parameter,
    max_adv_participation,
    parameters
)
values (
    'prediction-scope-local-v1',
    'COMMON_STOCK',
    0.001425,
    0.6,
    20,
    0.003,
    100000,
    'LOCAL_VALIDATION',
    'BASE',
    0,
    0.01,
    '{}'::jsonb
)
on conflict (cost_profile_version) do nothing;

insert into market_data.securities (
    symbol,
    display_name,
    market,
    asset_type,
    source_id
)
select
    fixture.symbol,
    fixture.display_name,
    fixture.market,
    'COMMON_STOCK' as asset_type,
    source.source_id
from (
    values
    ('9911', 'TWSE scope fixture', 'TWSE'),
    ('8811', 'TPEX scope fixture', 'TPEX')
) as fixture (symbol, display_name, market)
cross join market_data.data_sources as source
where source.source_code = 'PREDICTION_SCOPE_VALIDATION'
on conflict (market, symbol) do nothing;

do $validation$
declare
  v_twse_security_id bigint;
  v_tpex_security_id bigint;
  v_twse_run_id bigint;
  v_tpex_old_run_id bigint;
  v_tpex_same_identity_run_id bigint;
  v_result jsonb;
  v_twse_row jsonb;
  v_tpex_row jsonb;
  v_run jsonb;
  v_base_decision_at timestamptz;
  v_tpex_old_decision_at timestamptz;
  v_tpex_stale_decision_at timestamptz;
  v_base_as_of_date date;
  v_tpex_old_as_of_date date;
  v_tpex_stale_as_of_date date;
  v_training_end_date date;
begin
  select security_id
    into strict v_twse_security_id
  from market_data.securities
  where market = 'TWSE' and symbol = '9911';

  select security_id
    into strict v_tpex_security_id
  from market_data.securities
  where market = 'TPEX' and symbol = '8811';

  -- Always validate after the newest persisted 5-day stream. Fixed fixture
  -- dates become stale as soon as Production has a newer research snapshot.
  select coalesce(max(run.decision_at), transaction_timestamp())
      + interval '3 days'
    into v_base_decision_at
  from market_data.prediction_runs as run
  where run.horizon = 5
    and run.market_scope in ('TWSE', 'TPEX');

  v_tpex_old_decision_at := v_base_decision_at - interval '1 day';
  v_tpex_stale_decision_at := v_base_decision_at - interval '2 days';
  v_base_as_of_date :=
    (v_base_decision_at at time zone 'Asia/Taipei')::date;
  v_tpex_old_as_of_date :=
    (v_tpex_old_decision_at at time zone 'Asia/Taipei')::date;
  v_tpex_stale_as_of_date :=
    (v_tpex_stale_decision_at at time zone 'Asia/Taipei')::date;
  v_training_end_date := v_tpex_stale_as_of_date - 1;

  v_twse_row := jsonb_build_object(
    'security_id', v_twse_security_id,
    'market', 'TWSE',
    'industry', null,
    'model_raw_score', 1,
    'rank_score', 100,
    'global_rank', 1,
    'global_rank_percentile', 1,
    'industry_rank', null,
    'industry_rank_percentile', null,
    'calibrated_p_up', 0.4,
    'calibrated_p_neutral', 0.4,
    'calibrated_p_down', 0.2,
    'calibration_version', 'local-v1',
    'gross_q10', -0.1,
    'gross_q50', 0,
    'gross_q90', 0.1,
    'net_q10', -0.11,
    'net_q50', -0.01,
    'net_q90', 0.09,
    'interval_width', 0.2,
    'quantile_crossing_before_calibration', false,
    'calibration_status', 'RESEARCH_ONLY',
    'forecast_volatility', 0.1,
    'downside_risk', 0.1,
    'adv20_ntd', 1000000,
    'maximum_order_notional_ntd', 10000,
    'market_regime', null,
    'market_exposure_cap', null,
    'estimated_round_trip_cost', 0.005,
    'data_quality_status', 'PASS',
    'decision', 'NO_TRADE',
    'reason_codes', jsonb_build_array('LOCAL_MARKET_SCOPE_VALIDATION')
  );
  v_tpex_row := v_twse_row
    || jsonb_build_object(
      'security_id', v_tpex_security_id,
      'market', 'TPEX'
    );

  -- Existing publishers omit market_scope. That exact payload remains TWSE.
  v_run := jsonb_build_object(
    'as_of_date', v_base_as_of_date,
    'decision_at', v_base_decision_at,
    'horizon', 5,
    'model_bundle_version', 'market-scope-local-v1',
    'feature_schema_hash', repeat('a', 64),
    'benchmark_versions', jsonb_build_object('TWSE', 'local'),
    'cost_profile_version', 'prediction-scope-local-v1',
    'training_end_date', v_training_end_date,
    'system_validation_status', 'RESEARCH_ONLY',
    'source_dates', jsonb_build_object(
      'prediction_scope', 'RETROSPECTIVE_RESEARCH_INFERENCE',
      'feature_snapshot', 'twse-local',
      'snapshot_sha256', repeat('1', 64)
    ),
    'latest_available_at', v_base_decision_at - interval '1 hour',
    'candidate_count', 0,
    'watch_count', 0,
    'no_trade_count', 1,
    'hard_fail_count', 0
  );
  v_result := market_data.publish_research_prediction_snapshot(
    v_run,
    jsonb_build_array(v_twse_row)
  );
  v_twse_run_id := (v_result ->> 'prediction_run_id')::bigint;
  if v_result ->> 'market_scope' is distinct from 'TWSE' then
    raise exception 'legacy TWSE payload did not default to TWSE';
  end if;

  -- TPEX is explicit and can publish an older date than TWSE because stale
  -- ordering and the advisory lock are isolated by market_scope+horizon.
  v_run := v_run || jsonb_build_object(
    'as_of_date', v_tpex_old_as_of_date,
    'decision_at', v_tpex_old_decision_at,
    'market_scope', 'TPEX',
    'benchmark_versions', jsonb_build_object('TPEX', 'local'),
    'source_dates', jsonb_build_object(
      'prediction_scope', 'RETROSPECTIVE_RESEARCH_INFERENCE',
      'feature_snapshot', 'tpex-local-old',
      'snapshot_sha256', repeat('2', 64)
    ),
    'latest_available_at', v_tpex_old_decision_at - interval '1 hour'
  );
  v_result := market_data.publish_research_prediction_snapshot(
    v_run,
    jsonb_build_array(v_tpex_row)
  );
  v_tpex_old_run_id := (v_result ->> 'prediction_run_id')::bigint;

  -- The old identity may coexist in two markets.
  v_run := v_run || jsonb_build_object(
    'as_of_date', v_base_as_of_date,
    'decision_at', v_base_decision_at,
    'source_dates', jsonb_build_object(
      'prediction_scope', 'RETROSPECTIVE_RESEARCH_INFERENCE',
      'feature_snapshot', 'tpex-local-same-identity',
      'snapshot_sha256', repeat('3', 64)
    ),
    'latest_available_at', v_base_decision_at - interval '1 hour'
  );
  v_result := market_data.publish_research_prediction_snapshot(
    v_run,
    jsonb_build_array(v_tpex_row)
  );
  v_tpex_same_identity_run_id :=
    (v_result ->> 'prediction_run_id')::bigint;
  if v_tpex_same_identity_run_id = v_twse_run_id then
    raise exception 'TWSE and TPEX incorrectly shared one prediction run';
  end if;

  v_result := market_data.publish_research_prediction_snapshot(
    v_run,
    jsonb_build_array(v_tpex_row)
  );
  if (v_result ->> 'prediction_run_id')::bigint
     <> v_tpex_same_identity_run_id then
    raise exception 'market-scoped upsert did not preserve run identity';
  end if;

  begin
    perform market_data.publish_research_prediction_snapshot(
      v_run - 'market_scope',
      jsonb_build_array(v_tpex_row)
    );
    raise exception 'TPEX payload without explicit market_scope was accepted';
  exception
    when invalid_parameter_value then
      if sqlerrm <> 'INVALID_RESEARCH_STOCK_PREDICTION_CONTRACT' then
        raise;
      end if;
  end;

  begin
    perform market_data.publish_research_prediction_snapshot(
      v_run || jsonb_build_object(
        'as_of_date', v_tpex_stale_as_of_date,
        'decision_at', v_tpex_stale_decision_at,
        'source_dates', jsonb_build_object(
          'prediction_scope', 'RETROSPECTIVE_RESEARCH_INFERENCE',
          'feature_snapshot', 'tpex-local-stale',
          'snapshot_sha256', repeat('4', 64)
        ),
        'latest_available_at', v_tpex_stale_decision_at - interval '1 hour'
      ),
      jsonb_build_array(v_tpex_row)
    );
    raise exception 'older TPEX snapshot was accepted';
  exception
    when invalid_parameter_value then
      if sqlerrm <> 'STALE_RESEARCH_PREDICTION_SNAPSHOT' then
        raise;
      end if;
  end;

  begin
    update market_data.stock_predictions
    set market = 'TPEX'
    where prediction_run_id = v_twse_run_id;
    raise exception 'stock child market mismatch was accepted';
  exception
    when check_violation then
      if sqlerrm <> 'PREDICTION_CHILD_MARKET_SCOPE_MISMATCH' then
        raise;
      end if;
  end;

  begin
    insert into market_data.market_predictions (
      prediction_run_id,
      market,
      calibrated_p_up,
      calibrated_p_neutral,
      calibrated_p_down,
      market_regime,
      forecast_market_volatility,
      market_exposure_cap,
      model_version,
      training_end_date
    ) values (
      v_twse_run_id,
      'TPEX',
      0.4,
      0.4,
      0.2,
      'RANGE',
      0.1,
      0.5,
      'local-v1',
      v_training_end_date
    );
    raise exception 'market child scope mismatch was accepted';
  exception
    when check_violation then
      if sqlerrm <> 'PREDICTION_CHILD_MARKET_SCOPE_MISMATCH' then
        raise;
      end if;
  end;

  begin
    update market_data.prediction_runs
    set market_scope = 'TPEX'
    where prediction_run_id = v_twse_run_id;
    raise exception 'prediction run market_scope mutation was accepted';
  exception
    when check_violation then
      if sqlerrm <> 'PREDICTION_RUN_MARKET_SCOPE_IS_IMMUTABLE' then
        raise;
      end if;
  end;

  if v_tpex_old_run_id is null
     or exists (
       select 1
       from market_data.stock_predictions as prediction
       join market_data.prediction_runs as run
         using (prediction_run_id)
       where prediction.market is distinct from run.market_scope
     ) then
    raise exception 'persisted prediction market scopes are inconsistent';
  end if;

  if has_function_privilege(
    'anon',
    'market_data.publish_research_prediction_snapshot(jsonb,jsonb)',
    'EXECUTE'
  ) or has_function_privilege(
    'authenticated',
    'market_data.publish_research_prediction_snapshot(jsonb,jsonb)',
    'EXECUTE'
  ) or not has_function_privilege(
    'service_role',
    'market_data.publish_research_prediction_snapshot(jsonb,jsonb)',
    'EXECUTE'
  ) or has_function_privilege(
    'service_role',
    'market_data.publish_research_prediction_snapshot_twse_v1(jsonb,jsonb)',
    'EXECUTE'
  ) then
    raise exception 'prediction publishing RPC privileges are not isolated';
  end if;

  if exists (
    select 1
    from pg_catalog.pg_proc as procedure
    join pg_catalog.pg_namespace as namespace
      on namespace.oid = procedure.pronamespace
    where namespace.nspname = 'market_data'
      and procedure.proname in (
        'publish_research_prediction_snapshot',
        'enforce_prediction_child_market_scope',
        'enforce_prediction_run_market_scope_immutable'
      )
      and procedure.prosecdef
  ) then
    raise exception 'market-scope functions are not security invoker';
  end if;
end
$validation$;

rollback;
