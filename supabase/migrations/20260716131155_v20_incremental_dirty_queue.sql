-- Durable, service-only incremental v20 re-score queue. Enrichment completion
-- marks only the affected symbol dirty; it never changes the full-market cycle
-- key or the last-good public pointer.

create table if not exists public.v20_model_dirty_queue (
  id bigint generated always as identity primary key,
  symbol text not null references public.stock_master(symbol) on delete cascade,
  data_date date not null,
  group_name text not null check (group_name in ('listed', 'otc', 'etf')),
  model_version text not null,
  status text not null default 'pending'
    check (status in ('pending', 'running', 'success', 'error')),
  dirty_version bigint not null default 1 check (dirty_version > 0),
  claimed_version bigint,
  attempt_count integer not null default 0 check (attempt_count >= 0),
  max_attempts integer not null default 5 check (max_attempts between 1 and 20),
  next_retry_at timestamptz,
  lease_owner text,
  lease_until timestamptz,
  last_error text,
  completed_at timestamptz,
  created_at timestamptz not null default clock_timestamp(),
  updated_at timestamptz not null default clock_timestamp(),
  constraint v20_model_dirty_queue_symbol_cycle_key
    unique (symbol, data_date, model_version),
  constraint v20_model_dirty_queue_lease_consistency check (
    (status = 'running' and lease_owner is not null and lease_until is not null
      and claimed_version is not null)
    or (status <> 'running' and lease_owner is null and lease_until is null
      and claimed_version is null)
  )
);

create index if not exists v20_model_dirty_queue_claim_idx
  on public.v20_model_dirty_queue
    (data_date desc, model_version, next_retry_at, updated_at, id)
  where status in ('pending', 'error');

create index if not exists v20_model_dirty_queue_expired_lease_idx
  on public.v20_model_dirty_queue (lease_until, data_date desc, model_version, id)
  where status = 'running';

alter table public.v20_model_dirty_queue enable row level security;

-- Deliberately no anon/authenticated policy: this is infrastructure state.
revoke all on table public.v20_model_dirty_queue from public, anon, authenticated;
grant select, insert, update, delete on table public.v20_model_dirty_queue to service_role;
revoke all on sequence public.v20_model_dirty_queue_id_seq from public, anon, authenticated;
grant usage, select on sequence public.v20_model_dirty_queue_id_seq to service_role;

drop trigger if exists v20_model_dirty_queue_set_updated_at on public.v20_model_dirty_queue;
create trigger v20_model_dirty_queue_set_updated_at
before update on public.v20_model_dirty_queue
for each row execute function public.set_updated_at();

create or replace function public.twss_enqueue_v20_dirty_symbol(
  p_symbol text,
  p_data_date date,
  p_group_name text,
  p_model_version text default null
)
returns bigint
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_model_version text;
  v_id bigint;
begin
  if nullif(pg_catalog.btrim(coalesce(p_symbol, '')), '') is null
    or p_data_date is null
    or p_group_name not in ('listed', 'otc', 'etf')
  then
    raise exception 'invalid_v20_dirty_symbol' using errcode = '22023';
  end if;

  select coalesce(
    nullif(pg_catalog.btrim(coalesce(p_model_version, '')), ''),
    nullif(s.details ->> 'modelVersion', ''),
    '20.0'
  )
  into v_model_version
  from (select 1) seed
  left join public.stock_sync_state s on s.job_key = 'v20_model';

  insert into public.v20_model_dirty_queue (
    symbol, data_date, group_name, model_version, status, dirty_version,
    attempt_count, next_retry_at, last_error, completed_at
  )
  values (
    pg_catalog.btrim(p_symbol), p_data_date, p_group_name, v_model_version,
    'pending', 1, 0, null, null, null
  )
  on conflict (symbol, data_date, model_version) do update
  set group_name = excluded.group_name,
      dirty_version = public.v20_model_dirty_queue.dirty_version + 1,
      status = case
        when public.v20_model_dirty_queue.status = 'running' then 'running'
        else 'pending'
      end,
      attempt_count = case
        when public.v20_model_dirty_queue.status = 'running'
          then public.v20_model_dirty_queue.attempt_count
        else 0
      end,
      next_retry_at = null,
      last_error = null,
      completed_at = null,
      updated_at = clock_timestamp()
  returning id into v_id;

  return v_id;
end;
$$;

create or replace function public.twss_mark_v20_dirty_after_enrichment()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if new.status = 'success' and old.status is distinct from 'success' then
    perform public.twss_enqueue_v20_dirty_symbol(
      new.symbol,
      new.data_date,
      new.group_name,
      null
    );
  end if;
  return new;
end;
$$;

drop trigger if exists stock_enrichment_queue_mark_v20_dirty
  on public.stock_enrichment_queue;
create trigger stock_enrichment_queue_mark_v20_dirty
after update of status on public.stock_enrichment_queue
for each row execute function public.twss_mark_v20_dirty_after_enrichment();

create or replace function public.twss_claim_v20_dirty_batch(
  p_owner text,
  p_model_version text,
  p_data_date date,
  p_limit integer default 100,
  p_lease_seconds integer default 420
)
returns setof public.v20_model_dirty_queue
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_limit integer := greatest(1, least(coalesce(p_limit, 100), 500));
  v_lease_seconds integer := greatest(60, least(coalesce(p_lease_seconds, 420), 900));
begin
  if nullif(pg_catalog.btrim(coalesce(p_owner, '')), '') is null
    or nullif(pg_catalog.btrim(coalesce(p_model_version, '')), '') is null
    or p_data_date is null
  then
    raise exception 'invalid_v20_dirty_claim' using errcode = '22023';
  end if;

  return query
  with candidates as (
    select q.id
    from public.v20_model_dirty_queue q
    where q.model_version = p_model_version
      and q.data_date = p_data_date
      and q.attempt_count < q.max_attempts
      and (
        (q.status in ('pending', 'error')
          and (q.next_retry_at is null or q.next_retry_at <= clock_timestamp()))
        or (q.status = 'running' and q.lease_until < clock_timestamp())
      )
    order by q.updated_at, q.id
    limit v_limit
    for update skip locked
  )
  update public.v20_model_dirty_queue q
  set status = 'running',
      claimed_version = q.dirty_version,
      attempt_count = q.attempt_count + 1,
      next_retry_at = null,
      lease_owner = p_owner,
      lease_until = clock_timestamp() + pg_catalog.make_interval(secs => v_lease_seconds),
      last_error = null,
      completed_at = null,
      updated_at = clock_timestamp()
  from candidates c
  where q.id = c.id
  returning q.*;
end;
$$;

create or replace function public.twss_complete_v20_dirty_batch(
  p_ids bigint[],
  p_owner text
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
    raise exception 'v20_dirty_owner_required' using errcode = '22023';
  end if;

  update public.v20_model_dirty_queue q
  set status = case when q.dirty_version > q.claimed_version then 'pending' else 'success' end,
      attempt_count = case when q.dirty_version > q.claimed_version then 0 else q.attempt_count end,
      next_retry_at = null,
      lease_owner = null,
      lease_until = null,
      claimed_version = null,
      last_error = null,
      completed_at = case
        when q.dirty_version > q.claimed_version then null
        else clock_timestamp()
      end,
      updated_at = clock_timestamp()
  where q.id = any(coalesce(p_ids, '{}'::bigint[]))
    and q.status = 'running'
    and q.lease_owner = p_owner;

  get diagnostics v_changed = row_count;
  return v_changed;
end;
$$;

create or replace function public.twss_retry_v20_dirty_batch(
  p_ids bigint[],
  p_owner text,
  p_last_error text,
  p_retry_after_seconds integer default 120
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
    raise exception 'v20_dirty_owner_required' using errcode = '22023';
  end if;

  update public.v20_model_dirty_queue q
  set status = case when q.dirty_version > q.claimed_version then 'pending' else 'error' end,
      attempt_count = case when q.dirty_version > q.claimed_version then 0 else q.attempt_count end,
      next_retry_at = case
        when q.dirty_version > q.claimed_version then null
        when q.attempt_count < q.max_attempts then
          clock_timestamp() + pg_catalog.make_interval(
            secs => greatest(30, least(coalesce(p_retry_after_seconds, 120), 21600))
          )
        else null
      end,
      lease_owner = null,
      lease_until = null,
      claimed_version = null,
      last_error = case when q.dirty_version > q.claimed_version then null
        else nullif(pg_catalog.left(coalesce(p_last_error, ''), 2000), '')
      end,
      completed_at = null,
      updated_at = clock_timestamp()
  where q.id = any(coalesce(p_ids, '{}'::bigint[]))
    and q.status = 'running'
    and q.lease_owner = p_owner;

  get diagnostics v_changed = row_count;
  return v_changed;
end;
$$;

revoke all on function public.twss_enqueue_v20_dirty_symbol(text, date, text, text)
  from public, anon, authenticated;
revoke all on function public.twss_mark_v20_dirty_after_enrichment()
  from public, anon, authenticated;
revoke all on function public.twss_claim_v20_dirty_batch(text, text, date, integer, integer)
  from public, anon, authenticated;
revoke all on function public.twss_complete_v20_dirty_batch(bigint[], text)
  from public, anon, authenticated;
revoke all on function public.twss_retry_v20_dirty_batch(bigint[], text, text, integer)
  from public, anon, authenticated;

grant execute on function public.twss_enqueue_v20_dirty_symbol(text, date, text, text)
  to service_role;
grant execute on function public.twss_claim_v20_dirty_batch(text, text, date, integer, integer)
  to service_role;
grant execute on function public.twss_complete_v20_dirty_batch(bigint[], text)
  to service_role;
grant execute on function public.twss_retry_v20_dirty_batch(bigint[], text, text, integer)
  to service_role;

comment on table public.v20_model_dirty_queue is
  'Service-only coalescing queue for symbol-level v20 re-scores after enrichment. A dirty version arriving during a lease is never lost.';
comment on function public.twss_mark_v20_dirty_after_enrichment() is
  'Audited trigger boundary: it accepts no caller input and only enqueues the exact enrichment row that transitioned to success.';
