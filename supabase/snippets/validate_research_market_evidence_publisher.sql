begin;

do $privileges$
declare
  v_identity_args text;
  v_service_execute boolean;
  v_public_execute boolean;
begin
  select pg_get_function_identity_arguments(procedure.oid)
  into v_identity_args
  from pg_proc as procedure
  join pg_namespace as namespace
    on namespace.oid = procedure.pronamespace
  where namespace.nspname = 'market_data'
    and procedure.proname = 'publish_research_prediction_snapshot'
    and procedure.pronargs = 3;

  if v_identity_args is distinct from
    'p_run jsonb, p_stock_predictions jsonb, p_market_prediction jsonb'
  then
    raise exception 'three-argument research publisher is missing';
  end if;

  select has_function_privilege(
    'service_role',
    'market_data.publish_research_prediction_snapshot(jsonb,jsonb,jsonb)',
    'EXECUTE'
  )
  into v_service_execute;
  select has_function_privilege(
    'authenticated',
    'market_data.publish_research_prediction_snapshot(jsonb,jsonb,jsonb)',
    'EXECUTE'
  )
  into v_public_execute;

  if not v_service_execute or v_public_execute then
    raise exception 'research market publisher grants are invalid';
  end if;
end
$privileges$;

do $contract$
declare
  v_source_id bigint;
  v_security_id bigint;
  v_run jsonb;
  v_row jsonb;
  v_market jsonb;
  v_result jsonb;
  v_run_id bigint;
  v_missing_run jsonb;
  v_missing_row jsonb;
  v_missing_result jsonb;
  v_missing_run_id bigint;
begin
  insert into market_data.data_sources (
    source_code,
    display_name,
    source_timezone,
    revision_policy
  )
  values (
    'RESEARCH_MARKET_EVIDENCE_VALIDATION',
    'Research market evidence validation',
    'Asia/Taipei',
    'IMMUTABLE_TEST'
  )
  returning source_id into v_source_id;

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
    'research-market-evidence-validation-v1',
    'COMMON_STOCK',
    0.001425,
    1,
    20,
    0.003,
    100000,
    'validation',
    'BASE',
    0.001,
    0.01,
    '{}'::jsonb
  );

  insert into market_data.securities (
    symbol,
    display_name,
    market,
    asset_type,
    source_id
  )
  values (
    'RME1',
    'Research market evidence validation',
    'TWSE',
    'COMMON_STOCK',
    v_source_id
  )
  returning security_id into v_security_id;

  v_run := jsonb_build_object(
    'as_of_date', '2026-07-23',
    'decision_at', '2026-07-23T09:00:00+00:00',
    'horizon', 5,
    'market_scope', 'TWSE',
    'model_bundle_version', 'research-market-evidence-candidate',
    'feature_schema_hash', repeat('f', 64),
    'benchmark_versions', jsonb_build_object('TWSE', 'validation-v1'),
    'cost_profile_version', 'research-market-evidence-validation-v1',
    'training_end_date', '2026-06-30',
    'system_validation_status', 'RESEARCH_ONLY',
    'source_dates', jsonb_build_object(
      'prediction_scope', 'DAILY_RESEARCH_INFERENCE',
      'feature_snapshot', repeat('a', 64),
      'snapshot_sha256', repeat('b', 64)
    ),
    'latest_available_at', '2026-07-23T08:30:00+00:00',
    'candidate_count', 1,
    'watch_count', 0,
    'no_trade_count', 0,
    'policy_input_missing_count', 0,
    'policy_validation_failed_count', 0,
    'policy_hard_fail_count', 0,
    'hard_fail_count', 0
  );
  v_row := jsonb_build_object(
    'security_id', v_security_id,
    'market', 'TWSE',
    'industry', 'VALIDATION',
    'model_raw_score', 0.8,
    'rank_score', 100,
    'global_rank', 1,
    'global_rank_percentile', 1,
    'industry_rank', 1,
    'industry_rank_percentile', 1,
    'calibrated_p_up', 0.6,
    'calibrated_p_neutral', 0.3,
    'calibrated_p_down', 0.1,
    'calibration_version', 'validation-v1',
    'gross_q10', -0.02,
    'gross_q50', 0.01,
    'gross_q90', 0.05,
    'net_q10', -0.026,
    'net_q50', 0.004,
    'net_q90', 0.044,
    'interval_width', 0.07,
    'quantile_crossing_before_calibration', false,
    'calibration_status', 'CALIBRATED:validation-v1',
    'forecast_volatility', 0.2,
    'downside_risk', 0.03,
    'adv20_ntd', 20000000,
    'maximum_order_notional_ntd', 200000,
    'market_regime', 'UPTREND_NORMAL_VOL',
    'market_exposure_cap', 0.6,
    'estimated_round_trip_cost', 0.006,
    'data_quality_status', 'PASS',
    'decision', 'CANDIDATE',
    'decision_policy_status', 'EVALUATED',
    'reason_codes', jsonb_build_array('PASS')
  );
  v_market := jsonb_build_object(
    'market', 'TWSE',
    'calibrated_p_up', 0.55,
    'calibrated_p_neutral', 0.30,
    'calibrated_p_down', 0.15,
    'market_regime', 'UPTREND_NORMAL_VOL',
    'forecast_market_volatility', 0.18,
    'market_exposure_cap', 0.6,
    'model_version', 'twse-market-h5-validation-v1',
    'training_end_date', '2026-06-30'
  );

  v_result := market_data.publish_research_prediction_snapshot(
    v_run,
    jsonb_build_array(v_row),
    v_market
  );
  v_run_id := (v_result ->> 'prediction_run_id')::bigint;
  if (v_result ->> 'market_prediction_count')::integer <> 1
    or not exists (
      select 1
      from market_data.prediction_runs as run
      join market_data.stock_predictions as prediction
        on prediction.prediction_run_id = run.prediction_run_id
      join market_data.market_predictions as market_prediction
        on market_prediction.prediction_run_id = run.prediction_run_id
      where run.prediction_run_id = v_run_id
        and run.system_validation_status = 'RESEARCH_ONLY'
        and run.candidate_count = 1
        and run.no_trade_count = 0
        and prediction.decision_policy_status = 'EVALUATED'
        and prediction.decision = 'CANDIDATE'
        and prediction.data_quality_status = 'PASS'
        and market_prediction.market = 'TWSE'
        and market_prediction.market_exposure_cap = 0.6
    ) then
    raise exception 'evaluated candidate or market evidence was not atomic';
  end if;

  v_result := market_data.publish_research_prediction_snapshot(
    v_run,
    jsonb_build_array(v_row),
    v_market
  );
  if (v_result ->> 'prediction_run_id')::bigint <> v_run_id
    or (v_result ->> 'market_prediction_count')::integer <> 1 then
    raise exception 'research market evidence publisher is not idempotent';
  end if;

  begin
    perform market_data.publish_research_prediction_snapshot(
      v_run,
      jsonb_build_array(v_row),
      v_market || jsonb_build_object('market_exposure_cap', 0.5)
    );
    raise exception 'conflicting market evidence was accepted';
  exception
    when sqlstate '22023' then
      if sqlerrm <> 'INVALID_RESEARCH_MARKET_EVIDENCE_CONTRACT' then
        raise;
      end if;
  end;

  begin
    perform market_data.publish_research_prediction_snapshot(
      v_run,
      jsonb_build_array(v_row),
      v_market || jsonb_build_object('market_exposure_cap', null)
    );
    raise exception 'null market evidence was accepted';
  exception
    when sqlstate '22023' then
      if sqlerrm <> 'INVALID_RESEARCH_MARKET_EVIDENCE_CONTRACT' then
        raise;
      end if;
  end;

  begin
    perform market_data.publish_research_prediction_snapshot(
      v_run || jsonb_build_object('candidate_count', 0),
      jsonb_build_array(v_row),
      v_market
    );
    raise exception 'candidate count mismatch was accepted';
  exception
    when sqlstate '22023' then
      if sqlerrm <> 'RESEARCH_EVALUATED_CANDIDATE_COUNT_MISMATCH' then
        raise;
      end if;
  end;

  v_missing_run := v_run || jsonb_build_object(
    'as_of_date', '2026-07-24',
    'decision_at', '2026-07-24T09:00:00+00:00',
    'model_bundle_version', 'research-market-evidence-missing',
    'source_dates', jsonb_build_object(
      'prediction_scope', 'DAILY_RESEARCH_INFERENCE',
      'feature_snapshot', repeat('c', 64),
      'snapshot_sha256', repeat('d', 64)
    ),
    'latest_available_at', '2026-07-24T08:30:00+00:00',
    'candidate_count', 0,
    'policy_input_missing_count', 1
  );
  v_missing_row := (
    v_row - 'market_regime' - 'market_exposure_cap'
  ) || jsonb_build_object(
    'data_quality_status', 'WARN',
    'decision', null,
    'decision_policy_status', 'MISSING_REQUIRED_DATA',
    'reason_codes', jsonb_build_array(
      'MARKET_EXPOSURE_PRODUCER_UNAVAILABLE'
    )
  );
  v_missing_result := market_data.publish_research_prediction_snapshot(
    v_missing_run,
    jsonb_build_array(v_missing_row),
    null
  );
  v_missing_run_id :=
    (v_missing_result ->> 'prediction_run_id')::bigint;
  if (v_missing_result ->> 'market_prediction_count')::integer <> 0
    or not exists (
      select 1
      from market_data.prediction_runs as run
      join market_data.stock_predictions as prediction
        on prediction.prediction_run_id = run.prediction_run_id
      where run.prediction_run_id = v_missing_run_id
        and run.policy_input_missing_count = 1
        and prediction.decision_policy_status = 'MISSING_REQUIRED_DATA'
        and prediction.decision is null
    )
    or exists (
      select 1
      from market_data.market_predictions
      where prediction_run_id = v_missing_run_id
    ) then
    raise exception 'missing market evidence did not remain fail closed';
  end if;
end
$contract$;

rollback;
