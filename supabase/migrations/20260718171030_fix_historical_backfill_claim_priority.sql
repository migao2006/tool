begin;

create or replace function market_data.claim_historical_backfill_tasks(
  p_provider_code text,
  p_worker_id text,
  p_claim_token uuid,
  p_limit integer default 1,
  p_lease_seconds integer default 1800
)
returns setof market_data.historical_backfill_tasks
language plpgsql
security invoker
set search_path = pg_catalog, market_data
as $function$
begin
  if nullif(btrim(p_provider_code), '') is null
     or nullif(btrim(p_worker_id), '') is null
     or p_claim_token is null then
    raise exception using
      errcode = '22023',
      message = 'provider, worker and claim token are required';
  end if;
  if p_limit is null
     or p_lease_seconds is null
     or p_limit not between 1 and 100
     or p_lease_seconds not between 60 and 3600 then
    raise exception using
      errcode = '22023',
      message = 'claim limit or lease duration is outside allowed bounds';
  end if;

  update market_data.historical_backfill_tasks as expired
  set
    status = 'EXHAUSTED',
    lease_token = null,
    claimed_by = null,
    lease_expires_at = null,
    completed_at = now(),
    last_error_code = 'LEASE_EXPIRED_AT_MAX_ATTEMPTS',
    updated_at = now()
  where expired.status = 'LEASED'
    and expired.lease_expires_at <= now()
    and expired.attempt_count >= expired.max_attempts;

  return query
  with active_priority as materialized (
    select min(queued.priority) as priority
    from market_data.historical_backfill_tasks as queued
    where queued.provider_code = p_provider_code
      and queued.status in ('PENDING', 'LEASED', 'RETRY')
  ), candidates as materialized (
    select queued.task_id
    from market_data.historical_backfill_tasks as queued
    cross join active_priority
    where queued.provider_code = p_provider_code
      and queued.priority = active_priority.priority
      and queued.attempt_count < queued.max_attempts
      and (
        (
          queued.status in ('PENDING', 'RETRY')
          and queued.next_attempt_at <= now()
        )
        or (
          queued.status = 'LEASED'
          and queued.lease_expires_at <= now()
        )
      )
    order by
      queued.priority,
      queued.requested_start_date,
      queued.market,
      queued.source_symbol,
      queued.task_id
    for update of queued skip locked
    limit p_limit
  )
  update market_data.historical_backfill_tasks as task
  set
    status = 'LEASED',
    attempt_count = task.attempt_count + 1,
    lease_token = p_claim_token,
    claimed_by = p_worker_id,
    lease_expires_at = now() + make_interval(secs => p_lease_seconds),
    completed_at = null,
    updated_at = now()
  from candidates
  where task.task_id = candidates.task_id
  returning task.*;
end
$function$;

revoke all on function market_data.claim_historical_backfill_tasks(
  text,
  text,
  uuid,
  integer,
  integer
) from public, anon, authenticated;

grant execute on function market_data.claim_historical_backfill_tasks(
  text,
  text,
  uuid,
  integer,
  integer
) to service_role;

notify pgrst, 'reload schema';

commit;
