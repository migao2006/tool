-- v20.0.0: distinguish actionable repair failures from known source limits.
--
-- A short history returned successfully for a newly listed instrument is a
-- completed lookup, even when it is not yet long enough for every indicator.
-- Likewise, diagnostics explicitly marked retryable=false must not consume the
-- FinMind repair budget forever.

update public.stock_analysis_cache a
set
  needs_repair = false,
  repair_reasons = '{}'::text[],
  next_retry_at = null,
  updated_at = clock_timestamp()
where a.status = 'ready'
  and a.needs_repair
  and (
    (
      a.symbol in ('7610', '6535', '7751', '6945', '4590', '8084', '3485', '7828', '6907')
      and a.repair_reasons = array['margin']::text[]
      and a.analysis #>> '{sourceDiagnostics,margin,status}' = 'empty-no-history'
      and coalesce(a.analysis #>> '{sourceDiagnostics,margin,retryable}', 'false') = 'false'
    )
    or (
      a.symbol = '9105'
      and a.repair_reasons <@ array['income', 'balance', 'cashflow', 'financial-source-coverage']::text[]
      and coalesce(a.analysis #>> '{sourceDiagnostics,income,retryable}', 'false') = 'false'
      and coalesce(a.analysis #>> '{sourceDiagnostics,balance,retryable}', 'false') = 'false'
      and coalesce(a.analysis #>> '{sourceDiagnostics,cashflow,retryable}', 'false') = 'false'
    )
  );

with history as (
  select
    count(*)::integer as row_count,
    max(h.trade_date) as period
  from public.stock_price_history h
  where h.symbol = '00407A'
)
update public.stock_sync_state s
set
  status = 'success',
  cycle_date = coalesce(history.period, s.cycle_date),
  cursor_offset = history.row_count,
  total_items = history.row_count,
  processed_count = history.row_count,
  last_symbol = '00407A',
  last_error = null,
  last_success_at = clock_timestamp(),
  next_run_at = null,
  details = coalesce(s.details, '{}'::jsonb) || pg_catalog.jsonb_build_object(
    'symbol', '00407A',
    'historyRows', history.row_count,
    'historyPeriod', history.period,
    'historyComplete', true,
    'reasonCode', 'insufficient_history_new_listing',
    'minimumRows', 60
  ),
  updated_at = clock_timestamp()
from history
where s.job_key = 'history_00407A'
  and s.status = 'error'
  and s.last_error = '上市 00407A 歷史日線不足'
  and history.row_count > 0;

-- Preserve the complete existing aggregation as a private implementation
-- helper, then wrap it with corrected v20 reporting semantics.  This avoids
-- duplicating the large health/missing-data query and keeps its output backward
-- compatible for the existing administrator UI.
do $$
begin
  if pg_catalog.to_regprocedure('public.twss_admin_operations_log_v173(integer)') is null then
    alter function public.twss_admin_operations_log(integer)
      rename to twss_admin_operations_log_v173;
  end if;
end;
$$;

revoke all on function public.twss_admin_operations_log_v173(integer)
  from public, anon, authenticated;
grant execute on function public.twss_admin_operations_log_v173(integer)
  to service_role;

create or replace function public.twss_admin_operations_log(p_limit integer default 60)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  v_limit integer := greatest(1, least(coalesce(p_limit, 60), 100));
  v_payload jsonb;
  v_jobs jsonb;
  v_universe_date date;
  v_ready integer := 0;
  v_current_ready integer := 0;
  v_actionable_missing integer := 0;
  v_missing_total integer := 0;
  v_v20_symbols integer := 0;
begin
  if (select auth.uid()) is null or not (select public.twss_is_admin()) then
    raise exception using errcode = '42501', message = 'admin_required';
  end if;

  v_payload := public.twss_admin_operations_log_v173(v_limit);

  select s.cycle_date
  into v_universe_date
  from public.stock_sync_state s
  where s.job_key = 'universe'
  limit 1;

  select
    count(*) filter (where a.status = 'ready')::integer,
    count(*) filter (where a.status = 'ready' and a.data_date = v_universe_date)::integer
  into v_ready, v_current_ready
  from public.stock_analysis_cache a;

  select count(distinct s.symbol)::integer
  into v_v20_symbols
  from public.v20_model_signals s
  where s.model_version = '20.0'
    and s.signal_date = (
      select max(latest.signal_date)
      from public.v20_model_signals latest
      where latest.model_version = '20.0'
    );

  select
    coalesce(sum((item.value ->> 'count')::integer)
      filter (where item.value ->> 'classification' in ('scheduled_repair', 'upstream_error')), 0)::integer,
    coalesce(sum((item.value ->> 'count')::integer), 0)::integer
  into v_actionable_missing, v_missing_total
  from pg_catalog.jsonb_array_elements(
    coalesce(v_payload #> '{missingData,summary}', '[]'::jsonb)
  ) item(value);

  select coalesce(pg_catalog.jsonb_agg(
    case
      when s.group_name = 'history' then
        item.value || pg_catalog.jsonb_build_object(
          'status', s.status,
          'cycleDate', coalesce(s.details ->> 'historyPeriod', s.cycle_date::text),
          'cursor', case
            when coalesce(s.details ->> 'historyRows', '') ~ '^[0-9]+$'
              then (s.details ->> 'historyRows')::integer
            else s.cursor_offset
          end,
          'processed', case
            when coalesce(s.details ->> 'historyRows', '') ~ '^[0-9]+$'
              then (s.details ->> 'historyRows')::integer
            else s.processed_count
          end,
          'total', case
            when coalesce(s.details ->> 'historyRows', '') ~ '^[0-9]+$'
              then (s.details ->> 'historyRows')::integer
            else s.total_items
          end,
          'progress', case
            when s.details ->> 'historyComplete' = 'true' then 100
            when s.total_items > 0 then round(s.processed_count::numeric * 100 / s.total_items, 1)
            else 0
          end,
          'lastErrorCode', case when s.status = 'error' then item.value -> 'lastErrorCode' else null end,
          'lastErrorPreview', case when s.status = 'error' then item.value -> 'lastErrorPreview' else null end,
          'details', coalesce(item.value -> 'details', '{}'::jsonb) || pg_catalog.jsonb_strip_nulls(
            pg_catalog.jsonb_build_object(
              'historyRows', s.details -> 'historyRows',
              'historyPeriod', s.details ->> 'historyPeriod',
              'historyComplete', s.details -> 'historyComplete',
              'reasonCode', s.details ->> 'reasonCode',
              'minimumRows', s.details -> 'minimumRows'
            )
          )
        )
      else item.value
    end
    order by item.ordinality
  ), '[]'::jsonb)
  into v_jobs
  from pg_catalog.jsonb_array_elements(coalesce(v_payload -> 'jobs', '[]'::jsonb))
    with ordinality item(value, ordinality)
  left join public.stock_sync_state s
    on s.job_key = item.value ->> 'jobKey';

  return v_payload
    || pg_catalog.jsonb_build_object(
      'version', '20.0.0',
      'jobs', v_jobs,
      'summary', coalesce(v_payload -> 'summary', '{}'::jsonb)
        || pg_catalog.jsonb_build_object(
          'pendingRepairs', (select count(*) from public.stock_analysis_cache where needs_repair),
          'analysisErrors', (select count(*) from public.stock_analysis_cache where status = 'error'),
          'failedJobs', (
            select count(*) from public.stock_sync_state
            where status = 'error' and group_name is distinct from 'history'
          ),
          'historyLookupIssues', (
            select count(*) from public.stock_sync_state
            where status = 'error' and group_name = 'history'
          ),
          'runningJobs', (select count(*) from public.stock_sync_state where status = 'running'),
          'readyAnalyses', v_ready,
          'currentReadyAnalyses', v_current_ready,
          'retainedReadyAnalyses', greatest(v_ready - v_current_ready, 0),
          'v20ModelSymbols', v_v20_symbols,
          'actionableMissing', v_actionable_missing,
          'informationalMissing', greatest(v_missing_total - v_actionable_missing, 0),
          'latestDataDate', v_universe_date
        )
    );
end;
$$;

revoke all on function public.twss_admin_operations_log(integer)
  from public, anon, authenticated;
grant execute on function public.twss_admin_operations_log(integer)
  to authenticated, service_role;

comment on function public.twss_admin_operations_log(integer) is
  'Intentional SECURITY DEFINER boundary: active administrators only; v20 distinguishes actionable failures from source limitations.';
