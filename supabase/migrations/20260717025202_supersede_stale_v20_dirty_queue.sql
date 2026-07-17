-- Keep the incremental model queue bounded to the active point-in-time cycle.
-- Late enrichment for an older trading date must not wake the current model
-- forever, but the queue row remains auditable as superseded.

alter table public.v20_model_dirty_queue
  drop constraint if exists v20_model_dirty_queue_status_check;

alter table public.v20_model_dirty_queue
  add constraint v20_model_dirty_queue_status_check
  check (status in ('pending', 'running', 'success', 'error', 'superseded'));

create or replace function public.twss_supersede_stale_v20_dirty_queue(
  p_data_date date,
  p_model_version text
)
returns integer
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_changed integer := 0;
begin
  if p_data_date is null
    or nullif(pg_catalog.btrim(coalesce(p_model_version, '')), '') is null
  then
    raise exception 'invalid_v20_dirty_supersede' using errcode = '22023';
  end if;

  update public.v20_model_dirty_queue q
  set status = 'superseded',
      claimed_version = null,
      attempt_count = 0,
      next_retry_at = null,
      lease_owner = null,
      lease_until = null,
      last_error = 'superseded_by_active_cycle',
      completed_at = pg_catalog.clock_timestamp(),
      updated_at = pg_catalog.clock_timestamp()
  where (
      q.data_date < p_data_date
      or (q.data_date <= p_data_date and q.model_version <> p_model_version)
    )
    and (
      q.status in ('pending', 'error')
      or (q.status = 'running' and q.lease_until < pg_catalog.clock_timestamp())
    );

  get diagnostics v_changed = row_count;
  return v_changed;
end;
$$;

create or replace function public.twss_mark_v20_dirty_after_enrichment()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_active_date date;
begin
  if new.status = 'success' and old.status is distinct from 'success' then
    select s.cycle_date
    into v_active_date
    from public.stock_sync_state s
    where s.job_key = 'universe';

    if v_active_date is not null and new.data_date = v_active_date then
      perform public.twss_enqueue_v20_dirty_symbol(
        new.symbol,
        new.data_date,
        new.group_name,
        null
      );
    end if;
  end if;
  return new;
end;
$$;

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

  perform public.twss_supersede_stale_v20_dirty_queue(p_data_date, p_model_version);

  return query
  with candidates as (
    select q.id
    from public.v20_model_dirty_queue q
    where q.model_version = p_model_version
      and q.data_date = p_data_date
      and q.attempt_count < q.max_attempts
      and (
        (q.status in ('pending', 'error')
          and (q.next_retry_at is null or q.next_retry_at <= pg_catalog.clock_timestamp()))
        or (q.status = 'running' and q.lease_until < pg_catalog.clock_timestamp())
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
      lease_until = pg_catalog.clock_timestamp() + pg_catalog.make_interval(secs => v_lease_seconds),
      last_error = null,
      completed_at = null,
      updated_at = pg_catalog.clock_timestamp()
  from candidates c
  where q.id = c.id
  returning q.*;
end;
$$;

create or replace function public.twss_cron_v20_due()
returns boolean
language plpgsql
stable
set search_path = ''
as $$
declare
  v_due boolean := false;
  v_dirty boolean := false;
  v_cycle_date date;
  v_model_version text;
begin
  select u.cycle_date
  into v_cycle_date
  from public.stock_sync_state u
  where u.job_key = 'universe';

  select coalesce(nullif(s.details ->> 'modelVersion', ''), '20.1')
  into v_model_version
  from public.stock_sync_state s
  where s.job_key = 'v20_model';

  v_model_version := coalesce(v_model_version, '20.1');

  select s.job_key is null
      or (v_cycle_date is not null and (
        s.cycle_date is distinct from v_cycle_date
        or nullif(s.details ->> 'publishedDataDate', '')::date is distinct from v_cycle_date
      ))
      or s.processed_count < s.total_items
      or (s.status = 'error'
          and coalesce(s.next_run_at, pg_catalog.clock_timestamp()) <= pg_catalog.clock_timestamp())
  into v_due
  from (select 1) seed
  left join public.stock_sync_state s on s.job_key = 'v20_model';

  if v_cycle_date is not null then
    select exists (
      select 1
      from public.v20_model_dirty_queue q
      where q.data_date = v_cycle_date
        and q.model_version = v_model_version
        and (
          (q.status in ('pending', 'error')
            and q.attempt_count < q.max_attempts
            and coalesce(q.next_retry_at, pg_catalog.clock_timestamp())
                <= pg_catalog.clock_timestamp())
          or (q.status = 'running' and q.lease_until < pg_catalog.clock_timestamp())
        )
    ) into v_dirty;
  end if;

  return coalesce(v_due, false) or coalesce(v_dirty, false);
end;
$$;

revoke all on function public.twss_supersede_stale_v20_dirty_queue(date, text)
  from public, anon, authenticated;
revoke all on function public.twss_mark_v20_dirty_after_enrichment()
  from public, anon, authenticated;
revoke all on function public.twss_claim_v20_dirty_batch(text, text, date, integer, integer)
  from public, anon, authenticated;

grant execute on function public.twss_supersede_stale_v20_dirty_queue(date, text)
  to service_role;
grant execute on function public.twss_claim_v20_dirty_batch(text, text, date, integer, integer)
  to service_role;

do $$
declare
  v_data_date date;
  v_model_version text;
begin
  select u.cycle_date
  into v_data_date
  from public.stock_sync_state u
  where u.job_key = 'universe';

  select coalesce(nullif(s.details ->> 'modelVersion', ''), '20.1')
  into v_model_version
  from public.stock_sync_state s
  where s.job_key = 'v20_model';

  if v_data_date is not null then
    perform public.twss_supersede_stale_v20_dirty_queue(
      v_data_date,
      coalesce(v_model_version, '20.1')
    );
  end if;
end;
$$;

comment on function public.twss_supersede_stale_v20_dirty_queue(date, text) is
  'Settles obsolete incremental re-score work without rewriting immutable recommendation runs.';
comment on function public.twss_cron_v20_due() is
  'Wakes the v20 worker only for the active universe date and active model version.';
