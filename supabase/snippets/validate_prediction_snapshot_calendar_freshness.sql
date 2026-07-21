-- Run as a privileged migration operator after applying the calendar freshness RPC.
select
  to_regprocedure(
    'market_data.get_prediction_snapshot_rows_v2(integer,text,timestamptz)'
  ) is not null as function_exists,
  has_function_privilege(
    'service_role',
    'market_data.get_prediction_snapshot_rows_v2(integer,text,timestamptz)',
    'EXECUTE'
  ) as service_role_can_execute,
  has_function_privilege(
    'anon',
    'market_data.get_prediction_snapshot_rows_v2(integer,text,timestamptz)',
    'EXECUTE'
  ) as anon_can_execute,
  has_function_privilege(
    'authenticated',
    'market_data.get_prediction_snapshot_rows_v2(integer,text,timestamptz)',
    'EXECUTE'
  ) as authenticated_can_execute;

select
  not procedure.prosecdef as security_invoker,
  procedure.provolatile = 's' as stable_function,
  procedure.proconfig @> array['search_path=pg_catalog, market_data'] as fixed_search_path
from pg_proc as procedure
join pg_namespace as namespace
  on namespace.oid = procedure.pronamespace
where namespace.nspname = 'market_data'
  and procedure.proname = 'get_prediction_snapshot_rows_v2';

select
  pg_get_functiondef(
    'market_data.get_prediction_snapshot_rows_v2(integer,text,timestamptz)'::regprocedure
  ) like '%trading_calendar_observations%' as verified_calendar_is_embedded,
  pg_get_functiondef(
    'market_data.get_prediction_snapshot_rows_v2(integer,text,timestamptz)'::regprocedure
  ) like '%calendar_verification_status = ''VERIFIED''%' as verified_rows_only,
  pg_get_functiondef(
    'market_data.get_prediction_snapshot_rows_v2(integer,text,timestamptz)'::regprocedure
  ) like '%row.available_at <= p_observed_at%' as calendar_is_point_in_time_valid;
