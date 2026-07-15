-- v17.3: authenticated administrator console.
--
-- Administrator membership is stored separately from user-editable metadata.
-- The browser may discover its own membership, while all diagnostic data is
-- returned by a SECURITY DEFINER function that repeats the active-admin check.

create table if not exists public.app_admins (
  user_id uuid primary key references auth.users(id) on delete cascade,
  username text not null constraint app_admins_username_format
    check (username ~ '^[A-Za-z0-9_.-]{3,32}$'),
  active boolean not null default true,
  created_at timestamptz not null default clock_timestamp(),
  updated_at timestamptz not null default clock_timestamp()
);

alter table public.app_admins enable row level security;

drop policy if exists app_admins_read_self on public.app_admins;
create policy app_admins_read_self on public.app_admins
  for select to authenticated
  using ((select auth.uid()) is not null and user_id = (select auth.uid()));

revoke all on table public.app_admins from public, anon, authenticated;
grant select on table public.app_admins to authenticated;
grant all on table public.app_admins to service_role;

drop trigger if exists app_admins_set_updated_at on public.app_admins;
create trigger app_admins_set_updated_at
before update on public.app_admins
for each row execute function public.set_updated_at();

create or replace function public.twss_is_admin()
returns boolean
language sql
stable
security invoker
set search_path = ''
as $$
  select (select auth.uid()) is not null and exists (
    select 1
    from public.app_admins a
    where a.user_id = (select auth.uid())
      and a.active
  );
$$;

revoke all on function public.twss_is_admin()
  from public, anon, authenticated;
grant execute on function public.twss_is_admin()
  to authenticated, service_role;

create or replace function public.twss_admin_operations_log(p_limit integer default 60)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  v_limit integer := greatest(1, least(coalesce(p_limit, 60), 100));
  v_health jsonb;
  v_missing jsonb;
  v_username text;
begin
  if (select auth.uid()) is null or not (select public.twss_is_admin()) then
    raise exception using errcode = '42501', message = 'admin_required';
  end if;

  select a.username into v_username
  from public.app_admins a
  where a.user_id = (select auth.uid()) and a.active
  limit 1;

  v_health := public.twss_public_data_health();
  v_missing := public.twss_public_missing_data(v_limit);

  return pg_catalog.jsonb_build_object(
    'version', '17.3',
    'generatedAt', clock_timestamp(),
    'admin', pg_catalog.jsonb_build_object('username', v_username),
    'summary', pg_catalog.jsonb_build_object(
      'pendingRepairs', (select count(*) from public.stock_analysis_cache where needs_repair),
      'analysisErrors', (select count(*) from public.stock_analysis_cache where status = 'error'),
      'failedJobs', (select count(*) from public.stock_sync_state where status = 'error'),
      'runningJobs', (select count(*) from public.stock_sync_state where status = 'running'),
      'readyAnalyses', (select count(*) from public.stock_analysis_cache where status = 'ready'),
      'latestDataDate', (
        select cycle_date
        from public.stock_sync_state
        where job_key = 'universe'
        limit 1
      )
    ),
    'health', v_health,
    'missingData', v_missing,
    'jobs', coalesce((
      select pg_catalog.jsonb_agg(
        pg_catalog.jsonb_strip_nulls(pg_catalog.jsonb_build_object(
          'jobKey', s.job_key,
          'group', s.group_name,
          'status', s.status,
          'cycleDate', s.cycle_date,
          'cursor', s.cursor_offset,
          'processed', s.processed_count,
          'total', s.total_items,
          'progress', case when s.total_items > 0
            then round(s.processed_count::numeric * 100 / s.total_items, 1) else 0 end,
          'cycleNumber', s.cycle_number,
          'lastSymbol', s.last_symbol,
          'lastErrorCode', case
            when s.last_error is null then null
            when lower(s.last_error) ~ '(429|rate.?limit|quota)' then 'rate_limited'
            when lower(s.last_error) ~ '(timeout|abort)' then 'upstream_timeout'
            when lower(s.last_error) ~ '(502|503|504|http 5)' then 'upstream_5xx'
            else 'sync_error'
          end,
          'lastErrorPreview', case when s.last_error is null then null else
            pg_catalog.regexp_replace(
              pg_catalog.left(s.last_error, 400),
              '(apikey|authorization|bearer|token)([[:space:]]*[:=]?[[:space:]]*)[^,;[:space:]]+',
              '\1\2[redacted]',
              'gi'
            )
          end,
          'startedAt', s.started_at,
          'lastSuccessAt', s.last_success_at,
          'nextRunAt', s.next_run_at,
          'leaseUntil', s.lease_until,
          'updatedAt', s.updated_at,
          'details', pg_catalog.jsonb_strip_nulls(pg_catalog.jsonb_build_object(
            'counts', s.details -> 'counts',
            'eligibleCounts', s.details -> 'eligibleCounts',
            'completedCycleKey', s.details ->> 'completedCycleKey',
            'batchSize', s.details -> 'batchSize',
            'remaining', s.details -> 'remaining',
            'waitingRetry', s.details -> 'waitingRetry',
            'revenueBackfillPending', s.details -> 'revenueBackfillPending',
            'finmindBudget', coalesce(s.details -> 'finmindBudget', s.details -> 'finmindQuota'),
            'version', s.details ->> 'version'
          ))
        ))
        order by case s.job_key
          when 'universe' then 0
          when 'deep_listed' then 1
          when 'deep_otc' then 2
          when 'deep_etf' then 3
          else 9
        end, s.job_key
      )
      from public.stock_sync_state s
    ), '[]'::jsonb),
    'repairQueue', pg_catalog.jsonb_build_object(
      'pending', (select count(*) from public.stock_analysis_cache where needs_repair),
      'errors', (select count(*) from public.stock_analysis_cache where status = 'error'),
      'waitingBackoff', (select count(*) from public.stock_analysis_cache where next_retry_at > clock_timestamp()),
      'byGroup', coalesce((
        select pg_catalog.jsonb_object_agg(q.group_name, q.payload)
        from (
          select a.group_name, pg_catalog.jsonb_build_object(
            'pending', count(*) filter (where a.needs_repair),
            'errors', count(*) filter (where a.status = 'error'),
            'waitingBackoff', count(*) filter (where a.next_retry_at > clock_timestamp())
          ) payload
          from public.stock_analysis_cache a
          group by a.group_name
        ) q
      ), '{}'::jsonb),
      'items', coalesce((
        select pg_catalog.jsonb_agg(x.payload order by x.event_at desc, x.symbol)
        from (
          select
            a.symbol,
            coalesce(a.last_attempt_at, a.updated_at) event_at,
            pg_catalog.jsonb_strip_nulls(pg_catalog.jsonb_build_object(
              'symbol', a.symbol,
              'name', a.stock ->> 'name',
              'group', a.group_name,
              'dataDate', a.data_date,
              'status', a.status,
              'errorKind', a.error_kind,
              'attemptCount', a.attempt_count,
              'nextRetryAt', a.next_retry_at,
              'lastAttemptAt', a.last_attempt_at,
              'needsRepair', a.needs_repair,
              'repairReasons', a.repair_reasons,
              'updatedAt', a.updated_at
            )) payload
          from public.stock_analysis_cache a
          where a.needs_repair or a.status = 'error'
          order by coalesce(a.last_attempt_at, a.updated_at) desc nulls last, a.symbol
          limit v_limit
        ) x
      ), '[]'::jsonb)
    ),
    'apiQuota', pg_catalog.jsonb_build_object(
      'usedLast60Minutes', coalesce((
        select sum(q.units)
        from public.twss_api_quota_reservations q
        where q.reserved_at > clock_timestamp() - interval '60 minutes'
      ), 0),
      'reservationCount', (
        select count(*)
        from public.twss_api_quota_reservations q
        where q.reserved_at > clock_timestamp() - interval '60 minutes'
      ),
      'nextReleaseAt', (
        select min(q.reserved_at) + interval '60 minutes'
        from public.twss_api_quota_reservations q
        where q.reserved_at > clock_timestamp() - interval '60 minutes'
      ),
      'byJob', coalesce((
        select pg_catalog.jsonb_object_agg(x.job, x.units)
        from (
          select coalesce(q.metadata ->> 'job', 'unknown') job, sum(q.units) units
          from public.twss_api_quota_reservations q
          where q.reserved_at > clock_timestamp() - interval '60 minutes'
          group by coalesce(q.metadata ->> 'job', 'unknown')
        ) x
      ), '{}'::jsonb)
    ),
    'rankingCycles', coalesce((
      select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'scoreDate', c.score_date,
        'modelVersion', c.model_version,
        'group', c.group_name,
        'status', c.status,
        'expected', c.expected_count,
        'scored', c.scored_count,
        'official', c.official_count,
        'startedAt', c.started_at,
        'finalizedAt', c.finalized_at,
        'updatedAt', c.updated_at
      ) order by c.score_date desc, c.group_name)
      from (
        select *
        from public.opportunity_ranking_cycles
        order by score_date desc, updated_at desc
        limit 30
      ) c
    ), '[]'::jsonb),
    'timeline', coalesce((
      select pg_catalog.jsonb_agg(e.payload order by e.event_at desc)
      from (
        select s.updated_at event_at, pg_catalog.jsonb_build_object(
          'at', s.updated_at,
          'type', 'sync_job',
          'key', s.job_key,
          'status', s.status,
          'group', s.group_name
        ) payload
        from public.stock_sync_state s
        union all
        select coalesce(a.last_attempt_at, a.updated_at), pg_catalog.jsonb_build_object(
          'at', coalesce(a.last_attempt_at, a.updated_at),
          'type', case when a.status = 'error' then 'analysis_error' else 'repair_pending' end,
          'key', a.symbol,
          'group', a.group_name,
          'status', a.status,
          'errorKind', a.error_kind,
          'repairReasons', a.repair_reasons
        )
        from public.stock_analysis_cache a
        where a.status = 'error' or a.needs_repair
        union all
        select q.reserved_at, pg_catalog.jsonb_build_object(
          'at', q.reserved_at,
          'type', 'api_quota',
          'key', coalesce(q.metadata ->> 'job', 'unknown'),
          'units', q.units,
          'group', q.metadata ->> 'group'
        )
        from public.twss_api_quota_reservations q
        where q.reserved_at > clock_timestamp() - interval '24 hours'
        union all
        select c.updated_at, pg_catalog.jsonb_build_object(
          'at', c.updated_at,
          'type', 'ranking_cycle',
          'key', c.score_date::text,
          'group', c.group_name,
          'status', c.status,
          'scored', c.scored_count,
          'expected', c.expected_count
        )
        from public.opportunity_ranking_cycles c
        order by 1 desc
        limit v_limit
      ) e
    ), '[]'::jsonb)
  );
end;
$$;

revoke all on function public.twss_admin_operations_log(integer)
  from public, anon, authenticated;
grant execute on function public.twss_admin_operations_log(integer)
  to authenticated, service_role;

-- Keep the protected synchronization logger working after the v17.2.2
-- public-diagnostics revocation. These functions remain unavailable to users.
revoke all on function public.twss_public_data_health()
  from public, anon, authenticated;
grant execute on function public.twss_public_data_health()
  to service_role;

revoke all on function public.twss_public_missing_data(integer)
  from public, anon, authenticated;
grant execute on function public.twss_public_missing_data(integer)
  to service_role;

comment on function public.twss_admin_operations_log(integer) is
  'Intentional SECURITY DEFINER boundary: authenticated callers must also be active members of app_admins.';
