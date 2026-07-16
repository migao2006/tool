-- Make enrichment claims observable without treating every lease acquisition as
-- a failed provider attempt.  The queue remains service-only and keeps all
-- existing RPC signatures so an older worker can safely overlap deployment.

alter table public.stock_enrichment_queue
  add column if not exists claim_count integer not null default 0,
  add column if not exists lease_timeout_count integer not null default 0,
  add column if not exists lease_renewed_at timestamptz;

do $$
begin
  if not exists (
    select 1
    from pg_catalog.pg_constraint
    where conname = 'stock_enrichment_queue_claim_count_nonnegative'
      and conrelid = 'public.stock_enrichment_queue'::regclass
  ) then
    alter table public.stock_enrichment_queue
      add constraint stock_enrichment_queue_claim_count_nonnegative
      check (claim_count >= 0);
  end if;

  if not exists (
    select 1
    from pg_catalog.pg_constraint
    where conname = 'stock_enrichment_queue_lease_timeout_count_nonnegative'
      and conrelid = 'public.stock_enrichment_queue'::regclass
  ) then
    alter table public.stock_enrichment_queue
      add constraint stock_enrichment_queue_lease_timeout_count_nonnegative
      check (lease_timeout_count >= 0);
  end if;

  if not exists (
    select 1
    from pg_catalog.pg_constraint
    where conname = 'stock_enrichment_queue_renewal_consistency'
      and conrelid = 'public.stock_enrichment_queue'::regclass
  ) then
    alter table public.stock_enrichment_queue
      add constraint stock_enrichment_queue_renewal_consistency
      check (lease_renewed_at is null or status = 'running');
  end if;
end
$$;

comment on column public.stock_enrichment_queue.claim_count is
  'Number of queue leases acquired. Claims never consume provider failure attempts.';
comment on column public.stock_enrichment_queue.lease_timeout_count is
  'Number of expired running leases reclaimed by another worker.';
comment on column public.stock_enrichment_queue.lease_renewed_at is
  'Last successful claim or heartbeat for the current running lease.';

-- Convert the old counter before changing its meaning.  Previously every
-- claim incremented attempt_count and an intentional release refunded it.
-- Rows without an error marker therefore contain lease activity, not provider
-- failures.  Moving that history prevents actively reclaimed work from
-- starting the new worker with six or seven fictitious failures.
update public.stock_enrichment_queue q
set claim_count = greatest(q.claim_count, q.attempt_count),
    lease_timeout_count = case
      when q.status = 'running' then
        greatest(q.lease_timeout_count, greatest(q.attempt_count - 1, 0))
      else q.lease_timeout_count
    end,
    lease_renewed_at = case
      when q.status = 'running' then
        coalesce(q.lease_renewed_at, q.last_attempt_at, q.updated_at, q.created_at)
      else null
    end,
    attempt_count = 0,
    updated_at = pg_catalog.clock_timestamp()
where q.error_kind is null
  and q.last_error is null
  and (q.attempt_count > 0 or q.status = 'running');

-- Keep the existing signature.  Claims are capped at the new 15-row worker
-- batch, use SKIP LOCKED, and record an expired lease separately from a real
-- upstream failure.
create or replace function public.twss_claim_enrichment_batch(
  p_owner text,
  p_limit integer default 50,
  p_lease_seconds integer default 180,
  p_dataset_keys text[] default null
)
returns setof public.stock_enrichment_queue
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_limit integer := greatest(1, least(coalesce(p_limit, 15), 15));
  v_lease_seconds integer := greatest(60, least(coalesce(p_lease_seconds, 180), 300));
begin
  if nullif(pg_catalog.btrim(coalesce(p_owner, '')), '') is null then
    raise exception 'enrichment_owner_required' using errcode = '22023';
  end if;

  if p_dataset_keys is not null and exists (
    select 1
    from pg_catalog.unnest(p_dataset_keys) as requested(dataset_key)
    where requested.dataset_key not in (
      'lending', 'price', 'institutional', 'margin', 'revenue', 'financial'
    )
  ) then
    raise exception 'invalid_enrichment_dataset' using errcode = '22023';
  end if;

  return query
  with candidates as (
    select
      q.id,
      q.status = 'running' and q.lease_until < pg_catalog.clock_timestamp() as lease_expired
    from public.stock_enrichment_queue q
    where q.attempt_count < q.max_attempts
      and (p_dataset_keys is null or q.dataset_key = any(p_dataset_keys))
      and (
        (
          q.status in ('pending', 'error')
          and (q.next_retry_at is null or q.next_retry_at <= pg_catalog.clock_timestamp())
        )
        or (
          q.status = 'running'
          and q.lease_until < pg_catalog.clock_timestamp()
        )
      )
    order by q.data_date desc,
      q.priority desc,
      coalesce(q.next_retry_at, q.created_at),
      q.id
    limit v_limit
    for update of q skip locked
  )
  update public.stock_enrichment_queue q
  set status = 'running',
      claim_count = q.claim_count + 1,
      lease_timeout_count = q.lease_timeout_count + case when c.lease_expired then 1 else 0 end,
      next_retry_at = null,
      lease_owner = p_owner,
      lease_until = pg_catalog.clock_timestamp()
        + pg_catalog.make_interval(secs => v_lease_seconds),
      lease_renewed_at = pg_catalog.clock_timestamp(),
      last_attempt_at = pg_catalog.clock_timestamp(),
      completed_at = null,
      updated_at = pg_catalog.clock_timestamp()
  from candidates c
  where q.id = c.id
  returning q.*;
end;
$$;

-- Renew only live leases still owned by the caller.  An expired lease cannot
-- be revived, so a stale worker can never take ownership back from a retry.
create or replace function public.twss_renew_enrichment_leases(
  p_ids bigint[],
  p_owner text,
  p_lease_seconds integer default 180
)
returns integer
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_changed integer := 0;
  v_lease_seconds integer := greatest(60, least(coalesce(p_lease_seconds, 180), 300));
begin
  if nullif(pg_catalog.btrim(coalesce(p_owner, '')), '') is null then
    raise exception 'enrichment_owner_required' using errcode = '22023';
  end if;

  update public.stock_enrichment_queue q
  set lease_until = pg_catalog.clock_timestamp()
        + pg_catalog.make_interval(secs => v_lease_seconds),
      lease_renewed_at = pg_catalog.clock_timestamp(),
      updated_at = pg_catalog.clock_timestamp()
  where q.id = any(coalesce(p_ids, '{}'::bigint[]))
    and q.status = 'running'
    and q.lease_owner = p_owner
    and q.lease_until >= pg_catalog.clock_timestamp();

  get diagnostics v_changed = row_count;
  return v_changed;
end;
$$;

-- Successful completion and actual provider failure both end the heartbeat.
-- The signatures remain identical to the previously deployed functions.
create or replace function public.twss_complete_enrichment(
  p_id bigint,
  p_owner text,
  p_source_date date default null,
  p_details jsonb default '{}'::jsonb
)
returns boolean
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_changed integer := 0;
begin
  if p_id is null or nullif(pg_catalog.btrim(coalesce(p_owner, '')), '') is null
    or pg_catalog.jsonb_typeof(coalesce(p_details, '{}'::jsonb)) <> 'object'
  then
    raise exception 'invalid_enrichment_completion' using errcode = '22023';
  end if;

  update public.stock_enrichment_queue q
  set status = 'success',
      source_date = coalesce(p_source_date, q.source_date),
      details = coalesce(q.details, '{}'::jsonb) || coalesce(p_details, '{}'::jsonb),
      error_kind = null,
      last_error = null,
      next_retry_at = null,
      lease_owner = null,
      lease_until = null,
      lease_renewed_at = null,
      completed_at = pg_catalog.clock_timestamp(),
      updated_at = pg_catalog.clock_timestamp()
  where q.id = p_id
    and q.status = 'running'
    and q.lease_owner = p_owner;

  get diagnostics v_changed = row_count;
  return v_changed = 1;
end;
$$;

create or replace function public.twss_fail_enrichment(
  p_id bigint,
  p_owner text,
  p_error_kind text,
  p_last_error text,
  p_retry_after_seconds integer default 300
)
returns text
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_attempt_count integer;
  v_max_attempts integer;
begin
  if p_id is null or nullif(pg_catalog.btrim(coalesce(p_owner, '')), '') is null then
    raise exception 'invalid_enrichment_failure' using errcode = '22023';
  end if;

  update public.stock_enrichment_queue q
  set status = 'error',
      attempt_count = q.attempt_count + 1,
      error_kind = nullif(pg_catalog.left(coalesce(p_error_kind, ''), 120), ''),
      last_error = nullif(pg_catalog.left(coalesce(p_last_error, ''), 2000), ''),
      next_retry_at = case
        when q.attempt_count + 1 < q.max_attempts then
          pg_catalog.clock_timestamp() + pg_catalog.make_interval(
            secs => greatest(30, least(coalesce(p_retry_after_seconds, 300), 21600))
          )
        else null
      end,
      lease_owner = null,
      lease_until = null,
      lease_renewed_at = null,
      completed_at = null,
      updated_at = pg_catalog.clock_timestamp()
  where q.id = p_id
    and q.status = 'running'
    and q.lease_owner = p_owner
  returning q.attempt_count, q.max_attempts
  into v_attempt_count, v_max_attempts;

  if not found then
    return 'not_owned';
  end if;
  return case when v_attempt_count < v_max_attempts then 'retry' else 'error' end;
end;
$$;

-- Releasing a job that never called its provider must not burn or refund a
-- failure attempt.  Ownership checks make release safe under parallel pools.
create or replace function public.twss_release_enrichment(
  p_ids bigint[],
  p_owner text,
  p_retry_after_seconds integer default 300
)
returns integer
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_changed integer := 0;
begin
  if nullif(pg_catalog.btrim(coalesce(p_owner, '')), '') is null then
    raise exception 'enrichment_owner_required' using errcode = '22023';
  end if;

  update public.stock_enrichment_queue q
  set status = 'pending',
      next_retry_at = pg_catalog.clock_timestamp() + pg_catalog.make_interval(
        secs => greatest(30, least(coalesce(p_retry_after_seconds, 300), 21600))
      ),
      lease_owner = null,
      lease_until = null,
      lease_renewed_at = null,
      updated_at = pg_catalog.clock_timestamp()
  where q.id = any(coalesce(p_ids, '{}'::bigint[]))
    and q.status = 'running'
    and q.lease_owner = p_owner;

  get diagnostics v_changed = row_count;
  return v_changed;
end;
$$;

revoke all on function public.twss_claim_enrichment_batch(text, integer, integer, text[])
  from public, anon, authenticated;
revoke all on function public.twss_renew_enrichment_leases(bigint[], text, integer)
  from public, anon, authenticated;
revoke all on function public.twss_complete_enrichment(bigint, text, date, jsonb)
  from public, anon, authenticated;
revoke all on function public.twss_fail_enrichment(bigint, text, text, text, integer)
  from public, anon, authenticated;
revoke all on function public.twss_release_enrichment(bigint[], text, integer)
  from public, anon, authenticated;

grant execute on function public.twss_claim_enrichment_batch(text, integer, integer, text[])
  to service_role;
grant execute on function public.twss_renew_enrichment_leases(bigint[], text, integer)
  to service_role;
grant execute on function public.twss_complete_enrichment(bigint, text, date, jsonb)
  to service_role;
grant execute on function public.twss_fail_enrichment(bigint, text, text, text, integer)
  to service_role;
grant execute on function public.twss_release_enrichment(bigint[], text, integer)
  to service_role;

revoke all on table public.stock_enrichment_queue from public, anon, authenticated;
grant select, insert, update, delete on table public.stock_enrichment_queue to service_role;
