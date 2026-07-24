begin;

do $validation$
declare
  v_source_id bigint;
  v_security_id bigint;
  v_legacy_security_id bigint;
  v_hard_security_id bigint;
  v_run jsonb;
  v_row jsonb;
  v_result jsonb;
  v_run_id bigint;
  v_empty_run_id bigint;
  v_snapshot jsonb;
begin
  insert into market_data.data_sources (
    source_code,
    display_name,
    source_timezone,
    revision_policy
  )
  values (
    'DECISION_POLICY_VALIDATION',
    'Decision Policy validation',
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
    'decision-policy-validation-v1',
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
    'DPV1',
    'Policy missing validation',
    'TWSE',
    'COMMON_STOCK',
    v_source_id
  )
  returning security_id into v_security_id;

  insert into market_data.securities (
    symbol,
    display_name,
    market,
    asset_type,
    source_id
  )
  values (
    'DPV2',
    'Legacy policy validation',
    'TWSE',
    'COMMON_STOCK',
    v_source_id
  )
  returning security_id into v_legacy_security_id;

  insert into market_data.securities (
    symbol,
    display_name,
    market,
    asset_type,
    source_id
  )
  values (
    'DPV3',
    'Legacy hard fail validation',
    'TWSE',
    'COMMON_STOCK',
    v_source_id
  )
  returning security_id into v_hard_security_id;

  v_run := jsonb_build_object(
    'as_of_date', '2026-07-20',
    'decision_at', '2026-07-20T09:00:00+00:00',
    'horizon', 5,
    'market_scope', 'TWSE',
    'model_bundle_version', 'decision-policy-validation-explicit',
    'feature_schema_hash', repeat('f', 64),
    'benchmark_versions', jsonb_build_object('TWSE', 'validation-v1'),
    'cost_profile_version', 'decision-policy-validation-v1',
    'training_end_date', '2026-06-30',
    'system_validation_status', 'RESEARCH_ONLY',
    'source_dates', jsonb_build_object(
      'prediction_scope', 'DAILY_RESEARCH_INFERENCE',
      'feature_snapshot', repeat('a', 64),
      'snapshot_sha256', repeat('b', 64)
    ),
    'latest_available_at', '2026-07-20T08:30:00+00:00',
    'candidate_count', 0,
    'watch_count', 0,
    'no_trade_count', 0,
    'policy_input_missing_count', 1,
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
    'estimated_round_trip_cost', 0.006,
    'data_quality_status', 'WARN',
    'decision', null,
    'decision_policy_status', 'MISSING_REQUIRED_DATA',
    'reason_codes', jsonb_build_array(
      'FORMAL_MARKET_EXPOSURE_INPUT_MISSING'
    )
  );
  v_result := market_data.publish_research_prediction_snapshot(
    v_run,
    jsonb_build_array(v_row)
  );
  v_run_id := (v_result ->> 'prediction_run_id')::bigint;

  if not exists (
    select 1
    from market_data.prediction_runs as run
    join market_data.stock_predictions as prediction
      on prediction.prediction_run_id = run.prediction_run_id
    where run.prediction_run_id = v_run_id
      and run.no_trade_count = 0
      and run.policy_input_missing_count = 1
      and prediction.decision is null
      and prediction.decision_policy_status = 'MISSING_REQUIRED_DATA'
      and prediction.data_quality_status = 'WARN'
  ) then
    raise exception 'explicit missing-policy contract was not persisted';
  end if;

  v_run := v_run || jsonb_build_object(
    'as_of_date', '2026-07-21',
    'decision_at', '2026-07-21T09:00:00+00:00',
    'model_bundle_version', 'decision-policy-validation-legacy',
    'source_dates', jsonb_build_object(
      'prediction_scope', 'DAILY_RESEARCH_INFERENCE',
      'feature_snapshot', repeat('c', 64),
      'snapshot_sha256', repeat('d', 64)
    ),
    'latest_available_at', '2026-07-21T08:30:00+00:00',
    'no_trade_count', 1
  );
  v_row := (v_row - 'decision_policy_status') || jsonb_build_object(
    'security_id', v_legacy_security_id,
    'data_quality_status', 'FAIL',
    'decision', 'NO_TRADE',
    'reason_codes', jsonb_build_array('RESEARCH_DATA_QUALITY_WARN')
  );
  v_result := market_data.publish_research_prediction_snapshot(
    v_run,
    jsonb_build_array(v_row)
  );
  v_run_id := (v_result ->> 'prediction_run_id')::bigint;

  if not exists (
    select 1
    from market_data.prediction_runs as run
    join market_data.stock_predictions as prediction
      on prediction.prediction_run_id = run.prediction_run_id
    where run.prediction_run_id = v_run_id
      and run.no_trade_count = 0
      and run.policy_input_missing_count = 0
      and run.policy_validation_failed_count = 1
      and prediction.decision is null
      and prediction.decision_policy_status = 'VALIDATION_FAILED'
      and prediction.data_quality_status = 'WARN'
      and 'DECISION_POLICY_VALIDATION_FAILED' =
        any(prediction.reason_codes)
  ) then
    raise exception 'unclassified legacy NO_TRADE was not validation-failed';
  end if;

  v_run := v_run || jsonb_build_object(
    'as_of_date', '2026-07-22',
    'decision_at', '2026-07-22T09:00:00+00:00',
    'model_bundle_version', 'decision-policy-validation-legacy-hard',
    'source_dates', jsonb_build_object(
      'prediction_scope', 'DAILY_RESEARCH_INFERENCE',
      'feature_snapshot', repeat('e', 64),
      'snapshot_sha256', repeat('f', 64)
    ),
    'latest_available_at', '2026-07-22T08:30:00+00:00'
  );
  v_row := (v_row - 'decision_policy_status') || jsonb_build_object(
    'security_id', v_hard_security_id,
    'data_quality_status', 'HARD_FAIL',
    'decision', 'NO_TRADE',
    'reason_codes', jsonb_build_array('AUDIT_HARD_FAIL')
  );
  v_result := market_data.publish_research_prediction_snapshot(
    v_run,
    jsonb_build_array(v_row)
  );
  v_run_id := (v_result ->> 'prediction_run_id')::bigint;

  if not exists (
    select 1
    from market_data.prediction_runs as run
    join market_data.stock_predictions as prediction
      on prediction.prediction_run_id = run.prediction_run_id
    where run.prediction_run_id = v_run_id
      and run.no_trade_count = 0
      and run.policy_input_missing_count = 0
      and run.policy_hard_fail_count = 1
      and prediction.decision is null
      and prediction.decision_policy_status = 'HARD_FAIL'
      and prediction.data_quality_status = 'HARD_FAIL'
      and 'DATA_QUALITY_HARD_FAIL' = any(prediction.reason_codes)
  ) then
    raise exception 'legacy hard fail was reclassified as missing';
  end if;

  begin
    perform market_data.publish_research_prediction_snapshot(
      v_run || jsonb_build_object(
        'as_of_date', '2026-07-23',
        'decision_at', '2026-07-23T09:00:00+00:00',
        'model_bundle_version', 'decision-policy-validation-invalid-legacy',
        'latest_available_at', '2026-07-23T08:30:00+00:00'
      ),
      jsonb_build_array(
        v_row || jsonb_build_object('data_quality_status', 'UNKNOWN')
      )
    );
    raise exception 'unknown legacy quality was accepted';
  exception
    when sqlstate '22023' then
      if sqlerrm <> 'INVALID_LEGACY_RESEARCH_DECISION_POLICY_CONTRACT' then
        raise;
      end if;
  end;

  begin
    perform market_data.publish_research_prediction_snapshot(
      v_run || jsonb_build_object(
        'as_of_date', '2026-07-24',
        'decision_at', '2026-07-24T09:00:00+00:00',
        'model_bundle_version', 'decision-policy-validation-warn-action',
        'latest_available_at', '2026-07-24T08:30:00+00:00',
        'no_trade_count', 1,
        'policy_input_missing_count', 0,
        'policy_validation_failed_count', 0,
        'policy_hard_fail_count', 0,
        'hard_fail_count', 0
      ),
      jsonb_build_array(
        v_row || jsonb_build_object(
          'data_quality_status', 'WARN',
          'decision', 'NO_TRADE',
          'decision_policy_status', 'EVALUATED'
        )
      )
    );
    raise exception 'WARN quality was allowed to carry an evaluated action';
  exception
    when sqlstate '22023' then
      if sqlerrm <> 'INVALID_RESEARCH_DECISION_POLICY_CONTRACT' then
        raise;
      end if;
  end;

  v_snapshot := market_data.get_prediction_snapshot_rows_v2(
    5,
    'TWSE',
    statement_timestamp()
  );
  if v_snapshot -> 'run' ->> 'policy_hard_fail_count' <> '1'
    or v_snapshot -> 'predictions' -> 0 ->> 'decision_policy_status'
      <> 'HARD_FAIL'
    or v_snapshot -> 'predictions' -> 0 -> 'decision'
      <> 'null'::jsonb then
    raise exception 'read RPC omitted the Decision Policy status contract';
  end if;

  begin
    update market_data.stock_predictions
    set
      data_quality_status = 'HARD_FAIL',
      decision_policy_status = 'HARD_FAIL',
      decision = 'CANDIDATE'
    where prediction_run_id = v_run_id;
    raise exception 'HARD_FAIL was allowed to become CANDIDATE';
  exception
    when check_violation then null;
  end;

  begin
    update market_data.stock_predictions
    set
      data_quality_status = 'WARN',
      decision_policy_status = 'EVALUATED',
      decision = 'NO_TRADE'
    where prediction_run_id = v_run_id;
    raise exception 'WARN quality was allowed to persist an evaluated action';
  exception
    when check_violation then null;
  end;

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
    policy_input_missing_count,
    policy_validation_failed_count,
    policy_hard_fail_count,
    hard_fail_count
  )
  values (
    '2026-07-25',
    '2026-07-25T09:00:00+00:00',
    5,
    'TWSE',
    'decision-policy-validation-empty-formal',
    repeat('1', 64),
    jsonb_build_object('TWSE', 'validation-v1'),
    'decision-policy-validation-v1',
    '2026-06-30',
    'PASS',
    jsonb_build_object('daily_bars', '2026-07-25'),
    '2026-07-25T08:30:00+00:00',
    0,
    0,
    0,
    0,
    0,
    0,
    0
  )
  returning prediction_run_id into v_empty_run_id;

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
  )
  values (
    v_empty_run_id,
    'TWSE',
    0.6,
    0.25,
    0.15,
    'VALIDATION',
    0.18,
    0.6,
    'validation-market-v1',
    '2026-06-30'
  );

  perform market_data.refresh_home_data_status();
  if not exists (
    select 1
    from public.home_data_status
    where status_key = 'latest'
      and model_output_status = 'RESEARCH_ONLY'
      and 'MODEL_OUTPUT_INCOMPLETE' = any(reason_codes)
  ) then
    raise exception 'empty all-zero formal universe was promoted to PASS';
  end if;

  update market_data.prediction_runs
  set candidate_count = 1
  where prediction_run_id = v_empty_run_id;
  perform market_data.refresh_home_data_status();
  if not exists (
    select 1
    from public.home_data_status
    where status_key = 'latest'
      and model_output_status = 'RESEARCH_ONLY'
      and 'MODEL_OUTPUT_INCOMPLETE' = any(reason_codes)
  ) then
    raise exception 'missing formal row was hidden by its manifest';
  end if;
end
$validation$;

rollback;
