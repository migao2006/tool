begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

create index if not exists trading_calendar_observations_freshness_idx
on market_data.trading_calendar_observations (
  market,
  trading_date desc,
  available_at desc
)
where calendar_verification_status = 'VERIFIED'
  and market_basis = 'SOURCE_ASSERTED'
  and usage_scope = 'POINT_IN_TIME_CALENDAR'
  and system_status = 'PASS';

drop function if exists market_data.get_prediction_snapshot_rows_v2(
  integer,
  text,
  timestamptz
);

create or replace function market_data.get_prediction_snapshot_rows_v2(
  p_horizon integer,
  p_market_scope text,
  p_observed_at timestamptz default now()
)
returns jsonb
language sql
stable
security invoker
set search_path = pg_catalog, market_data
as $function$
  with base_snapshot as (
    select market_data.get_prediction_snapshot_rows(
      p_horizon,
      p_market_scope,
      p_observed_at
    ) as payload
  ),
  verified_calendar as (
    select coalesce(
      jsonb_agg(to_jsonb(observation) order by observation.trading_date),
      '[]'::jsonb
    ) as payload
    from (
      select
        row.market,
        row.trading_date,
        row.is_trading_day,
        row.decision_data_cutoff_at,
        row.calendar_verification_status,
        row.market_basis,
        row.available_at,
        row.usage_scope,
        row.system_status
      from market_data.trading_calendar_observations as row
      where row.market = p_market_scope
        and row.calendar_verification_status = 'VERIFIED'
        and row.market_basis = 'SOURCE_ASSERTED'
        and row.usage_scope = 'POINT_IN_TIME_CALENDAR'
        and row.system_status = 'PASS'
        and row.available_at <= p_observed_at
        and row.trading_date between
          ((p_observed_at at time zone 'Asia/Taipei')::date - 62)
          and (p_observed_at at time zone 'Asia/Taipei')::date
      order by row.trading_date
    ) as observation
  )
  select case
    when base_snapshot.payload is null then null
    else base_snapshot.payload || jsonb_build_object(
      'calendarObservations',
      verified_calendar.payload
    )
  end
  from base_snapshot
  cross join verified_calendar;
$function$;

comment on function market_data.get_prediction_snapshot_rows_v2(
  integer,
  text,
  timestamptz
) is
'One-request prediction snapshot plus 63 calendar days of verified, source-asserted
point-in-time observations. The Edge function validates contiguous coverage and
falls back to a bounded wall-clock policy when verified coverage is unavailable.';

revoke all on function market_data.get_prediction_snapshot_rows_v2(
  integer,
  text,
  timestamptz
) from public, anon, authenticated;

grant execute on function market_data.get_prediction_snapshot_rows_v2(
  integer,
  text,
  timestamptz
) to service_role;

commit;

notify pgrst, 'reload schema';
