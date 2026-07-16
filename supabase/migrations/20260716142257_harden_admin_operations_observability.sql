-- Harden the narrow v20 global-market writer and extend the existing
-- administrator-only operations payload without exposing queue or quota data
-- to public API roles.

revoke all on function public.twss_v20_persist_global_context(text, jsonb, jsonb, text[])
  from public, anon, authenticated;
grant execute on function public.twss_v20_persist_global_context(text, jsonb, jsonb, text[])
  to service_role;

comment on function public.twss_v20_persist_global_context(text, jsonb, jsonb, text[]) is
  'Service-role-only writer for the latest v20 global market cache. The existing internal-token validation remains defense in depth.';

do $$
begin
  if pg_catalog.to_regprocedure('public.twss_admin_operations_log_v206(integer)') is null then
    alter function public.twss_admin_operations_log(integer)
      rename to twss_admin_operations_log_v206;
  end if;
end;
$$;

revoke all on function public.twss_admin_operations_log_v206(integer)
  from public, anon, authenticated;
grant execute on function public.twss_admin_operations_log_v206(integer)
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
  v_now timestamptz := pg_catalog.clock_timestamp();
  v_payload jsonb;
  v_quota_pools jsonb := '{}'::jsonb;
  v_quota_combined jsonb := '{}'::jsonb;
  v_api_quota jsonb := '{}'::jsonb;
  v_queue_health jsonb := '{}'::jsonb;
  v_worker_throughput jsonb := '{}'::jsonb;
  v_calibration jsonb := '{}'::jsonb;
  v_model_version text := '20.0';
begin
  if (select auth.uid()) is null or not (select public.twss_is_admin()) then
    raise exception using errcode = '42501', message = 'admin_required';
  end if;

  v_payload := public.twss_admin_operations_log_v206(v_limit);

  with configured_pools(source, pool_key, unit_limit) as (
    values
      ('finmind_primary'::text, 'primary'::text, 600::integer),
      ('finmind_secondary'::text, 'secondary'::text, 600::integer)
  ), pool_usage as (
    select
      p.source,
      p.pool_key,
      p.unit_limit,
      coalesce(pg_catalog.sum(q.units), 0)::integer as used_units,
      pg_catalog.count(q.id)::integer as reservation_count,
      pg_catalog.min(q.reserved_at) + interval '60 minutes' as next_release_at
    from configured_pools p
    left join public.twss_api_quota_reservations q
      on q.source = p.source
     and q.reserved_at > v_now - interval '60 minutes'
    group by p.source, p.pool_key, p.unit_limit
  )
  select
    pg_catalog.jsonb_object_agg(
      u.pool_key,
      pg_catalog.jsonb_build_object(
        'source', u.source,
        'usedLast60Minutes', u.used_units,
        'limit', u.unit_limit,
        'remaining', greatest(u.unit_limit - u.used_units, 0),
        'reservationCount', u.reservation_count,
        'nextReleaseAt', u.next_release_at
      )
      order by u.pool_key
    ),
    pg_catalog.jsonb_build_object(
      'usedLast60Minutes', pg_catalog.sum(u.used_units)::integer,
      'limit', pg_catalog.sum(u.unit_limit)::integer,
      'remaining', greatest(
        pg_catalog.sum(u.unit_limit) - pg_catalog.sum(u.used_units),
        0
      )::integer,
      'reservationCount', pg_catalog.sum(u.reservation_count)::integer,
      'nextReleaseAt', pg_catalog.min(u.next_release_at)
    )
  into v_quota_pools, v_quota_combined
  from pool_usage u;

  v_api_quota := coalesce(v_payload -> 'apiQuota', '{}'::jsonb)
    || pg_catalog.jsonb_build_object(
      -- Keep the original flat fields for old admin clients.
      'usedLast60Minutes', coalesce((v_quota_combined ->> 'usedLast60Minutes')::integer, 0),
      'reservationCount', coalesce((v_quota_combined ->> 'reservationCount')::integer, 0),
      'nextReleaseAt', v_quota_combined -> 'nextReleaseAt',
      'pools', coalesce(v_quota_pools, '{}'::jsonb),
      'combined', coalesce(v_quota_combined, '{}'::jsonb)
    );

  select pg_catalog.jsonb_build_object(
    'activeLeases', pg_catalog.count(*) filter (
      where q.status = 'running' and q.lease_until >= v_now
    ),
    'expiredLeases', pg_catalog.count(*) filter (
      where q.status = 'running' and q.lease_until < v_now
    ),
    'staleLeases', pg_catalog.count(*) filter (
      where q.status = 'running'
        and q.lease_until >= v_now
        and coalesce(q.lease_renewed_at, q.updated_at) < v_now - interval '2 minutes'
    ),
    'claimCount', coalesce(pg_catalog.sum(q.claim_count), 0),
    'leaseTimeoutCount', coalesce(pg_catalog.sum(q.lease_timeout_count), 0),
    'latestHeartbeatAt', pg_catalog.max(coalesce(q.lease_renewed_at, q.updated_at))
      filter (where q.status = 'running'),
    'oldestHeartbeatAt', pg_catalog.min(coalesce(q.lease_renewed_at, q.updated_at))
      filter (where q.status = 'running'),
    'lastCompletedAt', pg_catalog.max(q.completed_at),
    'completedLast15Minutes', pg_catalog.count(*) filter (
      where q.completed_at > v_now - interval '15 minutes'
    ),
    'completedLast60Minutes', pg_catalog.count(*) filter (
      where q.completed_at > v_now - interval '60 minutes'
    ),
    'perMinuteLast60', pg_catalog.round(
      pg_catalog.count(*) filter (
        where q.completed_at > v_now - interval '60 minutes'
      )::numeric / 60,
      2
    )
  )
  into v_queue_health
  from public.stock_enrichment_queue q;

  v_worker_throughput := pg_catalog.jsonb_build_object(
    'completedLast15Minutes', coalesce((v_queue_health ->> 'completedLast15Minutes')::integer, 0),
    'completedLast60Minutes', coalesce((v_queue_health ->> 'completedLast60Minutes')::integer, 0),
    'perMinuteLast60', coalesce((v_queue_health ->> 'perMinuteLast60')::numeric, 0),
    'lastCompletedAt', v_queue_health -> 'lastCompletedAt',
    'latestHeartbeatAt', v_queue_health -> 'latestHeartbeatAt'
  );

  select coalesce(pg_catalog.max(s.model_version), '20.0')
  into v_model_version
  from public.v20_model_signals s;

  with horizons(model_key, horizon_days) as (
    values
      ('short'::text, 2), ('short'::text, 3), ('short'::text, 5), ('short'::text, 10),
      ('medium'::text, 20), ('medium'::text, 40), ('medium'::text, 60)
  ), outcome_counts as (
    select o.model_key, o.horizon_days, pg_catalog.count(*)::integer as outcome_count
    from public.v20_signal_outcomes o
    where o.model_version = v_model_version
    group by o.model_key, o.horizon_days
  ), bucket_stats as (
    select
      b.model_key,
      b.horizon_days,
      pg_catalog.max(b.sample_count) filter (where b.strategy_key <> 'all')::integer
        as max_exact_samples,
      pg_catalog.max(b.sample_count) filter (where b.strategy_key = 'all')::integer
        as max_fallback_samples,
      coalesce(pg_catalog.bool_or(
        (b.strategy_key <> 'all' and b.sample_count >= 60)
        or (b.strategy_key = 'all' and b.sample_count >= 150)
      ), false) as ready,
      pg_catalog.max(b.calibration_date) as calibration_date
    from public.v20_calibration_buckets b
    where b.model_version = v_model_version
    group by b.model_key, b.horizon_days
  ), readiness as (
    select
      h.model_key,
      h.horizon_days,
      coalesce(o.outcome_count, 0) as outcome_count,
      coalesce(b.max_exact_samples, 0) as max_exact_samples,
      coalesce(b.max_fallback_samples, 0) as max_fallback_samples,
      coalesce(b.ready, false) as ready,
      b.calibration_date
    from horizons h
    left join outcome_counts o using (model_key, horizon_days)
    left join bucket_stats b using (model_key, horizon_days)
  ), by_model as (
    select
      r.model_key,
      pg_catalog.jsonb_build_object(
        'ready', pg_catalog.bool_and(r.ready),
        'readyHorizons', pg_catalog.count(*) filter (where r.ready),
        'requiredHorizons', pg_catalog.count(*),
        'outcomes', pg_catalog.sum(r.outcome_count),
        'byHorizon', pg_catalog.jsonb_object_agg(
          r.horizon_days::text,
          pg_catalog.jsonb_build_object(
            'outcomes', r.outcome_count,
            'maxExactSamples', r.max_exact_samples,
            'maxFallbackSamples', r.max_fallback_samples,
            'ready', r.ready,
            'calibrationDate', r.calibration_date
          )
          order by r.horizon_days
        )
      ) as payload
    from readiness r
    group by r.model_key
  )
  select pg_catalog.jsonb_build_object(
    'modelVersion', v_model_version,
    'ready', coalesce((select pg_catalog.bool_and(r.ready) from readiness r), false),
    'outcomeCount', coalesce((select pg_catalog.sum(r.outcome_count) from readiness r), 0),
    'calibrationSampleCount', coalesce((
      select pg_catalog.sum(b.sample_count)
      from public.v20_calibration_buckets b
      where b.model_version = v_model_version and b.strategy_key = 'all'
    ), 0),
    'usableBucketCount', coalesce((
      select pg_catalog.count(*)
      from public.v20_calibration_buckets b
      where b.model_version = v_model_version
        and (
          (b.strategy_key <> 'all' and b.sample_count >= 60)
          or (b.strategy_key = 'all' and b.sample_count >= 150)
        )
    ), 0),
    'latestEvaluatedAt', (
      select pg_catalog.max(o.evaluated_at)
      from public.v20_signal_outcomes o
      where o.model_version = v_model_version
    ),
    'latestCalibrationDate', (
      select pg_catalog.max(b.calibration_date)
      from public.v20_calibration_buckets b
      where b.model_version = v_model_version
    ),
    'thresholds', pg_catalog.jsonb_build_object('exact', 60, 'fallback', 150),
    'byModel', coalesce((
      select pg_catalog.jsonb_object_agg(m.model_key, m.payload order by m.model_key)
      from by_model m
    ), '{}'::jsonb)
  )
  into v_calibration;

  return v_payload || pg_catalog.jsonb_build_object(
    'apiQuota', v_api_quota,
    'enrichmentQueue', coalesce(v_payload -> 'enrichmentQueue', '{}'::jsonb)
      || coalesce(v_queue_health, '{}'::jsonb),
    'workerThroughput', coalesce(v_worker_throughput, '{}'::jsonb),
    'calibrationReadiness', coalesce(v_calibration, '{}'::jsonb),
    'summary', coalesce(v_payload -> 'summary', '{}'::jsonb)
      || pg_catalog.jsonb_build_object(
        'expiredEnrichmentLeases', coalesce((v_queue_health ->> 'expiredLeases')::integer, 0),
        'staleEnrichmentLeases', coalesce((v_queue_health ->> 'staleLeases')::integer, 0),
        'calibrationReady', coalesce((v_calibration ->> 'ready')::boolean, false)
      )
  );
end;
$$;

revoke all on function public.twss_admin_operations_log(integer)
  from public, anon, authenticated;
grant execute on function public.twss_admin_operations_log(integer)
  to authenticated, service_role;

comment on function public.twss_admin_operations_log(integer) is
  'Intentional SECURITY DEFINER boundary for active administrators only; reports independent FinMind pools, queue leases, throughput, and calibration readiness.';
