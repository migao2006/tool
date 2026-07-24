do $validation$
begin
  if not exists (
    select 1
    from market_data.stock_predictions as prediction
    join market_data.prediction_runs as run
      on run.prediction_run_id = prediction.prediction_run_id
    join market_data.securities as security
      on security.security_id = prediction.security_id
    where security.market = 'TWSE'
      and security.symbol = 'LDP1'
      and prediction.decision is null
      and prediction.decision_policy_status = 'MISSING_REQUIRED_DATA'
      and prediction.data_quality_status = 'WARN'
      and prediction.global_rank = 1
      and prediction.rank_score = 100
      and prediction.calibrated_p_up = 0.6
      and prediction.net_q50 = 0.004
      and run.candidate_count = 0
      and run.watch_count = 0
      and run.no_trade_count = 0
      and run.policy_input_missing_count = 2
      and run.policy_validation_failed_count = 1
      and run.policy_hard_fail_count = 1
      and run.hard_fail_count = 1
  ) then
    raise exception
      'legacy research row was not backfilled without changing model output';
  end if;
  if not exists (
    select 1
    from market_data.stock_predictions as prediction
    join market_data.securities as security
      on security.security_id = prediction.security_id
    where security.market = 'TWSE'
      and security.symbol = 'LDP2'
      and prediction.decision is null
      and prediction.decision_policy_status = 'MISSING_REQUIRED_DATA'
      and prediction.data_quality_status = 'WARN'
      and prediction.global_rank = 2
      and prediction.rank_score = 50
      and prediction.calibrated_p_up = 0.6
      and prediction.net_q50 = 0.004
  ) then
    raise exception
      'non-hard audit authority was not preserved during backfill';
  end if;
  if not exists (
    select 1
    from market_data.stock_predictions as prediction
    join market_data.securities as security
      on security.security_id = prediction.security_id
    where security.market = 'TWSE'
      and security.symbol = 'LDP3'
      and prediction.decision is null
      and prediction.decision_policy_status = 'HARD_FAIL'
      and prediction.data_quality_status = 'HARD_FAIL'
      and prediction.global_rank = 3
      and prediction.rank_score = 0
      and prediction.calibrated_p_up = 0.6
      and prediction.net_q50 = 0.004
  ) then
    raise exception
      'hard-fail audit authority was not preserved during backfill';
  end if;
  if not exists (
    select 1
    from market_data.stock_predictions as prediction
    join market_data.securities as security
      on security.security_id = prediction.security_id
    where security.market = 'TWSE'
      and security.symbol = 'LDP4'
      and prediction.decision is null
      and prediction.decision_policy_status = 'VALIDATION_FAILED'
      and prediction.data_quality_status = 'PASS'
      and prediction.global_rank = 4
      and prediction.rank_score = 0
      and prediction.calibrated_p_up = 0.6
      and prediction.net_q50 = 0.004
      and 'DECISION_POLICY_VALIDATION_FAILED' =
        any(prediction.reason_codes)
  ) then
    raise exception
      'unclassified legacy policy row was not failed closed as validation';
  end if;
end
$validation$;
