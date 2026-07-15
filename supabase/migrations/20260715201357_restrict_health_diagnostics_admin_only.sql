-- Operational diagnostics belong in Supabase's authenticated administration
-- surface and Edge Function logs, not in the public website or Data API.

revoke all on function public.twss_public_data_health()
  from public, anon, authenticated;
grant execute on function public.twss_public_data_health()
  to service_role;

revoke all on function public.twss_public_missing_data(integer)
  from public, anon, authenticated;
grant execute on function public.twss_public_missing_data(integer)
  to service_role;

-- Public market pages no longer consume the synchronization table.  Removing
-- both the table privilege and the permissive RLS policy prevents callers from
-- bypassing the Vercel API to read raw errors, leases, URLs or batch details.
revoke all on table public.stock_sync_state from public, anon, authenticated;
drop policy if exists stock_sync_state_public_read on public.stock_sync_state;

-- Analysis results remain public research data, but retry state and upstream
-- exception fields are internal diagnostics.  Column grants make that boundary
-- hold even when callers use Supabase's Data API directly.
revoke all on table public.stock_analysis_cache from public, anon, authenticated;
grant select (
  symbol,
  group_name,
  data_date,
  analysis_version,
  score,
  confidence,
  official,
  tier,
  stock,
  analysis,
  result,
  status,
  fetched_at,
  updated_at
) on table public.stock_analysis_cache to anon, authenticated;

-- Remove any raw optional-source message already stored inside otherwise
-- public analysis JSON.  Future writes apply the same allowlist in compactDeep.
update public.stock_analysis_cache a
set analysis = pg_catalog.jsonb_set(
  a.analysis,
  '{sourceDiagnostics}',
  coalesce((
    select pg_catalog.jsonb_object_agg(
      entry.key,
      case when pg_catalog.jsonb_typeof(entry.value) = 'object'
        then entry.value - 'message' - 'error' - 'url' - 'details'
        else '{}'::jsonb
      end
    )
    from pg_catalog.jsonb_each(a.analysis -> 'sourceDiagnostics') entry
  ), '{}'::jsonb),
  true
)
where pg_catalog.jsonb_typeof(a.analysis -> 'sourceDiagnostics') = 'object';

-- The public context RPC previously selected the whole composite row.  Rewrite
-- it to touch only the columns in the allowlist above so SECURITY INVOKER keeps
-- working without regaining access to internal diagnostics.
create or replace function public.twss_get_stock_context(p_symbol text)
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
  target record;
  v_industry text;
  v_scope text;
  v_peer_count integer;
  v_metrics jsonb;
  v_series jsonb;
  v_final_dates integer;
begin
  if p_symbol !~ '^[0-9]{4,6}[A-Za-z]?$' then
    raise exception 'invalid_symbol';
  end if;

  select
    a.symbol,
    a.group_name,
    a.data_date,
    a.analysis_version,
    a.score,
    a.stock,
    a.analysis
  into target
  from public.stock_analysis_cache a
  where a.symbol = p_symbol and a.status = 'ready'
  limit 1;

  if not found then
    return pg_catalog.jsonb_build_object('available', false, 'symbol', p_symbol);
  end if;

  v_industry := coalesce(target.stock ->> 'industry', '未分類');
  select count(*) into v_peer_count
  from public.stock_analysis_cache a
  where a.group_name = target.group_name
    and a.status = 'ready'
    and a.data_date = target.data_date
    and a.analysis_version = target.analysis_version
    and a.stock ->> 'industry' = v_industry;

  v_scope := case when v_peer_count >= 5 then 'industry' else 'group_fallback' end;
  if v_scope = 'group_fallback' then
    select count(*) into v_peer_count
    from public.stock_analysis_cache a
    where a.group_name = target.group_name
      and a.status = 'ready'
      and a.data_date = target.data_date
      and a.analysis_version = target.analysis_version;
  end if;

  if target.group_name = 'etf' then
    v_metrics := pg_catalog.jsonb_build_array(
      public.twss_peer_metric(target.group_name, v_industry, v_scope, target.data_date, target.analysis_version,
        'score', target.score, true),
      public.twss_peer_metric(target.group_name, v_industry, v_scope, target.data_date, target.analysis_version,
        'relative_strength20', nullif(target.analysis #>> '{price,relative20}', '')::numeric, true),
      public.twss_peer_metric(target.group_name, v_industry, v_scope, target.data_date, target.analysis_version,
        'volume_ratio', nullif(target.analysis #>> '{price,volumeRatio}', '')::numeric, true),
      public.twss_peer_metric(target.group_name, v_industry, v_scope, target.data_date, target.analysis_version,
        'premium_discount', pg_catalog.abs(nullif(target.analysis #>> '{etf,premiumDiscount}', '')::numeric), false),
      public.twss_peer_metric(target.group_name, v_industry, v_scope, target.data_date, target.analysis_version,
        'atr_pct', nullif(target.analysis #>> '{price,atrPct}', '')::numeric, false)
    );
  else
    v_metrics := pg_catalog.jsonb_build_array(
      public.twss_peer_metric(target.group_name, v_industry, v_scope, target.data_date, target.analysis_version,
        'score', target.score, true),
      public.twss_peer_metric(target.group_name, v_industry, v_scope, target.data_date, target.analysis_version,
        'revenue_avg3', nullif(target.analysis #>> '{revenue,avg3Yoy}', '')::numeric, true),
      public.twss_peer_metric(target.group_name, v_industry, v_scope, target.data_date, target.analysis_version,
        'revenue_acceleration', nullif(target.analysis #>> '{revenue,acceleration3}', '')::numeric, true),
      public.twss_peer_metric(target.group_name, v_industry, v_scope, target.data_date, target.analysis_version,
        'operating_margin', nullif(target.analysis #>> '{financial,operatingMargin}', '')::numeric, true),
      public.twss_peer_metric(target.group_name, v_industry, v_scope, target.data_date, target.analysis_version,
        'cash_conversion', nullif(target.analysis #>> '{financial,cashConversion}', '')::numeric, true),
      public.twss_peer_metric(target.group_name, v_industry, v_scope, target.data_date, target.analysis_version,
        'institutional_intensity', nullif(target.analysis #>> '{institutional,intensity5}', '')::numeric, true),
      public.twss_peer_metric(target.group_name, v_industry, v_scope, target.data_date, target.analysis_version,
        'relative_strength20', nullif(target.analysis #>> '{price,relative20}', '')::numeric, true),
      public.twss_peer_metric(target.group_name, v_industry, v_scope, target.data_date, target.analysis_version,
        'pe', case when nullif(target.stock ->> 'pe', '')::numeric > 0
          then nullif(target.stock ->> 'pe', '')::numeric else null end, false)
    );
  end if;

  select count(*) into v_final_dates
  from public.opportunity_ranking_cycles
  where group_name = target.group_name
    and model_version = '16.3'
    and status = 'final';

  with ranked as (
    select h.symbol, h.score_date, h.score, h.confidence,
      rank() over (
        partition by h.score_date
        order by h.score desc nulls last, h.confidence desc
      ) as rank_value
    from public.opportunity_score_history h
    join public.opportunity_ranking_cycles c
      on c.group_name = h.group_name
      and c.score_date = h.score_date
      and c.model_version = h.model_version
      and c.status = 'final'
    where h.group_name = target.group_name
      and h.model_version = '16.3'
      and h.official
  )
  select coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
    'date', score_date, 'score', score, 'confidence', confidence, 'rank', rank_value
  ) order by score_date), '[]'::jsonb)
  into v_series
  from (
    select * from ranked
    where symbol = p_symbol
    order by score_date desc
    limit 20
  ) recent;

  return pg_catalog.jsonb_build_object(
    'available', true,
    'symbol', p_symbol,
    'group', target.group_name,
    'industry', v_industry,
    'peer', pg_catalog.jsonb_build_object(
      'scope', v_scope,
      'peerCount', v_peer_count,
      'dataDate', target.data_date,
      'analysisVersion', target.analysis_version,
      'metrics', v_metrics
    ),
    'trend', pg_catalog.jsonb_build_object(
      'status', case when v_final_dates >= 2 then 'ready' else 'accumulating' end,
      'finalDateCount', v_final_dates,
      'minimumFinalDates', 2,
      'series', v_series
    )
  );
end;
$$;

revoke all on function public.twss_get_stock_context(text) from public;
grant execute on function public.twss_get_stock_context(text)
  to anon, authenticated, service_role;
