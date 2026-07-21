begin;

set local search_path = pg_catalog, public, extensions;
set local lock_timeout = '5s';
set local statement_timeout = '30s';

-- FinMind's free tier rejects TaiwanStockPriceAdj. Preserve those tasks for a
-- future credential upgrade, but make their deferred state explicit and keep
-- them out of the runnable queue.
update market_data.historical_backfill_tasks as queued_task
set
    status = 'RETRY',
    next_attempt_at = 'infinity'::timestamptz,
    lease_token = null,
    claimed_by = null,
    lease_expires_at = null,
    completed_at = null,
    last_error_code = 'FINMIND_DATASET_ACCESS_UNAVAILABLE',
    reason_codes = case
        when
            'ADJUSTED_BARS_PROVIDER_ACCESS_UNAVAILABLE'
            = any(queued_task.reason_codes)
            then queued_task.reason_codes
        else array_append(
            queued_task.reason_codes,
            'ADJUSTED_BARS_PROVIDER_ACCESS_UNAVAILABLE'
        )
    end,
    updated_at = now()
where
    queued_task.provider_code = 'FINMIND'
    and queued_task.source_dataset = 'adjusted_bars'
    and queued_task.market = 'TWSE'
    and queued_task.asset_type = 'COMMON_STOCK'
    and (
        queued_task.status in ('PENDING', 'RETRY')
        or (
            queued_task.status = 'LEASED'
            and queued_task.lease_expires_at <= now()
            and queued_task.attempt_count < queued_task.max_attempts
        )
    );

drop function if exists
market_data.claim_historical_supplemental_backfill_task(
    text,
    text,
    uuid,
    integer
);

create function market_data.claim_historical_supplemental_backfill_task(
    p_provider_code text,
    p_worker_id text,
    p_claim_token uuid,
    p_lease_seconds integer default 1800,
    p_allowed_datasets text [] default array[
        'institutional_flows',
        'margin_short'
    ]::text []
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
     or p_lease_seconds not between 60 and 3600
     or p_allowed_datasets is null
     or cardinality(p_allowed_datasets) not between 1 and 3
     or exists (
       select 1
       from unnest(p_allowed_datasets) as allowed(source_dataset)
       where allowed.source_dataset not in (
         'adjusted_bars',
         'institutional_flows',
         'margin_short'
       )
     )
     or cardinality(p_allowed_datasets) <> (
       select count(distinct allowed.source_dataset)
       from unnest(p_allowed_datasets) as allowed(source_dataset)
     ) then
    raise exception using errcode = '22023',
      message = 'provider, worker, token, lease and allowed datasets are required';
  end if;

  -- Any excluded adjusted-price task remains auditable and resumable without
  -- consuming another request or attempt.
  if not ('adjusted_bars' = any(p_allowed_datasets)) then
    update market_data.historical_backfill_tasks as deferred
    set status = 'RETRY',
        next_attempt_at = 'infinity'::timestamptz,
        lease_token = null,
        claimed_by = null,
        lease_expires_at = null,
        completed_at = null,
        last_error_code = 'FINMIND_DATASET_ACCESS_UNAVAILABLE',
        reason_codes = case
          when 'ADJUSTED_BARS_PROVIDER_ACCESS_UNAVAILABLE'
            = any(deferred.reason_codes) then deferred.reason_codes
          else array_append(
            deferred.reason_codes,
            'ADJUSTED_BARS_PROVIDER_ACCESS_UNAVAILABLE'
          )
        end,
        updated_at = now()
    where deferred.provider_code = p_provider_code
      and deferred.source_dataset = 'adjusted_bars'
      and deferred.market = 'TWSE'
      and deferred.asset_type = 'COMMON_STOCK'
      and (
        deferred.status in ('PENDING', 'RETRY')
        or (
          deferred.status = 'LEASED'
          and deferred.lease_expires_at <= now()
          and deferred.attempt_count < deferred.max_attempts
        )
      )
      and not (
        deferred.status = 'RETRY'
        and deferred.next_attempt_at = 'infinity'::timestamptz
        and deferred.lease_token is null
        and deferred.claimed_by is null
        and deferred.lease_expires_at is null
        and deferred.completed_at is null
        and deferred.last_error_code = 'FINMIND_DATASET_ACCESS_UNAVAILABLE'
        and 'ADJUSTED_BARS_PROVIDER_ACCESS_UNAVAILABLE'
          = any(deferred.reason_codes)
      );
  end if;

  -- Explicitly including a previously deferred dataset reactivates it. This is
  -- the paid-tier re-enable path and does not rewrite successful archives.
  update market_data.historical_backfill_tasks as enabled
  set status = 'PENDING',
      attempt_count = 0,
      next_attempt_at = now(),
      lease_token = null,
      claimed_by = null,
      lease_expires_at = null,
      completed_at = null,
      last_result_code = 'PROVIDER_ACCESS_RESTORED',
      last_error_code = null,
      reason_codes = array_remove(
        enabled.reason_codes,
        'ADJUSTED_BARS_PROVIDER_ACCESS_UNAVAILABLE'
      ),
      updated_at = now()
  where enabled.provider_code = p_provider_code
    and enabled.source_dataset = any(p_allowed_datasets)
    and enabled.status in ('RETRY', 'EXHAUSTED')
    and enabled.last_error_code = 'FINMIND_DATASET_ACCESS_UNAVAILABLE';

  update market_data.historical_backfill_tasks as expired
  set status = 'EXHAUSTED',
      lease_token = null,
      claimed_by = null,
      lease_expires_at = null,
      completed_at = now(),
      last_error_code = 'LEASE_EXPIRED_AT_MAX_ATTEMPTS',
      updated_at = now()
  where expired.provider_code = p_provider_code
    and expired.source_dataset = any(p_allowed_datasets)
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
      and queued.source_dataset = any(p_allowed_datasets)
      and queued.market = 'TWSE'
      and queued.asset_type = 'COMMON_STOCK'
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
    order by array_position(p_allowed_datasets, queued.source_dataset)
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
        (
          queued.status in ('PENDING', 'RETRY')
          and queued.next_attempt_at <= now()
        )
        or (
          queued.status = 'LEASED'
          and queued.lease_expires_at <= now()
        )
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

comment on function market_data.claim_historical_supplemental_backfill_task(
    text,
    text,
    uuid,
    integer,
    text []
) is
'Claims only credential-allowed datasets; defaults are free-tier.';

revoke all on function
market_data.claim_historical_supplemental_backfill_task(
    text,
    text,
    uuid,
    integer,
    text []
) from public, anon, authenticated;
grant execute on function
market_data.claim_historical_supplemental_backfill_task(
    text,
    text,
    uuid,
    integer,
    text []
) to service_role;

notify pgrst, 'reload schema';

commit;
