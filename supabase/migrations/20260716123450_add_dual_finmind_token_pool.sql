-- Add a second independently rate-limited FinMind account without exposing
-- either credential to the browser or application logs.  Existing primary
-- reservations are moved to the primary pool so deployment cannot briefly
-- exceed that account's rolling 600 request/hour allowance.

alter table public.twss_api_quota_reservations
  drop constraint if exists twss_api_quota_reservations_source_check;

alter table public.twss_api_quota_reservations
  add constraint twss_api_quota_reservations_source_check
  check (source in ('finmind', 'finmind_primary', 'finmind_secondary'));

update public.twss_api_quota_reservations
set source = 'finmind_primary'
where source = 'finmind';

create or replace function public.twss_finmind_tokens()
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
  select jsonb_build_object(
    'primary', (
      select s.decrypted_secret
      from vault.decrypted_secrets s
      where s.name = 'finmind_api_token'
      order by s.created_at desc
      limit 1
    ),
    'secondary', (
      select s.decrypted_secret
      from vault.decrypted_secrets s
      where s.name = 'finmind_api_token_secondary'
      order by s.created_at desc
      limit 1
    )
  );
$$;

revoke all on function public.twss_finmind_tokens()
  from public, anon, authenticated;
grant execute on function public.twss_finmind_tokens()
  to service_role;

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
  v_now timestamptz := clock_timestamp();
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
  if p_source not in ('finmind', 'finmind_primary', 'finmind_secondary') then
    raise exception 'Unsupported API quota source';
  end if;
  if p_hourly_limit not in (300, 600) then
    raise exception 'FinMind hourly limit must be 300 or 600 per credential';
  end if;

  safe_limit := p_hourly_limit;
  safe_cap := greatest(0, least(safe_limit, coalesce(p_claim_cap, safe_limit)));
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('twss-api-quota:' || p_source, 0));

  select coalesce(sum(units), 0), min(reserved_at + interval '60 minutes')
    into used_units, retry_after
  from public.twss_api_quota_reservations
  where source = p_source
    and reserved_at > v_now - interval '60 minutes';

  available_units := least(greatest(0, safe_limit - used_units), safe_cap);
  if coalesce(cardinality(p_item_costs), 0) > 0 then
    foreach item_cost in array p_item_costs loop
      item_cost := greatest(1, least(20, coalesce(item_cost, 1)));
      if claimed_units + item_cost + (case when item_count = 0 then greatest(0, p_overhead) else 0 end) > available_units then
        exit;
      end if;
      if item_count = 0 then
        claimed_units := claimed_units + greatest(0, p_overhead);
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

  return jsonb_build_object(
    'reservationId', reservation_id,
    'items', item_count,
    'claimed', claimed_units,
    'usedBefore', used_units,
    'hourlyLimit', safe_limit,
    'remaining', greatest(0, safe_limit - used_units - claimed_units),
    'retryAfterAt', case when item_count = 0 and used_units > 0 then retry_after else null end,
    'quotaSource', p_source
  );
end;
$$;

revoke all on function public.twss_reserve_api_batch(text, integer[], integer, integer, integer, jsonb)
  from public, anon, authenticated;
grant execute on function public.twss_reserve_api_batch(text, integer[], integer, integer, integer, jsonb)
  to service_role;

do $$
declare
  existing_job bigint;
begin
  for existing_job in
    select jobid
    from cron.job
    where jobname in (
      'twss-enrichment-weekday',
      'twss-enrichment-primary-weekday',
      'twss-enrichment-secondary-weekday'
    )
  loop
    perform cron.unschedule(existing_job);
  end loop;
end;
$$;

select cron.schedule(
  'twss-enrichment-primary-weekday',
  '1,5,11,15,21,25,31,35,41,45,51,55 7-15 * * 1-5',
  $job$
    select net.http_post(
      url := 'https://lfkdkdyaatdlizryiyon.supabase.co/functions/v1/twss-sync-batch',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'x-twss-sync-token', (
          select decrypted_secret from vault.decrypted_secrets where name = 'twss_sync_token'
        )
      ),
      body := '{"mode":"enrichment","pool":"primary","limit":50}'::jsonb,
      timeout_milliseconds := 300000
    );
  $job$
);

select cron.schedule(
  'twss-enrichment-secondary-weekday',
  '3,7,13,17,23,27,33,37,43,47,53,57 7-15 * * 1-5',
  $job$
    select net.http_post(
      url := 'https://lfkdkdyaatdlizryiyon.supabase.co/functions/v1/twss-sync-batch',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'x-twss-sync-token', (
          select decrypted_secret from vault.decrypted_secrets where name = 'twss_sync_token'
        )
      ),
      body := '{"mode":"enrichment","pool":"secondary","limit":50}'::jsonb,
      timeout_milliseconds := 300000
    );
  $job$
);

comment on function public.twss_finmind_tokens() is
  'Service-role-only FinMind credential pool. Decrypted values never reach browser roles.';
