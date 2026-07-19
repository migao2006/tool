begin;

set local search_path = pg_catalog, public, extensions;
set local lock_timeout = '5s';
set local statement_timeout = '30s';

create or replace function
market_data.claim_historical_supplemental_backfill_task(
    p_provider_code text,
    p_worker_id text,
    p_claim_token uuid,
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
     or p_claim_token is null
     or p_lease_seconds is null
     or p_lease_seconds not between 60 and 3600 then
    raise exception using errcode = '22023',
      message = 'provider, worker, token and valid lease are required';
  end if;

  update market_data.historical_backfill_tasks as expired
  set status = 'EXHAUSTED',
      lease_token = null,
      claimed_by = null,
      lease_expires_at = null,
      completed_at = now(),
      last_error_code = 'LEASE_EXPIRED_AT_MAX_ATTEMPTS',
      updated_at = now()
  where expired.provider_code = p_provider_code
    and expired.source_dataset in (
      'adjusted_bars', 'institutional_flows', 'margin_short'
    )
    and expired.market = 'TWSE'
    and expired.asset_type = 'COMMON_STOCK'
    and expired.status = 'LEASED'
    and expired.lease_expires_at <= now()
    and expired.attempt_count >= expired.max_attempts;

  return query
  with active_dataset as materialized (
    select queued.source_dataset
    from market_data.historical_backfill_tasks as queued
    where queued.provider_code = p_provider_code
      and queued.source_dataset in (
        'adjusted_bars', 'institutional_flows', 'margin_short'
      )
      and queued.market = 'TWSE'
      and queued.asset_type = 'COMMON_STOCK'
      and queued.status in ('PENDING', 'LEASED', 'RETRY')
    order by case queued.source_dataset
      when 'adjusted_bars' then 10
      when 'institutional_flows' then 20
      when 'margin_short' then 30
    end
    limit 1
  ), candidate as materialized (
    select queued.task_id
    from market_data.historical_backfill_tasks as queued
    join active_dataset using (source_dataset)
    where queued.provider_code = p_provider_code
      and queued.market = 'TWSE'
      and queued.asset_type = 'COMMON_STOCK'
      and queued.attempt_count < queued.max_attempts
      and (
        (queued.status in ('PENDING', 'RETRY') and queued.next_attempt_at <= now())
        or (queued.status = 'LEASED' and queued.lease_expires_at <= now())
      )
    order by queued.requested_start_date, queued.source_symbol, queued.task_id
    for update of queued skip locked
    limit 1
  )
  update market_data.historical_backfill_tasks as task
  set status = 'LEASED',
      attempt_count = task.attempt_count + 1,
      lease_token = p_claim_token,
      claimed_by = p_worker_id,
      lease_expires_at = now() + make_interval(secs => p_lease_seconds),
      completed_at = null,
      updated_at = now()
  from candidate
  where task.task_id = candidate.task_id
  returning task.*;
end
$function$;

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
     or p_claim_token is null
     or p_limit is null
     or p_lease_seconds is null
     or p_limit not between 1 and 100
     or p_lease_seconds not between 60 and 3600 then
    raise exception using errcode = '22023',
      message = 'provider, worker, token and valid limits are required';
  end if;

  update market_data.historical_backfill_tasks as expired
  set status = 'EXHAUSTED',
      lease_token = null,
      claimed_by = null,
      lease_expires_at = null,
      completed_at = now(),
      last_error_code = 'LEASE_EXPIRED_AT_MAX_ATTEMPTS',
      updated_at = now()
  where expired.provider_code = p_provider_code
    and expired.source_dataset = 'daily_bars'
    and expired.status = 'LEASED'
    and expired.lease_expires_at <= now()
    and expired.attempt_count >= expired.max_attempts;

  return query
  with active_priority as materialized (
    select min(queued.priority) as priority
    from market_data.historical_backfill_tasks as queued
    where queued.provider_code = p_provider_code
      and queued.source_dataset = 'daily_bars'
      and queued.status in ('PENDING', 'LEASED', 'RETRY')
  ), candidates as materialized (
    select queued.task_id
    from market_data.historical_backfill_tasks as queued
    cross join active_priority
    where queued.provider_code = p_provider_code
      and queued.source_dataset = 'daily_bars'
      and queued.priority = active_priority.priority
      and queued.attempt_count < queued.max_attempts
      and (
        (queued.status in ('PENDING', 'RETRY') and queued.next_attempt_at <= now())
        or (queued.status = 'LEASED' and queued.lease_expires_at <= now())
      )
    order by queued.priority, queued.requested_start_date,
      queued.market, queued.source_symbol, queued.task_id
    for update of queued skip locked
    limit p_limit
  )
  update market_data.historical_backfill_tasks as task
  set status = 'LEASED',
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

comment on function market_data.claim_historical_supplemental_backfill_task(
    text, text, uuid, integer
) is 'Claims adjusted bars before institutional flows and margin/short data.';

revoke all on function market_data.claim_historical_supplemental_backfill_task(
    text, text, uuid, integer
) from public, anon, authenticated;
grant execute on function
market_data.claim_historical_supplemental_backfill_task(
    text, text, uuid, integer
) to service_role;

notify pgrst, 'reload schema';

commit;
