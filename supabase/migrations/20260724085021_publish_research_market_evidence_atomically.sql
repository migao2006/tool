begin;

create function market_data.publish_research_prediction_snapshot(
  p_run jsonb,
  p_stock_predictions jsonb,
  p_market_prediction jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, market_data
as $function$
declare
  v_result jsonb;
  v_prediction_run_id bigint;
  v_market text;
  v_p_up numeric;
  v_p_neutral numeric;
  v_p_down numeric;
  v_market_regime text;
  v_forecast_market_volatility numeric;
  v_market_exposure_cap numeric;
  v_model_version text;
  v_training_end_date date;
  v_market_count integer;
  v_candidate_count integer;
  v_no_trade_count integer;
  v_bridge_run jsonb;
  v_bridge_rows jsonb;
  v_persisted_candidate_count integer;
begin
  if jsonb_typeof(p_run) is distinct from 'object'
    or jsonb_typeof(p_stock_predictions) is distinct from 'array'
    or jsonb_array_length(p_stock_predictions) = 0 then
    raise exception using
      errcode = '22023',
      message = 'INVALID_RESEARCH_MARKET_EVIDENCE_PAYLOAD';
  end if;

  if p_market_prediction is null then
    if exists (
      select 1
      from jsonb_array_elements(p_stock_predictions) as item(value)
      where (
        item.value ? 'market_exposure_cap'
        and item.value -> 'market_exposure_cap' <> 'null'::jsonb
      )
        or (
          item.value ? 'market_regime'
          and item.value -> 'market_regime' <> 'null'::jsonb
        )
    ) then
      raise exception using
        errcode = '22023',
        message = 'RESEARCH_MARKET_EVIDENCE_ROW_WITHOUT_PUBLICATION';
    end if;
  elsif jsonb_typeof(p_market_prediction) is distinct from 'object'
    or not (
      p_market_prediction ?& array[
        'market',
        'calibrated_p_up',
        'calibrated_p_neutral',
        'calibrated_p_down',
        'market_regime',
        'forecast_market_volatility',
        'market_exposure_cap',
        'model_version',
        'training_end_date'
      ]
    ) then
    raise exception using
      errcode = '22023',
      message = 'INVALID_RESEARCH_MARKET_EVIDENCE_PAYLOAD';
  else
    begin
      v_market := p_market_prediction ->> 'market';
      v_p_up := (p_market_prediction ->> 'calibrated_p_up')::numeric;
      v_p_neutral :=
        (p_market_prediction ->> 'calibrated_p_neutral')::numeric;
      v_p_down := (p_market_prediction ->> 'calibrated_p_down')::numeric;
      v_market_regime := p_market_prediction ->> 'market_regime';
      v_forecast_market_volatility :=
        (p_market_prediction ->> 'forecast_market_volatility')::numeric;
      v_market_exposure_cap :=
        (p_market_prediction ->> 'market_exposure_cap')::numeric;
      v_model_version := p_market_prediction ->> 'model_version';
      v_training_end_date :=
        (p_market_prediction ->> 'training_end_date')::date;
    exception
      when invalid_text_representation
        or invalid_datetime_format
        or datetime_field_overflow
        or numeric_value_out_of_range then
        raise exception using
          errcode = '22023',
          message = 'INVALID_RESEARCH_MARKET_EVIDENCE_PAYLOAD';
    end;

    if v_market is null
      or v_market not in ('TWSE', 'TPEX')
      or v_market is distinct from p_run ->> 'market_scope'
      or coalesce((p_run ->> 'horizon')::integer, -1) <> 5
      or v_p_up is null
      or v_p_neutral is null
      or v_p_down is null
      or v_p_up not between 0 and 1
      or v_p_neutral not between 0 and 1
      or v_p_down not between 0 and 1
      or abs(v_p_up + v_p_neutral + v_p_down - 1) > 0.000001
      or v_market_regime is null
      or btrim(v_market_regime) = ''
      or v_forecast_market_volatility is null
      or v_forecast_market_volatility < 0
      or v_market_exposure_cap is null
      or v_market_exposure_cap not between 0 and 1
      or v_model_version is null
      or btrim(v_model_version) = ''
      or v_training_end_date is null
      or v_training_end_date >= (p_run ->> 'as_of_date')::date
      or exists (
        select 1
        from jsonb_array_elements(p_stock_predictions) as item(value)
        where item.value ->> 'market' is distinct from v_market
          or item.value ->> 'market_regime'
            is distinct from v_market_regime
          or item.value ->> 'market_exposure_cap' is null
          or abs(
            (item.value ->> 'market_exposure_cap')::numeric
              - v_market_exposure_cap
          ) > 0.00000001
      ) then
      raise exception using
        errcode = '22023',
        message = 'INVALID_RESEARCH_MARKET_EVIDENCE_CONTRACT';
    end if;
  end if;

  select
    count(*) filter (
      where item.value ->> 'decision' = 'CANDIDATE'
    )::integer,
    count(*) filter (
      where item.value ->> 'decision' = 'NO_TRADE'
    )::integer
  into v_candidate_count, v_no_trade_count
  from jsonb_array_elements(p_stock_predictions) as item(value);

  if coalesce((p_run ->> 'candidate_count')::integer, -1)
      <> v_candidate_count
    or coalesce((p_run ->> 'no_trade_count')::integer, -1)
      <> v_no_trade_count then
    raise exception using
      errcode = '22023',
      message = 'RESEARCH_EVALUATED_CANDIDATE_COUNT_MISMATCH';
  end if;

  if v_candidate_count = 0 then
    v_result := market_data.publish_research_prediction_snapshot(
      p_run,
      p_stock_predictions
    );
  else
    -- The status-aware two-argument compatibility publisher predates
    -- authoritative required evidence and rejects CANDIDATE. Bridge only the
    -- storage call, then restore the exact evaluated actions in this same
    -- transaction. RESEARCH_ONLY remains the system status, not an action.
    select jsonb_agg(
      case
        when item.value ->> 'decision' = 'CANDIDATE'
          then item.value || jsonb_build_object(
            'decision',
            'NO_TRADE'
          )
        else item.value
      end
      order by item.ordinality
    )
    into v_bridge_rows
    from jsonb_array_elements(p_stock_predictions)
      with ordinality as item(value, ordinality);
    v_bridge_run := p_run || jsonb_build_object(
      'candidate_count',
      0,
      'no_trade_count',
      v_no_trade_count + v_candidate_count
    );
    v_result := market_data.publish_research_prediction_snapshot(
      v_bridge_run,
      v_bridge_rows
    );
  end if;
  v_prediction_run_id := (v_result ->> 'prediction_run_id')::bigint;

  if v_candidate_count > 0 then
    update market_data.stock_predictions as stored
    set decision = 'CANDIDATE'
    from jsonb_to_recordset(p_stock_predictions) as published(
      security_id bigint,
      decision text,
      decision_policy_status text
    )
    where stored.prediction_run_id = v_prediction_run_id
      and stored.security_id = published.security_id
      and published.decision_policy_status = 'EVALUATED'
      and published.decision = 'CANDIDATE';

    update market_data.prediction_runs
    set
      candidate_count = v_candidate_count,
      no_trade_count = v_no_trade_count
    where prediction_run_id = v_prediction_run_id;

    select count(*)::integer
    into v_persisted_candidate_count
    from market_data.stock_predictions as stored
    where stored.prediction_run_id = v_prediction_run_id
      and stored.decision_policy_status = 'EVALUATED'
      and stored.decision = 'CANDIDATE';
    if v_persisted_candidate_count <> v_candidate_count then
      raise exception using
        errcode = '23514',
        message = 'RESEARCH_EVALUATED_CANDIDATE_COUNT_MISMATCH';
    end if;
  end if;

  if p_market_prediction is not null then
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
      v_prediction_run_id,
      v_market,
      v_p_up,
      v_p_neutral,
      v_p_down,
      v_market_regime,
      v_forecast_market_volatility,
      v_market_exposure_cap,
      v_model_version,
      v_training_end_date
    )
    on conflict (prediction_run_id, market) do nothing;

    if not exists (
      select 1
      from market_data.market_predictions as stored
      where stored.prediction_run_id = v_prediction_run_id
        and stored.market = v_market
        and stored.calibrated_p_up = v_p_up
        and stored.calibrated_p_neutral = v_p_neutral
        and stored.calibrated_p_down = v_p_down
        and stored.market_regime = v_market_regime
        and stored.forecast_market_volatility =
          v_forecast_market_volatility
        and stored.market_exposure_cap = v_market_exposure_cap
        and stored.model_version = v_model_version
        and stored.training_end_date = v_training_end_date
    ) then
      raise exception using
        errcode = '23505',
        message = 'RESEARCH_MARKET_EVIDENCE_IMMUTABILITY_CONFLICT';
    end if;
  elsif exists (
    select 1
    from market_data.market_predictions as stored
    where stored.prediction_run_id = v_prediction_run_id
      and stored.market = p_run ->> 'market_scope'
  ) then
    raise exception using
      errcode = '22023',
      message = 'RESEARCH_MARKET_EVIDENCE_OMITTED_FOR_EXISTING_RUN';
  end if;

  select count(*)::integer
  into v_market_count
  from market_data.market_predictions as stored
  where stored.prediction_run_id = v_prediction_run_id
    and stored.market = p_run ->> 'market_scope';

  if v_market_count <> (
    case when p_market_prediction is null then 0 else 1 end
  ) then
    raise exception using
      errcode = '23514',
      message = 'RESEARCH_MARKET_EVIDENCE_ATOMIC_COUNT_MISMATCH';
  end if;

  return v_result || jsonb_build_object(
    'market_prediction_count',
    v_market_count
  );
end
$function$;

comment on function market_data.publish_research_prediction_snapshot(
  jsonb,
  jsonb,
  jsonb
) is
'Atomic market-scoped RESEARCH_ONLY publisher with optional, exact-run market evidence; service_role only.';

revoke all on function market_data.publish_research_prediction_snapshot(
  jsonb,
  jsonb,
  jsonb
) from public, anon, authenticated;

grant execute on function market_data.publish_research_prediction_snapshot(
  jsonb,
  jsonb,
  jsonb
) to service_role;

commit;
