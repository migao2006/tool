-- A Champion promotion changes the active model even when the source data date
-- and the previous cycle are otherwise complete. The cron gate must therefore
-- compare the worker state with the immutable Champion heads instead of waiting
-- for a new trading date or dirty-symbol event.
create or replace function public.twss_cron_v20_due()
returns boolean
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
  v_due boolean := false;
  v_dirty boolean := false;
  v_cycle_date date;
  v_state_model_version text;
  v_champion_model_version text;
  v_active_model_version text;
begin
  select u.cycle_date
  into v_cycle_date
  from public.stock_sync_state u
  where u.job_key = 'universe';

  select nullif(s.details ->> 'modelVersion', '')
  into v_state_model_version
  from public.stock_sync_state s
  where s.job_key = 'v20_model';

  select case
      when pg_catalog.count(*) = 2
        and pg_catalog.count(distinct r.model_version) = 1
      then pg_catalog.min(r.model_version)
      else null
    end
  into v_champion_model_version
  from public.v20_model_channel_heads h
  join public.v20_model_releases r on r.id = h.release_id
  where h.channel = 'champion'
    and h.model_key in ('short', 'medium');

  v_active_model_version := coalesce(
    v_champion_model_version,
    v_state_model_version,
    '20.1'
  );

  select s.job_key is null
      or (
        v_champion_model_version is not null
        and v_state_model_version is distinct from v_champion_model_version
      )
      or (v_cycle_date is not null and (
        s.cycle_date is distinct from v_cycle_date
        or nullif(s.details ->> 'publishedDataDate', '')::date is distinct from v_cycle_date
      ))
      or s.processed_count < s.total_items
      or (
        s.status in ('error', 'partial')
        and coalesce(s.next_run_at, pg_catalog.clock_timestamp())
          <= pg_catalog.clock_timestamp()
      )
  into v_due
  from (select 1) seed
  left join public.stock_sync_state s on s.job_key = 'v20_model';

  if v_cycle_date is not null then
    select exists (
      select 1
      from public.v20_model_dirty_queue q
      where q.data_date = v_cycle_date
        and q.model_version = v_active_model_version
        and (
          (
            q.status in ('pending', 'error')
            and q.attempt_count < q.max_attempts
            and coalesce(q.next_retry_at, pg_catalog.clock_timestamp())
              <= pg_catalog.clock_timestamp()
          )
          or (
            q.status = 'running'
            and q.lease_until < pg_catalog.clock_timestamp()
          )
        )
    ) into v_dirty;
  end if;

  return coalesce(v_due, false) or coalesce(v_dirty, false);
end;
$$;

revoke all on function public.twss_cron_v20_due()
  from public, anon, authenticated;

comment on function public.twss_cron_v20_due() is
  'Wakes v20 for a Champion-version change, unfinished/retryable cycle, active-version dirty work, or a new universe date.';
