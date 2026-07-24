begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

alter table market_data.prediction_runs
  add column policy_input_missing_count integer not null default 0,
  add column policy_validation_failed_count integer not null default 0,
  add column policy_hard_fail_count integer not null default 0;

alter table market_data.stock_predictions
  add column decision_policy_status text;

alter table market_data.stock_predictions
  drop constraint if exists stock_predictions_data_quality_status_check;
alter table market_data.stock_predictions
  drop constraint if exists stock_predictions_decision_check;
alter table market_data.stock_predictions
  drop constraint if exists stock_predictions_decision_quality_check;

alter table market_data.stock_predictions
  alter column decision drop not null;

update market_data.stock_predictions as prediction
set data_quality_status = case
  when exists (
    select 1
    from market_data.data_quality_audits as audit
    where audit.prediction_run_id = prediction.prediction_run_id
      and audit.security_id = prediction.security_id
      and audit.hard_fail
  ) then 'HARD_FAIL'
  when exists (
    select 1
    from market_data.data_quality_audits as audit
    where audit.prediction_run_id = prediction.prediction_run_id
      and audit.security_id = prediction.security_id
      and not audit.hard_fail
      and audit.quality_status = 'FAIL'
  ) then 'WARN'
  when exists (
    select 1
    from market_data.data_quality_audits as audit
    where audit.prediction_run_id = prediction.prediction_run_id
      and audit.security_id = prediction.security_id
      and not audit.hard_fail
      and audit.quality_status = 'PASS'
  ) then 'PASS'
  when prediction.data_quality_status = 'FAIL'
    and 'RESEARCH_DATA_QUALITY_WARN' = any(prediction.reason_codes)
    then 'WARN'
  when prediction.data_quality_status = 'FAIL'
    then 'HARD_FAIL'
  else prediction.data_quality_status
end;

update market_data.stock_predictions as prediction
set decision_policy_status = case
  when prediction.data_quality_status = 'HARD_FAIL' then 'HARD_FAIL'
  when exists (
      select 1
      from market_data.decision_gate_results as gate
      where gate.stock_prediction_id = prediction.stock_prediction_id
        and (
          gate.reason_code like '%MISSING%'
          or gate.reason_code like '%UNAVAILABLE%'
        )
    )
    or exists (
      select 1
      from unnest(prediction.reason_codes) as reason(code)
      where reason.code = 'REQUIRED_DECISION_POLICY_DATA_MISSING'
        or reason.code = 'RESEARCH_ONLY_NO_FORMAL_DECISION_POLICY'
        or reason.code like '%\_INPUT\_MISSING' escape '\'
        or reason.code like '%SOURCE\_DATE\_MISSING%' escape '\'
    )
    then 'MISSING_REQUIRED_DATA'
  when prediction.data_quality_status <> 'PASS'
    or run.system_validation_status in ('RESEARCH_ONLY', 'FAIL')
    then 'VALIDATION_FAILED'
  else 'EVALUATED'
end
from market_data.prediction_runs as run
where run.prediction_run_id = prediction.prediction_run_id;

update market_data.stock_predictions
set
  decision = null,
  reason_codes = case
    when decision_policy_status = 'MISSING_REQUIRED_DATA'
      and not (
        'REQUIRED_DECISION_POLICY_DATA_MISSING' = any(reason_codes)
      )
      then array_append(
        reason_codes,
        'REQUIRED_DECISION_POLICY_DATA_MISSING'
      )
    when decision_policy_status = 'HARD_FAIL'
      and not ('DATA_QUALITY_HARD_FAIL' = any(reason_codes))
      then array_append(reason_codes, 'DATA_QUALITY_HARD_FAIL')
    when decision_policy_status = 'VALIDATION_FAILED'
      and not ('DECISION_POLICY_VALIDATION_FAILED' = any(reason_codes))
      then array_append(reason_codes, 'DECISION_POLICY_VALIDATION_FAILED')
    else reason_codes
  end
where decision_policy_status <> 'EVALUATED';

alter table market_data.stock_predictions
  alter column decision_policy_status set not null;

alter table market_data.stock_predictions
  add constraint stock_predictions_data_quality_status_check
    check (data_quality_status in ('PASS', 'WARN', 'HARD_FAIL')),
  add constraint stock_predictions_decision_check
    check (
      decision is null
      or decision in ('CANDIDATE', 'WATCH', 'NO_TRADE')
    ),
  add constraint stock_predictions_decision_policy_status_check
    check (
      decision_policy_status in (
        'EVALUATED',
        'MISSING_REQUIRED_DATA',
        'VALIDATION_FAILED',
        'HARD_FAIL'
      )
    ),
  add constraint stock_predictions_decision_policy_consistency_check
    check (
      (
        decision_policy_status = 'EVALUATED'
        and decision is not null
      )
      or (
        decision_policy_status <> 'EVALUATED'
        and decision is null
      )
    ),
  add constraint stock_predictions_decision_quality_check
    check (
      (
        decision_policy_status <> 'EVALUATED'
        or data_quality_status = 'PASS'
      )
      and (
        (decision_policy_status = 'HARD_FAIL')
        = (data_quality_status = 'HARD_FAIL')
      )
    );

comment on column market_data.stock_predictions.decision is
'Decision Policy action. NULL means no valid policy action was produced; inspect decision_policy_status.';
comment on column market_data.stock_predictions.decision_policy_status is
'Evaluation state distinct from the action: EVALUATED, MISSING_REQUIRED_DATA, VALIDATION_FAILED, or HARD_FAIL.';
comment on column market_data.prediction_runs.no_trade_count is
'Count of EVALUATED rows whose policy action is NO_TRADE; missing or invalid policy inputs are excluded.';
comment on column market_data.prediction_runs.policy_input_missing_count is
'Count of rows that failed closed because mandatory Decision Policy evidence was missing.';
comment on column market_data.prediction_runs.policy_validation_failed_count is
'Count of rows whose Decision Policy input or output contract failed validation.';
comment on column market_data.prediction_runs.policy_hard_fail_count is
'Count of published prediction rows with Decision Policy HARD_FAIL status.';

create index stock_predictions_run_policy_status_idx
on market_data.stock_predictions (
  prediction_run_id,
  decision_policy_status,
  global_rank
);

with counts as (
  select
    run.prediction_run_id,
    count(*) filter (
      where prediction.decision_policy_status = 'EVALUATED'
        and prediction.decision = 'CANDIDATE'
    )::integer as candidate_count,
    count(*) filter (
      where prediction.decision_policy_status = 'EVALUATED'
        and prediction.decision = 'WATCH'
    )::integer as watch_count,
    count(*) filter (
      where prediction.decision_policy_status = 'EVALUATED'
        and prediction.decision = 'NO_TRADE'
    )::integer as no_trade_count,
    count(*) filter (
      where prediction.decision_policy_status = 'MISSING_REQUIRED_DATA'
    )::integer as policy_input_missing_count,
    count(*) filter (
      where prediction.decision_policy_status = 'VALIDATION_FAILED'
    )::integer as policy_validation_failed_count,
    count(*) filter (
      where prediction.decision_policy_status = 'HARD_FAIL'
    )::integer as policy_hard_fail_count,
    (
      select count(distinct excluded.security_id)::integer
      from (
        select hard_prediction.security_id
        from market_data.stock_predictions as hard_prediction
        where hard_prediction.prediction_run_id = run.prediction_run_id
          and hard_prediction.decision_policy_status = 'HARD_FAIL'
        union
        select audit.security_id
        from market_data.data_quality_audits as audit
        where audit.prediction_run_id = run.prediction_run_id
          and audit.hard_fail
      ) as excluded
    ) as hard_fail_count
  from market_data.prediction_runs as run
  left join market_data.stock_predictions as prediction
    on prediction.prediction_run_id = run.prediction_run_id
  group by run.prediction_run_id
)
update market_data.prediction_runs as run
set
  candidate_count = counts.candidate_count,
  watch_count = counts.watch_count,
  no_trade_count = counts.no_trade_count,
  policy_input_missing_count = counts.policy_input_missing_count,
  policy_validation_failed_count = counts.policy_validation_failed_count,
  policy_hard_fail_count = counts.policy_hard_fail_count,
  hard_fail_count = counts.hard_fail_count
from counts
where counts.prediction_run_id = run.prediction_run_id;

alter table market_data.prediction_runs
  drop constraint if exists prediction_runs_nonnegative_counts_check;
alter table market_data.prediction_runs
  add constraint prediction_runs_nonnegative_counts_check check (
    candidate_count >= 0
    and watch_count >= 0
    and no_trade_count >= 0
    and policy_input_missing_count >= 0
    and policy_validation_failed_count >= 0
    and policy_hard_fail_count >= 0
    and hard_fail_count >= 0
  );

-- The bridge is enabled only inside the new service-role publisher while it
-- reuses the proven atomic insert/upsert implementation. No bridged state can
-- commit because the wrapper immediately replaces it with the normalized
-- action/status contract in the same transaction.
create function market_data.prepare_decision_policy_bridge()
returns trigger
language plpgsql
set search_path = pg_catalog, market_data
as $function$
begin
  if current_setting(
    'alpha_lens.decision_policy_bridge',
    true
  ) = 'enabled'
    and current_user = pg_get_userbyid((
      select relation.relowner
      from pg_catalog.pg_class as relation
      where relation.oid = tg_relid
    )) then
    new.decision_policy_status := 'EVALUATED';
  end if;
  return new;
end
$function$;

revoke all on function market_data.prepare_decision_policy_bridge()
from public, anon, authenticated, service_role;

create trigger stock_predictions_decision_policy_bridge
before insert or update of decision, data_quality_status
on market_data.stock_predictions
for each row
execute function market_data.prepare_decision_policy_bridge();

alter function market_data.publish_research_prediction_snapshot(jsonb, jsonb)
rename to publish_research_prediction_snapshot_policy_v1;
revoke all on function
market_data.publish_research_prediction_snapshot_policy_v1(jsonb, jsonb)
from public, anon, authenticated, service_role;

create function market_data.publish_research_prediction_snapshot(
  p_run jsonb,
  p_stock_predictions jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, market_data
as $function$
declare
  v_all_legacy boolean;
  v_all_explicit boolean;
  v_normalized_rows jsonb;
  v_bridge_rows jsonb;
  v_bridge_run jsonb;
  v_result jsonb;
  v_prediction_run_id bigint;
  v_expected_count integer;
  v_candidate_count integer;
  v_watch_count integer;
  v_no_trade_count integer;
  v_missing_count integer;
  v_validation_failed_count integer;
  v_policy_hard_fail_count integer;
  v_actual_count integer;
begin
  if jsonb_typeof(p_run) is distinct from 'object'
    or jsonb_typeof(p_stock_predictions) is distinct from 'array'
    or jsonb_array_length(p_stock_predictions) = 0 then
    raise exception using
      errcode = '22023',
      message = 'INVALID_RESEARCH_DECISION_POLICY_PAYLOAD';
  end if;
  v_expected_count := jsonb_array_length(p_stock_predictions);

  select
    bool_and(not (item.value ? 'decision_policy_status')),
    bool_and(item.value ? 'decision_policy_status')
  into v_all_legacy, v_all_explicit
  from jsonb_array_elements(p_stock_predictions) as item(value);
  if not v_all_legacy and not v_all_explicit then
    raise exception using
      errcode = '22023',
      message = 'MIXED_RESEARCH_DECISION_POLICY_CONTRACT';
  end if;
  if v_all_legacy and exists (
    select 1
    from jsonb_array_elements(p_stock_predictions) as item(value)
    where not (item.value ?& array[
      'decision',
      'data_quality_status',
      'reason_codes'
    ])
      or item.value ->> 'decision' is null
      or item.value ->> 'decision' not in (
        'CANDIDATE',
        'WATCH',
        'NO_TRADE'
      )
      or item.value ->> 'data_quality_status' is null
      or item.value ->> 'data_quality_status' not in (
        'PASS',
        'WARN',
        'FAIL',
        'HARD_FAIL'
      )
      or jsonb_typeof(item.value -> 'reason_codes') is distinct from 'array'
  ) then
    raise exception using
      errcode = '22023',
      message = 'INVALID_LEGACY_RESEARCH_DECISION_POLICY_CONTRACT';
  end if;

  select jsonb_agg(
    case
      when v_all_legacy then
        item.value || jsonb_build_object(
          'decision',
          null,
          'decision_policy_status',
          case
            when item.value ->> 'data_quality_status' = 'HARD_FAIL'
              or (
                item.value ->> 'data_quality_status' = 'FAIL'
                and not (
                  (item.value -> 'reason_codes')
                  ? 'RESEARCH_DATA_QUALITY_WARN'
                )
              )
              then 'HARD_FAIL'
            when exists (
              select 1
              from jsonb_array_elements_text(
                item.value -> 'reason_codes'
              ) as reason(code)
              where reason.code in (
                'REQUIRED_DECISION_POLICY_DATA_MISSING',
                'RESEARCH_ONLY_NO_FORMAL_DECISION_POLICY'
              )
                or reason.code like '%\_INPUT\_MISSING' escape '\'
                or reason.code like '%SOURCE\_DATE\_MISSING%' escape '\'
            ) then 'MISSING_REQUIRED_DATA'
            else 'VALIDATION_FAILED'
          end,
          'data_quality_status',
          case
            when item.value ->> 'data_quality_status' = 'HARD_FAIL'
              or (
                item.value ->> 'data_quality_status' = 'FAIL'
                and not (
                  (item.value -> 'reason_codes')
                  ? 'RESEARCH_DATA_QUALITY_WARN'
                )
              )
              then 'HARD_FAIL'
            when item.value ->> 'data_quality_status' in ('FAIL', 'WARN')
              then 'WARN'
            else 'PASS'
          end,
          'reason_codes',
          case
            when (
              item.value ->> 'data_quality_status' = 'HARD_FAIL'
              or (
                item.value ->> 'data_quality_status' = 'FAIL'
                and not (
                  (item.value -> 'reason_codes')
                  ? 'RESEARCH_DATA_QUALITY_WARN'
                )
              )
            )
              and not (
                (item.value -> 'reason_codes') ? 'DATA_QUALITY_HARD_FAIL'
              )
              then (item.value -> 'reason_codes')
                || jsonb_build_array('DATA_QUALITY_HARD_FAIL')
            when exists (
              select 1
              from jsonb_array_elements_text(
                item.value -> 'reason_codes'
              ) as reason(code)
              where reason.code in (
                'REQUIRED_DECISION_POLICY_DATA_MISSING',
                'RESEARCH_ONLY_NO_FORMAL_DECISION_POLICY'
              )
                or reason.code like '%\_INPUT\_MISSING' escape '\'
                or reason.code like '%SOURCE\_DATE\_MISSING%' escape '\'
            )
              and not (
                (item.value -> 'reason_codes')
                ? 'REQUIRED_DECISION_POLICY_DATA_MISSING'
              )
              then (item.value -> 'reason_codes')
                || jsonb_build_array(
                  'REQUIRED_DECISION_POLICY_DATA_MISSING'
                )
            when not exists (
              select 1
              from jsonb_array_elements_text(
                item.value -> 'reason_codes'
              ) as reason(code)
              where reason.code in (
                'REQUIRED_DECISION_POLICY_DATA_MISSING',
                'RESEARCH_ONLY_NO_FORMAL_DECISION_POLICY'
              )
                or reason.code like '%\_INPUT\_MISSING' escape '\'
                or reason.code like '%SOURCE\_DATE\_MISSING%' escape '\'
            )
              and not (
                (item.value -> 'reason_codes')
                ? 'DECISION_POLICY_VALIDATION_FAILED'
              )
              then (item.value -> 'reason_codes')
                || jsonb_build_array(
                  'DECISION_POLICY_VALIDATION_FAILED'
                )
            else item.value -> 'reason_codes'
          end
        )
      else item.value
    end
    order by item.ordinality
  )
  into v_normalized_rows
  from jsonb_array_elements(p_stock_predictions)
    with ordinality as item(value, ordinality);

  if exists (
    select 1
    from jsonb_array_elements(v_normalized_rows) as item(value)
    where not (item.value ?& array[
      'security_id',
      'market',
      'global_rank',
      'decision',
      'decision_policy_status',
      'data_quality_status',
      'reason_codes'
    ])
      or item.value ->> 'decision_policy_status' is null
      or item.value ->> 'decision_policy_status' not in (
        'EVALUATED',
        'MISSING_REQUIRED_DATA',
        'VALIDATION_FAILED',
        'HARD_FAIL'
      )
      or item.value ->> 'data_quality_status' is null
      or item.value ->> 'data_quality_status' not in (
        'PASS',
        'WARN',
        'HARD_FAIL'
      )
      or jsonb_typeof(item.value -> 'reason_codes') is distinct from 'array'
      or (
        item.value ->> 'decision_policy_status' = 'EVALUATED'
        and item.value ->> 'decision' not in (
          'CANDIDATE',
          'WATCH',
          'NO_TRADE'
        )
      )
      or (
        item.value ->> 'decision_policy_status' = 'EVALUATED'
        and item.value ->> 'data_quality_status' <> 'PASS'
      )
      or (
        item.value ->> 'decision_policy_status' <> 'EVALUATED'
        and item.value -> 'decision' <> 'null'::jsonb
      )
      or item.value ->> 'decision' = 'CANDIDATE'
      or (
        (
          item.value ->> 'decision_policy_status' = 'HARD_FAIL'
        ) <> (
          item.value ->> 'data_quality_status' = 'HARD_FAIL'
        )
      )
  ) then
    raise exception using
      errcode = '22023',
      message = 'INVALID_RESEARCH_DECISION_POLICY_CONTRACT';
  end if;

  select
    count(*) filter (
      where item.value ->> 'decision_policy_status' = 'EVALUATED'
        and item.value ->> 'decision' = 'CANDIDATE'
    )::integer,
    count(*) filter (
      where item.value ->> 'decision_policy_status' = 'EVALUATED'
        and item.value ->> 'decision' = 'WATCH'
    )::integer,
    count(*) filter (
      where item.value ->> 'decision_policy_status' = 'EVALUATED'
        and item.value ->> 'decision' = 'NO_TRADE'
    )::integer,
    count(*) filter (
      where item.value ->> 'decision_policy_status' =
        'MISSING_REQUIRED_DATA'
    )::integer,
    count(*) filter (
      where item.value ->> 'decision_policy_status' = 'VALIDATION_FAILED'
    )::integer,
    count(*) filter (
      where item.value ->> 'decision_policy_status' = 'HARD_FAIL'
    )::integer
  into
    v_candidate_count,
    v_watch_count,
    v_no_trade_count,
    v_missing_count,
    v_validation_failed_count,
    v_policy_hard_fail_count
  from jsonb_array_elements(v_normalized_rows) as item(value);

  if (
    v_candidate_count
    + v_watch_count
    + v_no_trade_count
    + v_missing_count
    + v_validation_failed_count
    + v_policy_hard_fail_count
  ) <> v_expected_count then
    raise exception using
      errcode = '22023',
      message = 'RESEARCH_DECISION_POLICY_STATUS_COVERAGE_INCOMPLETE';
  end if;

  if not v_all_legacy and (
    coalesce((p_run ->> 'candidate_count')::integer, -1)
      <> v_candidate_count
    or coalesce((p_run ->> 'watch_count')::integer, -1)
      <> v_watch_count
    or coalesce((p_run ->> 'no_trade_count')::integer, -1)
      <> v_no_trade_count
    or coalesce((p_run ->> 'policy_input_missing_count')::integer, -1)
      <> v_missing_count
    or coalesce(
      (p_run ->> 'policy_validation_failed_count')::integer,
      -1
    ) <> v_validation_failed_count
    or coalesce((p_run ->> 'policy_hard_fail_count')::integer, -1)
      <> v_policy_hard_fail_count
    or coalesce((p_run ->> 'hard_fail_count')::integer, -1)
      <> v_policy_hard_fail_count
  ) then
    raise exception using
      errcode = '22023',
      message = 'RESEARCH_DECISION_POLICY_COUNTS_DO_NOT_MATCH_ROWS';
  end if;

  select jsonb_agg(
    (item.value - 'decision_policy_status')
      || jsonb_build_object(
        'decision',
        'NO_TRADE',
        'data_quality_status',
        'PASS'
      )
    order by item.ordinality
  )
  into v_bridge_rows
  from jsonb_array_elements(v_normalized_rows)
    with ordinality as item(value, ordinality);
  v_bridge_run := p_run || jsonb_build_object(
    'candidate_count', 0,
    'watch_count', 0,
    'no_trade_count', v_expected_count,
    'hard_fail_count', 0
  );

  perform set_config(
    'alpha_lens.decision_policy_bridge',
    'enabled',
    true
  );
  begin
    v_result :=
      market_data.publish_research_prediction_snapshot_policy_v1(
        v_bridge_run,
        v_bridge_rows
      );
  exception when others then
    perform set_config(
      'alpha_lens.decision_policy_bridge',
      'disabled',
      true
    );
    raise;
  end;
  perform set_config(
    'alpha_lens.decision_policy_bridge',
    'disabled',
    true
  );

  v_prediction_run_id := (v_result ->> 'prediction_run_id')::bigint;
  update market_data.stock_predictions as prediction
  set
    data_quality_status = normalized.data_quality_status,
    decision = normalized.decision,
    decision_policy_status = normalized.decision_policy_status,
    reason_codes = normalized.reason_codes
  from jsonb_to_recordset(v_normalized_rows) as normalized(
    security_id bigint,
    data_quality_status text,
    decision text,
    decision_policy_status text,
    reason_codes text[]
  )
  where prediction.prediction_run_id = v_prediction_run_id
    and prediction.security_id = normalized.security_id;

  update market_data.prediction_runs
  set
    candidate_count = v_candidate_count,
    watch_count = v_watch_count,
    no_trade_count = v_no_trade_count,
    policy_input_missing_count = v_missing_count,
    policy_validation_failed_count = v_validation_failed_count,
    policy_hard_fail_count = v_policy_hard_fail_count,
    hard_fail_count = v_policy_hard_fail_count
  where prediction_run_id = v_prediction_run_id;

  select count(*)::integer
  into v_actual_count
  from market_data.stock_predictions
  where prediction_run_id = v_prediction_run_id
    and (
      (
        decision_policy_status = 'EVALUATED'
        and decision is not null
      )
      or (
        decision_policy_status <> 'EVALUATED'
        and decision is null
      )
    );
  if v_actual_count <> v_expected_count then
    raise exception using
      errcode = '23514',
      message = 'RESEARCH_DECISION_POLICY_ATOMIC_ROW_COUNT_MISMATCH';
  end if;

  return v_result;
end
$function$;

comment on function market_data.publish_research_prediction_snapshot(
  jsonb,
  jsonb
) is
'Atomic market-scoped RESEARCH_ONLY publisher with distinct Decision Policy action and evaluation status; service_role only.';
revoke all on function market_data.publish_research_prediction_snapshot(
  jsonb,
  jsonb
) from public, anon, authenticated;
grant execute on function market_data.publish_research_prediction_snapshot(
  jsonb,
  jsonb
) to service_role;

alter function market_data.get_prediction_snapshot_rows(
  integer,
  text,
  timestamptz
) rename to get_prediction_snapshot_rows_policy_v1;
revoke all on function market_data.get_prediction_snapshot_rows_policy_v1(
  integer,
  text,
  timestamptz
) from public, anon, authenticated;
grant execute on function market_data.get_prediction_snapshot_rows_policy_v1(
  integer,
  text,
  timestamptz
) to service_role;

create function market_data.get_prediction_snapshot_rows(
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
  v_payload jsonb;
  v_run_id bigint;
  v_run jsonb;
  v_predictions jsonb;
begin
  v_payload := market_data.get_prediction_snapshot_rows_policy_v1(
    p_horizon,
    p_market_scope,
    p_observed_at
  );
  if v_payload is null then
    return null;
  end if;
  v_run_id := (v_payload -> 'run' ->> 'prediction_run_id')::bigint;

  select (v_payload -> 'run') || jsonb_build_object(
    'policy_input_missing_count',
    run.policy_input_missing_count,
    'policy_validation_failed_count',
    run.policy_validation_failed_count,
    'policy_hard_fail_count',
    run.policy_hard_fail_count
  )
  into v_run
  from market_data.prediction_runs as run
  where run.prediction_run_id = v_run_id;

  select coalesce(
    jsonb_agg(
      item.value || jsonb_build_object(
        'decision',
        prediction.decision,
        'decision_policy_status',
        prediction.decision_policy_status,
        'data_quality_status',
        prediction.data_quality_status
      )
      order by item.ordinality
    ),
    '[]'::jsonb
  )
  into v_predictions
  from jsonb_array_elements(v_payload -> 'predictions')
    with ordinality as item(value, ordinality)
  join market_data.stock_predictions as prediction
    on prediction.stock_prediction_id =
      (item.value ->> 'stock_prediction_id')::bigint
    and prediction.prediction_run_id = v_run_id;

  return jsonb_set(
    jsonb_set(v_payload, '{run}', v_run),
    '{predictions}',
    v_predictions
  );
end
$function$;

comment on function market_data.get_prediction_snapshot_rows(
  integer,
  text,
  timestamptz
) is
'Returns one complete latest prediction snapshot with explicit Decision Policy action/status and counters; service_role only.';
revoke all on function market_data.get_prediction_snapshot_rows(
  integer,
  text,
  timestamptz
) from public, anon, authenticated;
grant execute on function market_data.get_prediction_snapshot_rows(
  integer,
  text,
  timestamptz
) to service_role;

create or replace function market_data.refresh_home_data_status()
returns void
language plpgsql
security invoker
set search_path = pg_catalog, public, market_data
as $function$
declare
  archived_rows bigint;
  archived_parsed bigint;
  archived_quarantined bigint;
  unarchived_rows bigint;
  unarchived_parsed bigint;
  unarchived_quarantined bigint;
  latest_archive_available_at timestamptz;
begin
  perform market_data.refresh_home_data_status_without_archive();

  with latest_archive_slice as (
    select distinct on (
      provider_code,
      source_dataset,
      scheduled_market,
      asset_type,
      source_symbol,
      requested_start_date,
      requested_end_date
    )
      row_count,
      parsed_row_count,
      quarantined_row_count,
      first_observed_at
    from market_data.historical_archive_objects
    order by
      provider_code,
      source_dataset,
      scheduled_market,
      asset_type,
      source_symbol,
      requested_start_date,
      requested_end_date,
      created_at desc,
      archive_id desc
  )
  select
    coalesce(sum(row_count), 0),
    coalesce(sum(parsed_row_count), 0),
    coalesce(sum(quarantined_row_count), 0),
    max(first_observed_at)
  into
    archived_rows,
    archived_parsed,
    archived_quarantined,
    latest_archive_available_at
  from latest_archive_slice;

  select
    count(*),
    count(*) filter (where landing.parse_status = 'PARSED'),
    count(*) filter (where landing.parse_status = 'QUARANTINED')
  into unarchived_rows, unarchived_parsed, unarchived_quarantined
  from market_data.historical_daily_bar_landing as landing
  where not exists (
    select 1
    from market_data.historical_archive_objects as archive
    where archive.provider_code = 'FINMIND'
      and archive.source_dataset = landing.source_dataset
      and archive.source_payload_hash = landing.source_payload_hash
  );

  update public.home_data_status
  set
    latest_available_at = greatest(
      home_data_status.latest_available_at,
      latest_archive_available_at
    ),
    historical_landing_count = unarchived_rows + archived_rows,
    historical_parsed_count = unarchived_parsed + archived_parsed,
    historical_quarantined_count =
      unarchived_quarantined + archived_quarantined,
    reason_codes = case
      when unarchived_rows + archived_rows > 0
        and historical_production_eligible_count = 0
        and not (
          'HISTORICAL_POINT_IN_TIME_UNVERIFIED' = any(reason_codes)
        )
      then array_append(
        reason_codes,
        'HISTORICAL_POINT_IN_TIME_UNVERIFIED'
      )
      else reason_codes
    end,
    updated_at = statement_timestamp()
  where status_key = 'latest';

  with latest_run as (
    select *
    from market_data.prediction_runs
    where horizon = 5
    order by decision_at desc, prediction_run_id desc
    limit 1
  ),
  output_summary as (
    select
      count(prediction.stock_prediction_id)::integer as stock_count,
      (
        select count(*)::integer
        from market_data.market_predictions
        where prediction_run_id = latest_run.prediction_run_id
          and market = latest_run.market_scope
      ) as market_count,
      (
        select count(distinct excluded.security_id)::integer
        from (
          select hard_prediction.security_id
          from market_data.stock_predictions as hard_prediction
          where hard_prediction.prediction_run_id =
            latest_run.prediction_run_id
            and hard_prediction.decision_policy_status = 'HARD_FAIL'
          union
          select audit.security_id
          from market_data.data_quality_audits as audit
          where audit.prediction_run_id = latest_run.prediction_run_id
            and audit.hard_fail
        ) as excluded
      ) as hard_fail_count
    from latest_run
    left join market_data.stock_predictions as prediction
      on prediction.prediction_run_id = latest_run.prediction_run_id
    group by latest_run.prediction_run_id, latest_run.market_scope
  ),
  contract as (
    select
      latest_run.system_validation_status,
      (
        output_summary.stock_count = (
          latest_run.candidate_count
          + latest_run.watch_count
          + latest_run.no_trade_count
          + latest_run.policy_input_missing_count
          + latest_run.policy_validation_failed_count
          + latest_run.policy_hard_fail_count
        )
        and output_summary.hard_fail_count =
          latest_run.hard_fail_count
        and output_summary.market_count = 1
        and output_summary.stock_count > 0
      ) as complete
    from latest_run
    cross join output_summary
  )
  update public.home_data_status
  set
    model_output_status = case
      when contract.system_validation_status = 'FAIL' then 'FAIL'
      when contract.system_validation_status = 'PASS' and contract.complete
        then 'PASS'
      else 'RESEARCH_ONLY'
    end,
    reason_codes = case
      when contract.system_validation_status = 'PASS'
        and not contract.complete
        then array_append(
          array_remove(reason_codes, 'MODEL_OUTPUT_INCOMPLETE'),
          'MODEL_OUTPUT_INCOMPLETE'
        )
      else array_remove(reason_codes, 'MODEL_OUTPUT_INCOMPLETE')
    end,
    updated_at = statement_timestamp()
  from contract
  where status_key = 'latest';
end
$function$;

revoke all on function market_data.refresh_home_data_status()
from public, anon, authenticated;
grant execute on function market_data.refresh_home_data_status()
to service_role;

select market_data.refresh_home_data_status();

commit;

notify pgrst, 'reload schema';
