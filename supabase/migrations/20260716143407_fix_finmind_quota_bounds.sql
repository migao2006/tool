-- PostgreSQL treats LEAST/GREATEST as conditional expressions, not functions
-- in pg_catalog.  Schema-qualifying them makes every quota reservation fail
-- with 42883 before either FinMind pool can claim work.

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
  safe_cap := greatest(0, least(safe_limit, coalesce(p_claim_cap, safe_limit)));
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('twss-api-quota:' || p_source, 0)
  );

  select coalesce(pg_catalog.sum(r.units), 0),
         pg_catalog.min(r.reserved_at + interval '60 minutes')
  into used_units, retry_after
  from public.twss_api_quota_reservations r
  where r.source = p_source
    and r.reserved_at > v_now - interval '60 minutes';

  available_units := least(greatest(0, safe_limit - used_units), safe_cap);
  if coalesce(pg_catalog.cardinality(p_item_costs), 0) > 0 then
    foreach item_cost in array p_item_costs loop
      item_cost := greatest(1, least(20, coalesce(item_cost, 1)));
      if claimed_units + item_cost
        + (case when item_count = 0 then greatest(0, p_overhead) else 0 end)
        > available_units then
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

  return pg_catalog.jsonb_build_object(
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

revoke all on function public.twss_reserve_api_batch(
  text, integer[], integer, integer, integer, jsonb
) from public, anon, authenticated;
grant execute on function public.twss_reserve_api_batch(
  text, integer[], integer, integer, integer, jsonb
) to service_role;

comment on function public.twss_reserve_api_batch(
  text, integer[], integer, integer, integer, jsonb
) is
  'Service-only atomic rolling-hour FinMind reservation for independent primary and secondary credentials; bounds use PostgreSQL LEAST/GREATEST expressions.';
