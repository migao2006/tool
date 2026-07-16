-- Split the two FinMind credentials into independently observable jobs and
-- stop pg_cron from dispatching HTTP work when there is nothing to do.

update public.twss_api_quota_reservations
set source = 'finmind_primary'
where source = 'finmind';

alter table public.twss_api_quota_reservations
  drop constraint if exists twss_api_quota_reservations_source_check;
alter table public.twss_api_quota_reservations
  add constraint twss_api_quota_reservations_source_check
  check (source in ('finmind_primary', 'finmind_secondary'));

create or replace function public.twss_reserve_api_batch(
  p_source text,
  p_item_costs integer[],
  p_overhead integer,
  p_hourly_limit integer,
  p_claim_cap integer,
  p_metadata jsonb default '{}'::jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_now timestamptz := pg_catalog.clock_timestamp();
  safe_limit integer;
  safe_cap integer;
  used_units integer := 0;
  available_units integer := 0;
  claimed_units integer := 0;
  item_count integer := 0;
  item_cost integer;
  reservation_id bigint;
  retry_after timestamptz;
begin
  if p_source not in ('finmind_primary', 'finmind_secondary') then
    raise exception 'Unsupported API quota source';
  end if;
  if p_hourly_limit not in (300, 600) then
    raise exception 'FinMind hourly limit must be 300 or 600 per credential';
  end if;

  safe_limit := p_hourly_limit;
  safe_cap := pg_catalog.greatest(0, pg_catalog.least(safe_limit, coalesce(p_claim_cap, safe_limit)));
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('twss-api-quota:' || p_source, 0));

  select coalesce(sum(r.units), 0), min(r.reserved_at + interval '60 minutes')
  into used_units, retry_after
  from public.twss_api_quota_reservations r
  where r.source = p_source
    and r.reserved_at > v_now - interval '60 minutes';

  available_units := pg_catalog.least(pg_catalog.greatest(0, safe_limit - used_units), safe_cap);
  if coalesce(pg_catalog.cardinality(p_item_costs), 0) > 0 then
    foreach item_cost in array p_item_costs loop
      item_cost := pg_catalog.greatest(1, pg_catalog.least(20, coalesce(item_cost, 1)));
      if claimed_units + item_cost
        + (case when item_count = 0 then pg_catalog.greatest(0, p_overhead) else 0 end)
        > available_units then
        exit;
      end if;
      if item_count = 0 then
        claimed_units := claimed_units + pg_catalog.greatest(0, p_overhead);
      end if;
      claimed_units := claimed_units + item_cost;
      item_count := item_count + 1;
    end loop;
  end if;

  if claimed_units > 0 then
    insert into public.twss_api_quota_reservations (source, units, metadata)
    values (p_source, claimed_units, coalesce(p_metadata, '{}'::jsonb))
    returning id into reservation_id;
  end if;

  return pg_catalog.jsonb_build_object(
    'reservationId', reservation_id,
    'items', item_count,
    'claimed', claimed_units,
    'usedBefore', used_units,
    'hourlyLimit', safe_limit,
    'remaining', pg_catalog.greatest(0, safe_limit - used_units - claimed_units),
    'retryAfterAt', case when item_count = 0 and used_units > 0 then retry_after else null end,
    'quotaSource', p_source
  );
end;
$$;

revoke all on function public.twss_reserve_api_batch(text, integer[], integer, integer, integer, jsonb)
  from public, anon, authenticated;
grant execute on function public.twss_reserve_api_batch(text, integer[], integer, integer, integer, jsonb)
  to service_role;

insert into public.stock_sync_state (job_key, group_name, status, details)
select 'enrichment_primary', 'enrichment', e.status,
       coalesce(e.details, '{}'::jsonb) || '{"pool":"primary"}'::jsonb
from (select * from public.stock_sync_state where job_key = 'enrichment' limit 1) e
on conflict (job_key) do nothing;

insert into public.stock_sync_state (job_key, group_name, status, details)
values ('enrichment_primary', 'enrichment', 'pending', '{"pool":"primary"}'::jsonb),
       ('enrichment_secondary', 'enrichment', 'pending', '{"pool":"secondary"}'::jsonb)
on conflict (job_key) do nothing;

create or replace function public.twss_refresh_enrichment_state()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if new.job_key not in ('enrichment_primary', 'enrichment_secondary') then
    return new;
  end if;

  insert into public.stock_sync_state (
    job_key, group_name, cycle_date, total_items, processed_count, status,
    last_symbol, last_error, started_at, last_success_at, next_run_at, details, updated_at
  )
  select
    'enrichment', 'enrichment', max(s.cycle_date), coalesce(sum(s.total_items), 0),
    coalesce(sum(s.processed_count), 0),
    case
      when bool_or(s.status = 'running') then 'running'
      when bool_or(s.status = 'error') then 'error'
      when bool_or(s.status = 'partial') then 'partial'
      when bool_or(s.status = 'pending') then 'pending'
      else 'success'
    end,
    (array_agg(s.last_symbol order by s.updated_at desc) filter (where s.last_symbol is not null))[1],
    (array_agg(s.last_error order by s.updated_at desc) filter (where s.last_error is not null))[1],
    min(s.started_at), max(s.last_success_at), min(s.next_run_at),
    pg_catalog.jsonb_build_object('aggregate', true, 'pools',
      coalesce(pg_catalog.jsonb_object_agg(
        pg_catalog.replace(s.job_key, 'enrichment_', ''), s.details
      ), '{}'::jsonb)
    ),
    pg_catalog.clock_timestamp()
  from public.stock_sync_state s
  where s.job_key in ('enrichment_primary', 'enrichment_secondary')
  on conflict (job_key) do update set
    cycle_date = excluded.cycle_date,
    total_items = excluded.total_items,
    processed_count = excluded.processed_count,
    status = excluded.status,
    last_symbol = excluded.last_symbol,
    last_error = excluded.last_error,
    started_at = excluded.started_at,
    last_success_at = excluded.last_success_at,
    next_run_at = excluded.next_run_at,
    details = excluded.details,
    updated_at = excluded.updated_at;
  return new;
end;
$$;

revoke all on function public.twss_refresh_enrichment_state()
  from public, anon, authenticated;

drop trigger if exists twss_refresh_enrichment_state on public.stock_sync_state;
create trigger twss_refresh_enrichment_state
after insert or update on public.stock_sync_state
for each row execute function public.twss_refresh_enrichment_state();

-- Trigger one initial aggregation without discarding the legacy row/API.
update public.stock_sync_state
set updated_at = pg_catalog.clock_timestamp()
where job_key = 'enrichment_primary';

create or replace function public.twss_cron_deep_due(p_group text)
returns boolean
language sql
stable
set search_path = ''
as $$
  select case when u.cycle_date is null then false else
    d.job_key is null
    or d.cycle_date is distinct from u.cycle_date
    or d.total_items = 0
    or d.processed_count < d.total_items
    or (d.status = 'error' and coalesce(d.next_run_at, pg_catalog.clock_timestamp()) <= pg_catalog.clock_timestamp())
  end
  from (select cycle_date from public.stock_sync_state where job_key = 'universe') u
  left join public.stock_sync_state d on d.job_key = 'deep_' || p_group;
$$;

create or replace function public.twss_cron_enrichment_due()
returns boolean
language sql
stable
set search_path = ''
as $$
  select exists (
    select 1 from public.stock_enrichment_queue q
    where (q.status = 'pending' and coalesce(q.next_retry_at, pg_catalog.clock_timestamp()) <= pg_catalog.clock_timestamp())
       or (q.status = 'running' and q.lease_until < pg_catalog.clock_timestamp())
       or (q.status = 'error' and q.attempt_count < q.max_attempts
           and coalesce(q.next_retry_at, pg_catalog.clock_timestamp()) <= pg_catalog.clock_timestamp())
  );
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
begin
  select s.job_key is null
      or (u.cycle_date is not null and (
        s.cycle_date is distinct from u.cycle_date
        or nullif(s.details ->> 'publishedDataDate', '')::date is distinct from u.cycle_date
      ))
      or s.processed_count < s.total_items
      or (s.status = 'error' and coalesce(s.next_run_at, pg_catalog.clock_timestamp()) <= pg_catalog.clock_timestamp())
  into v_due
  from (select cycle_date from public.stock_sync_state where job_key = 'universe') u
  left join public.stock_sync_state s on s.job_key = 'v20_model';

  if pg_catalog.to_regclass('public.v20_model_dirty_queue') is not null then
    execute $query$
      select exists (
        select 1 from public.v20_model_dirty_queue q
        where (
          coalesce(to_jsonb(q) ->> 'status', 'pending') in ('pending', 'error')
          and coalesce((to_jsonb(q) ->> 'attempt_count')::integer, 0)
              < coalesce((to_jsonb(q) ->> 'max_attempts')::integer, 1)
          and coalesce((to_jsonb(q) ->> 'next_retry_at')::timestamptz, pg_catalog.clock_timestamp())
              <= pg_catalog.clock_timestamp()
        ) or (
          to_jsonb(q) ->> 'status' = 'running'
          and (to_jsonb(q) ->> 'lease_until')::timestamptz < pg_catalog.clock_timestamp()
        )
      )
    $query$ into v_dirty;
  end if;
  return coalesce(v_due, false) or coalesce(v_dirty, false);
end;
$$;

create or replace function public.twss_cron_v19_rankings_due()
returns boolean
language sql
stable
set search_path = ''
as $$
  with latest as (
    select h.group_name, max(h.score_date) as score_date
    from public.opportunity_score_history h
    where h.model_version = '16.3'
    group by h.group_name
  ), history as (
    select l.group_name, l.score_date, count(*)::bigint as row_count,
           max(h.created_at) as changed_at,
           case when exists (
             select 1 from public.opportunity_ranking_cycles c
             where c.group_name = l.group_name and c.score_date = l.score_date
               and c.model_version = '16.3' and c.status = 'final'
           ) then 'final' else 'provisional' end as desired_status
    from latest l
    join public.opportunity_score_history h on h.group_name = l.group_name
      and h.score_date = l.score_date and h.model_version = '16.3'
    group by l.group_name, l.score_date
  ), snapshots as (
    select s.group_name, s.score_date, count(*)::bigint as row_count,
           max(s.generated_at) as generated_at,
           bool_and(s.cycle_status = h.desired_status) as status_matches
    from public.v19_ranking_snapshots s
    join history h on h.group_name = s.group_name and h.score_date = s.score_date
    where s.model_version = '16.3'
    group by s.group_name, s.score_date
  )
  select exists (
    select 1 from history h
    left join snapshots s using (group_name, score_date)
    where s.row_count is distinct from h.row_count
       or s.generated_at is null or s.generated_at < h.changed_at
       or not coalesce(s.status_matches, false)
  );
$$;

revoke all on function public.twss_cron_deep_due(text) from public, anon, authenticated;
revoke all on function public.twss_cron_enrichment_due() from public, anon, authenticated;
revoke all on function public.twss_cron_v20_due() from public, anon, authenticated;
revoke all on function public.twss_cron_v19_rankings_due() from public, anon, authenticated;

do $$
declare existing_job bigint;
begin
  for existing_job in
    select jobid from cron.job where jobname in (
      'twss-deep-listed', 'twss-deep-otc', 'twss-deep-etf',
      'twss-enrichment-primary-weekday', 'twss-enrichment-secondary-weekday',
      'twss-v20-model-weekday', 'twss-v20-model-weekday-final',
      'twss-v19-ranking-snapshots'
    )
  loop
    perform cron.unschedule(existing_job);
  end loop;
end;
$$;

select cron.schedule('twss-deep-listed', '*/2 7-15 * * 1-5', $job$
  select net.http_post(url := 'https://lfkdkdyaatdlizryiyon.supabase.co/functions/v1/twss-sync-batch', headers := jsonb_build_object('Content-Type','application/json','x-twss-sync-token',(select decrypted_secret from vault.decrypted_secrets where name='twss_sync_token')), body := '{"mode":"deep","group":"listed","limit":200}'::jsonb, timeout_milliseconds := 300000)
  where public.twss_cron_deep_due('listed');
$job$);
select cron.schedule('twss-deep-otc', '*/2 7-15 * * 1-5', $job$
  select net.http_post(url := 'https://lfkdkdyaatdlizryiyon.supabase.co/functions/v1/twss-sync-batch', headers := jsonb_build_object('Content-Type','application/json','x-twss-sync-token',(select decrypted_secret from vault.decrypted_secrets where name='twss_sync_token')), body := '{"mode":"deep","group":"otc","limit":200}'::jsonb, timeout_milliseconds := 300000)
  where public.twss_cron_deep_due('otc');
$job$);
select cron.schedule('twss-deep-etf', '*/2 7-15 * * 1-5', $job$
  select net.http_post(url := 'https://lfkdkdyaatdlizryiyon.supabase.co/functions/v1/twss-sync-batch', headers := jsonb_build_object('Content-Type','application/json','x-twss-sync-token',(select decrypted_secret from vault.decrypted_secrets where name='twss_sync_token')), body := '{"mode":"deep","group":"etf","limit":200}'::jsonb, timeout_milliseconds := 300000)
  where public.twss_cron_deep_due('etf');
$job$);

select cron.schedule('twss-enrichment-primary-weekday', '1,5,11,15,21,25,31,35,41,45,51,55 7-15 * * 1-5', $job$
  select net.http_post(url := 'https://lfkdkdyaatdlizryiyon.supabase.co/functions/v1/twss-sync-batch', headers := jsonb_build_object('Content-Type','application/json','x-twss-sync-token',(select decrypted_secret from vault.decrypted_secrets where name='twss_sync_token')), body := '{"mode":"enrichment","pool":"primary","limit":50}'::jsonb, timeout_milliseconds := 300000)
  where public.twss_cron_enrichment_due();
$job$);
select cron.schedule('twss-enrichment-secondary-weekday', '3,7,13,17,23,27,33,37,43,47,53,57 7-15 * * 1-5', $job$
  select net.http_post(url := 'https://lfkdkdyaatdlizryiyon.supabase.co/functions/v1/twss-sync-batch', headers := jsonb_build_object('Content-Type','application/json','x-twss-sync-token',(select decrypted_secret from vault.decrypted_secrets where name='twss_sync_token')), body := '{"mode":"enrichment","pool":"secondary","limit":50}'::jsonb, timeout_milliseconds := 300000)
  where public.twss_cron_enrichment_due();
$job$);

select cron.schedule('twss-v20-model-weekday', '*/2 7-15 * * 1-5', $job$
  select net.http_post(url := 'https://lfkdkdyaatdlizryiyon.supabase.co/functions/v1/twss-v20-model', headers := jsonb_build_object('Content-Type','application/json','x-twss-sync-token',(select decrypted_secret from vault.decrypted_secrets where name='twss_sync_token')), body := '{"limit":250}'::jsonb, timeout_milliseconds := 300000)
  where public.twss_cron_v20_due();
$job$);
select cron.schedule('twss-v20-model-weekday-final', '59 15 * * 1-5', $job$
  select net.http_post(url := 'https://lfkdkdyaatdlizryiyon.supabase.co/functions/v1/twss-v20-model', headers := jsonb_build_object('Content-Type','application/json','x-twss-sync-token',(select decrypted_secret from vault.decrypted_secrets where name='twss_sync_token')), body := '{"limit":250}'::jsonb, timeout_milliseconds := 300000)
  where public.twss_cron_v20_due();
$job$);

select cron.schedule('twss-v19-ranking-snapshots', '*/5 * * * *', $job$
  select public.twss_v19_refresh_available_rankings()
  where public.twss_cron_v19_rankings_due();
$job$);

comment on function public.twss_cron_enrichment_due() is
  'Cron dispatch gate: an empty or not-yet-due enrichment queue does not invoke an Edge Function.';
comment on function public.twss_cron_v20_due() is
  'Cron dispatch gate: runs only for a new/full cycle, unfinished batch, retry, or due dirty symbol.';
