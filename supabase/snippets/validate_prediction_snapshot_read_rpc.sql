-- Run with a role that can inspect privileges and execute service-role-only RPCs.
select
  has_function_privilege(
    'service_role',
    'market_data.get_prediction_snapshot_rows(integer,text,timestamp with time zone)',
    'EXECUTE'
  ) as service_role_can_execute,
  has_function_privilege(
    'anon',
    'market_data.get_prediction_snapshot_rows(integer,text,timestamp with time zone)',
    'EXECUTE'
  ) as anon_can_execute,
  has_function_privilege(
    'authenticated',
    'market_data.get_prediction_snapshot_rows(integer,text,timestamp with time zone)',
    'EXECUTE'
  ) as authenticated_can_execute;

with available_market as (
  select run.market_scope
  from market_data.prediction_runs as run
  where run.horizon = 5
    and run.market_scope in ('TWSE', 'TPEX')
  order by run.decision_at desc, run.prediction_run_id desc
  limit 1
), observed as (
  select now() as observed_at
), payload as (
  select
    market_data.get_prediction_snapshot_rows(
      5,
      available_market.market_scope,
      observed.observed_at
    ) as value,
    observed.observed_at
  from available_market
  cross join observed
), history_rows as (
  select
    payload.observed_at,
    history.value as history
  from payload
  cross join lateral jsonb_array_elements(
    coalesce(payload.value -> 'currentSecurityHistory', '[]'::jsonb)
  ) as history(value)
)
select
  jsonb_typeof(value) = 'object' as payload_is_object,
  jsonb_typeof(value -> 'run') = 'object' as run_is_object,
  jsonb_typeof(value -> 'predictions') = 'array' as predictions_are_array,
  jsonb_typeof(value -> 'gates') = 'array' as gates_are_array,
  (value -> 'run' ->> 'decision_at')::timestamptz <= observed_at
    and (value -> 'run' ->> 'latest_available_at')::timestamptz <= observed_at
    and (value -> 'run' ->> 'created_at')::timestamptz <= observed_at
    as run_is_point_in_time_valid,
  jsonb_array_length(value -> 'predictions') = (
    (value -> 'run' ->> 'candidate_count')::integer
    + (value -> 'run' ->> 'watch_count')::integer
    + (value -> 'run' ->> 'no_trade_count')::integer
  ) as prediction_manifest_count_matches,
  value ->> 'validationLinkStatus' in ('LINKED', 'MISSING', 'AMBIGUOUS')
    as validation_link_status_is_valid,
  (
    select count(*) = count(distinct (history ->> 'security_id'))
    from history_rows
  ) as current_history_has_one_row_per_security,
  not exists (
    select 1
    from history_rows
    where (history ->> 'effective_from')::date
        > (observed_at at time zone 'Asia/Taipei')::date
      or (
        history ->> 'effective_to' is not null
        and (observed_at at time zone 'Asia/Taipei')::date
          >= (history ->> 'effective_to')::date
      )
      or (history ->> 'available_at')::timestamptz > observed_at
  ) as current_history_is_point_in_time_valid
from payload;
