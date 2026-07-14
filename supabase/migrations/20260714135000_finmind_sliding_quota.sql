-- Keep every scheduled and manual persistent sync below FinMind's documented
-- rolling-hour allowance.  A database advisory lock makes reservations atomic
-- across universe, listed, OTC and ETF Edge Function invocations.

create table if not exists public.twss_api_quota_reservations (
  id bigint generated always as identity primary key,
  source text not null check (source = 'finmind'),
  units integer not null check (units > 0 and units <= 600),
  reserved_at timestamptz not null default clock_timestamp(),
  metadata jsonb not null default '{}'::jsonb
);

create index if not exists twss_api_quota_reservations_lookup_idx
  on public.twss_api_quota_reservations (source, reserved_at desc);

alter table public.twss_api_quota_reservations enable row level security;
revoke all on table public.twss_api_quota_reservations from public, anon, authenticated;
grant select, insert, delete on table public.twss_api_quota_reservations to service_role;
grant usage, select on sequence public.twss_api_quota_reservations_id_seq to service_role;

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
  if p_source <> 'finmind' then
    raise exception 'Unsupported API quota source';
  end if;
  if p_hourly_limit not in (300, 600) then
    raise exception 'FinMind hourly limit must be 300 or 600';
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
    'retryAfterAt', case when item_count = 0 and used_units > 0 then retry_after else null end
  );
end;
$$;

revoke all on function public.twss_reserve_api_batch(text, integer[], integer, integer, integer, jsonb)
  from public, anon, authenticated;
grant execute on function public.twss_reserve_api_batch(text, integer[], integer, integer, integer, jsonb)
  to service_role;

-- Keep the small reservation ledger bounded independently of long market
-- history.  This job does not affect the active rolling 60-minute window.
do $$
declare
  existing_job bigint;
begin
  for existing_job in
    select jobid from cron.job where jobname = 'twss-prune-api-quota'
  loop
    perform cron.unschedule(existing_job);
  end loop;
end
$$;

select cron.schedule(
  'twss-prune-api-quota',
  '40 7 * * *',
  $job$
    delete from public.twss_api_quota_reservations
    where reserved_at < clock_timestamp() - interval '2 days';
  $job$
);
