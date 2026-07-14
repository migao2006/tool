-- Keep interactive history repair useful without allowing it to starve the
-- scheduled universe/deep accumulation.  All callers still share the same
-- atomic rolling-hour ledger; public_history additionally has its own small
-- hourly allowance and must leave headroom for cron jobs.

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
  public_used_units integer := 0;
  public_limit integer := 0;
  reserved_headroom integer := 0;
  available_units integer := 0;
  claimed_units integer := 0;
  item_count integer := 0;
  item_cost integer;
  reservation_id bigint;
  retry_after timestamptz;
  is_public_history boolean := coalesce(p_metadata ->> 'job', '') = 'public_history';
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

  select
    coalesce(sum(units), 0),
    coalesce(sum(units) filter (where metadata ->> 'job' = 'public_history'), 0),
    min(reserved_at + interval '60 minutes')
  into used_units, public_used_units, retry_after
  from public.twss_api_quota_reservations
  where source = p_source
    and reserved_at > v_now - interval '60 minutes';

  if is_public_history then
    public_limit := case when safe_limit = 600 then 60 else 30 end;
    -- Leave enough room for at least one normal scheduled symbol while still
    -- letting a user repair a missing chart when the ledger is nearly full.
    reserved_headroom := case when safe_limit = 600 then 20 else 10 end;
    available_units := least(
      greatest(0, safe_limit - reserved_headroom - used_units),
      greatest(0, public_limit - public_used_units),
      safe_cap
    );
  else
    available_units := least(greatest(0, safe_limit - used_units), safe_cap);
  end if;

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
    'publicHistoryUsedBefore', public_used_units,
    'publicHistoryLimit', case when is_public_history then public_limit else null end,
    'reservedHeadroom', case when is_public_history then reserved_headroom else 0 end,
    'remaining', greatest(0, safe_limit - used_units - claimed_units),
    'retryAfterAt', case when item_count = 0 and used_units > 0 then retry_after else null end
  );
end;
$$;

revoke all on function public.twss_reserve_api_batch(text, integer[], integer, integer, integer, jsonb)
  from public, anon, authenticated;
grant execute on function public.twss_reserve_api_batch(text, integer[], integer, integer, integer, jsonb)
  to service_role;
